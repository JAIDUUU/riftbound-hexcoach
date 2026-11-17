"""The coach behind the message endpoint (issue #12): one question in, one reply out.

`Coach` is the seam the API depends on. Given the player's question, the conversation so
far and who is asking, it runs the agent fresh and reports progress through `on_event`
(the trace id first, then graph steps and answer tokens). API tests hand the app a
scripted fake; `database_coach` is the real one: hybrid retrieval and the lookup_card
tool over Postgres, traced in Langfuse when the keys are set.
"""

import uuid
from dataclasses import dataclass
from typing import Protocol

from langchain_core.tools import BaseTool
from sqlalchemy import Connection, Engine

from backend.agent.graph import ChatModel, Mentioned, OnEvent, Outcome, Turn
from backend.agent.tracing import traced_run
from backend.retrieval.repository import SearchHit

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
    evidence: tuple[SearchHit, ...]  # the chunks the answer was written from


class Coach(Protocol):
    def __call__(self, question: Question, on_event: OnEvent) -> Reply: ...


def card_lookup_tool(connection: Connection) -> BaseTool:
    """The lookup_card tool backed by the cards table (issue #10)."""
    from backend.agent.tools import make_lookup_card
    from backend.cards.chunk_text import card_text_chunk
    from backend.cards.repository import all_card_names, find_by_oracle_name

    def find_card(name: str) -> str | None:
        card = find_by_oracle_name(connection, name)
        return card_text_chunk(card) if card else None

    return make_lookup_card(find_card, lambda: all_card_names(connection))


def database_coach(engine: Engine, llm: ChatModel) -> Coach:
    """The production coach: each question gets its own connection for retrieval and
    card lookups, held for the length of the run."""
    from backend.retrieval.embedding import embedder
    from backend.retrieval.repository import hybrid_search_chunks

    def coach(question: Question, on_event: OnEvent) -> Reply:
        with engine.connect() as connection:

            def retrieve(query: str) -> list[SearchHit]:
                return hybrid_search_chunks(
                    connection, query, embedder().embed_query(query), limit=RETRIEVAL_LIMIT
                )

            state, _ = traced_run(
                llm,
                retrieve,
                question.text,
                question.history,
                user_id=str(question.user_id),
                conversation_id=str(question.conversation_id),
                tools=[card_lookup_tool(connection)],
                on_event=on_event,
                mentions=question.mentions,
            )
        return Reply(state["answer"], state["outcome"], tuple(state["hits"]))

    return coach
