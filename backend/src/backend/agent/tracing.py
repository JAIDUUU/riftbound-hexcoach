"""Langfuse tracing around agent runs (issue #9).

`traced_run` wraps `run_agent` in a Langfuse trace: the LangChain callback captures the
graph steps and every LLM call as spans, the user id is stored hashed, the conversation
id becomes the Langfuse session id, and the trace id is returned so feedback can be
scored on it later. Without Langfuse keys it degrades to a plain untraced run, so tests
and CI never need credentials.
"""

import hashlib
from collections.abc import Sequence

from langchain_core.tools import BaseTool

from backend.agent.graph import AgentState, ChatModel, Retriever, Turn, run_agent
from backend.config import optional_env


def hash_user_id(user_id: str) -> str:
    """A stable one-way pseudonym: traces must never carry the raw user id."""
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()


def tracing_enabled() -> bool:
    return (
        optional_env("LANGFUSE_PUBLIC_KEY") is not None
        and optional_env("LANGFUSE_SECRET_KEY") is not None
    )


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
    from langfuse.langchain import CallbackHandler

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
            llm, retrieve, question, history, config={"callbacks": [CallbackHandler()]}, tools=tools
        )
        span.update(output={"outcome": state["outcome"], "answer": state["answer"]})
    langfuse.flush()
    return state, trace_id
