"""The coach behind the message endpoint (issue #12): one question in, one reply out.

`Coach` is the seam the API depends on. Given the player's question, the conversation so
far and who is asking, it runs the agent fresh and reports progress through `on_event`
(the trace id first, then graph steps and answer tokens). API tests hand the app a
scripted fake; `database_coach` is the real one: hybrid retrieval and the lookup_card
tool over Postgres, traced in Langfuse when the keys are set.

`run_on_database` is that real run without the API's types, so `backend ask` runs exactly
what the endpoint runs.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from langchain_core.tools import BaseTool
from sqlalchemy import Connection, Engine

from backend.agent.graph import AgentState, ChatModel, OnEvent, Outcome, Retriever, evidence
from backend.agent.tracing import traced_run
from backend.retrieval.repository import SearchHit
from backend.turns import Mentioned, Turn

RETRIEVAL_LIMIT = 8  # chunks per retrieval, the same as `backend ask`


@dataclass(frozen=True, slots=True)
class Question:
    """What the player asked, in which conversation. Request-level context the agent
    should see (such as @ mentions) belongs here too."""

    text: str
    history: tuple[Turn, ...]  # oldest first, already capped; excludes `text`
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    mentions: tuple[Mentioned, ...] = ()  # already resolved; see backend.mentions


@dataclass(frozen=True, slots=True)
class Reply:
    answer: str
    outcome: Outcome
    evidence: tuple[SearchHit, ...]  # what the answer was written from (graph.evidence)


class Coach(Protocol):
    def __call__(self, question: Question, on_event: OnEvent) -> Reply: ...


def card_lookup_tool(connection: Connection) -> BaseTool:
    """The lookup_card tool backed by the cards table (issue #10)."""
    from backend.agent.tools import make_lookup_card
    from backend.cards.catalog import SqlCardCatalog

    return make_lookup_card(SqlCardCatalog(connection))


def hybrid_retriever(connection: Connection, limit: int = RETRIEVAL_LIMIT) -> Retriever:
    """Hybrid (keyword + vector) search over the chunks, `limit` hits per query."""
    from backend.retrieval.embedding import embedder
    from backend.retrieval.repository import hybrid_search_chunks

    def retrieve(query: str) -> list[SearchHit]:
        return hybrid_search_chunks(connection, query, embedder().embed_query(query), limit=limit)

    return retrieve


def run_on_database(
    engine: Engine,
    llm: ChatModel,
    question: str,
    *,
    history: Sequence[Turn] = (),
    user_id: str | None = None,
    conversation_id: str | None = None,
    on_event: OnEvent | None = None,
    mentions: Sequence[Mentioned] = (),
    limit: int = RETRIEVAL_LIMIT,
) -> tuple[AgentState, str | None]:
    """One traced agent run with retrieval and card lookups over one connection, held for
    the length of the run; returns the final state and the trace id (None untraced)."""
    with engine.connect() as connection:
        return traced_run(
            llm,
            hybrid_retriever(connection, limit),
            question,
            history,
            user_id=user_id,
            conversation_id=conversation_id,
            tools=[card_lookup_tool(connection)],
            on_event=on_event,
            mentions=mentions,
        )


def database_coach(engine: Engine, llm: ChatModel) -> Coach:
    """The production coach: each question gets its own connection for retrieval and
    card lookups, held for the length of the run."""

    def coach(question: Question, on_event: OnEvent) -> Reply:
        state, _ = run_on_database(
            engine,
            llm,
            question.text,
            history=question.history,
            user_id=str(question.user_id),
            conversation_id=str(question.conversation_id),
            on_event=on_event,
            mentions=question.mentions,
        )
        return Reply(state["answer"], state["outcome"], evidence(state))

    return coach
