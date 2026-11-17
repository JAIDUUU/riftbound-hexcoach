"""Langfuse tracing around agent runs (issue #9), and feedback scores on those traces (#19).

`traced_run` wraps `run_agent` in a Langfuse trace: the LangChain callback captures the
graph steps and every LLM call as spans, the user id is stored hashed, the conversation
id becomes the Langfuse session id, and the trace id is returned so feedback can be
scored on it later (`score_feedback`). Without Langfuse keys it degrades to a plain
untraced run, so tests and CI never need credentials.
"""

import hashlib
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Literal, Protocol

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from backend.agent.graph import AgentState, ChatModel, Retriever, Turn, run_agent
from backend.config import optional_env
from backend.conversations.store import Feedback


def hash_user_id(user_id: str) -> str:
    """A stable one-way pseudonym: traces must never carry the raw user id."""
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()


def tracing_enabled() -> bool:
    return (
        optional_env("LANGFUSE_PUBLIC_KEY") is not None
        and optional_env("LANGFUSE_SECRET_KEY") is not None
    )


def _langfuse_callbacks() -> RunnableConfig:
    """Config that records graph steps, LLM calls and tool calls into the current trace."""
    from langfuse.langchain import CallbackHandler

    return {"callbacks": [CallbackHandler()]}


def run_in_open_trace(
    llm: ChatModel,
    retrieve: Retriever,
    question: str,
    tools: Sequence[BaseTool] = (),
) -> AgentState:
    """Run the agent under a trace someone else already opened (e.g. a Langfuse
    experiment item), recording steps and LLM calls without traced_run's own ask span.
    Requires Langfuse keys; keyless callers want run_agent or traced_run instead."""
    return run_agent(llm, retrieve, question, config=_langfuse_callbacks(), tools=tools)


def traced_run(
    llm: ChatModel,
    retrieve: Retriever,
    question: str,
    history: Sequence[Turn] = (),
    user_id: str | None = None,
    conversation_id: str | None = None,
    tools: Sequence[BaseTool] = (),
) -> tuple[AgentState, str | None]:
    """Run the agent; return its final state and the Langfuse trace id (None untraced)."""
    if not tracing_enabled():
        return run_agent(llm, retrieve, question, history, tools=tools), None

    from langfuse import get_client, propagate_attributes

    langfuse = get_client()
    with (
        propagate_attributes(
            user_id=hash_user_id(user_id) if user_id else None,
            session_id=conversation_id,
        ),
        langfuse.start_as_current_observation(
            name="ask",
            as_type="agent",
            input={"question": question, "history_turns": len(history)},
        ) as span,
    ):
        trace_id = langfuse.get_current_trace_id()
        state = run_agent(
            llm, retrieve, question, history, config=_langfuse_callbacks(), tools=tools
        )
        span.update(output={"outcome": state["outcome"], "answer": state["answer"]})
    langfuse.flush()
    return state, trace_id


class ScoreClient(Protocol):
    """The part of the Langfuse client that feedback uses; tests pass a fake."""

    def create_score(
        self,
        *,
        name: str,
        value: float,
        trace_id: str | None = None,
        score_id: str | None = None,
        data_type: Literal["BOOLEAN"] | None = None,
        timestamp: datetime | None = None,
    ) -> None: ...


def langfuse_scores() -> ScoreClient | None:
    """The Langfuse client for feedback scores; None without keys (feedback is then only
    stored, not scored)."""
    if not tracing_enabled():
        return None
    from langfuse import get_client

    return get_client()


def score_feedback(
    client: ScoreClient, message_id: uuid.UUID, trace_id: str, feedback: Feedback
) -> None:
    """Send the player's feedback on an answer as a score on that answer's trace.

    Langfuse overwrites a score only when its id, name and timestamp date all match, so
    the id comes from the message and the timestamp is when feedback was first given:
    a changed vote replaces the score rather than adding a second one.
    """
    client.create_score(
        name="feedback",
        value=1.0 if feedback.rating == "up" else 0.0,
        trace_id=trace_id,
        score_id=f"feedback-{message_id}",
        data_type="BOOLEAN",
        timestamp=feedback.given_at,
    )
