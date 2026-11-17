"""One chat turn, streamed as server-sent events (issue #12, ADR 0005).

The player's message is already stored and checked by the time a turn runs (see
`begin_turn` in app.py), so everything here happens inside an open 200 stream. Events:
`start` (the answer's message id and the trace id), `status` (a graph step began),
`token` (a piece of the answer), then exactly one of `final` (the full text, citations
and validated cards) or `error` (a typed, user-presentable reason). `start` is always
first, even when the run fails before the trace exists.

The answer is stored before `final` is sent, by the worker thread rather than the
response, so a player who closes the tab still finds the answer on their next visit.
"""

import logging
import queue
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date
from typing import Literal

from fastapi.sse import ServerSentEvent
from pydantic import BaseModel

from backend.agent.citations import cited_evidence
from backend.agent.coach import Coach, Question, Reply
from backend.agent.graph import AgentEvent, Outcome, Started, Step, StepName, Token
from backend.conversations.store import ConversationStore
from backend.llm.providers import AllProvidersFailedError
from backend.retrieval.repository import SearchHit, SourceType

_log = logging.getLogger(__name__)

OpenStore = Callable[[], AbstractContextManager[ConversationStore]]
"""Opens a store for one unit of work; leaving the context commits (or rolls back on error)."""

Emit = Callable[[ServerSentEvent], None]


class StartData(BaseModel):
    message_id: uuid.UUID
    trace_id: str | None


class StatusData(BaseModel):
    step: StepName


class TokenData(BaseModel):
    text: str


class CitationOut(BaseModel):
    source_type: SourceType
    rule_id: str | None
    title: str | None
    section: str | None
    source_date: date
    source_url: str | None
    text: str

    @classmethod
    def of(cls, hit: SearchHit) -> "CitationOut":
        return cls(
            source_type=hit.source_type,
            rule_id=hit.rule_id,
            title=hit.title,
            section=hit.section,
            source_date=hit.source_date,
            source_url=hit.source_url,
            text=hit.text,
        )


class CardOut(BaseModel):
    """A Card tag in the answer that matched a real Card. Issue #15 settles the fields."""

    oracle_id: str
    name: str


class FinalData(BaseModel):
    text: str
    outcome: Outcome
    citations: list[CitationOut]
    cards: list[CardOut]


ErrorCode = Literal["providers_unavailable", "conversation_deleted", "internal"]

_ERROR_MESSAGES: dict[ErrorCode, str] = {
    "providers_unavailable": (
        "The coach can't reach any of its AI providers right now. Please try again in a few"
        " minutes."
    ),
    "conversation_deleted": "This conversation was deleted before the answer was ready.",
    "internal": "Something went wrong while answering. Please try again.",
}


class ErrorData(BaseModel):
    code: ErrorCode
    message: str


@dataclass(frozen=True, slots=True)
class PreparedTurn:
    question: Question
    answer_id: uuid.UUID  # the assistant message's id, announced in `start`


def citations(reply: Reply) -> list[CitationOut]:
    return [CitationOut.of(hit) for hit in cited_evidence(reply.answer, reply.evidence)]


def validated_cards(answer: str) -> list[CardOut]:
    """The answer's Card tags that match a real Card; none until issue #15 adds checking."""
    return []


def run_turn(turn: PreparedTurn, coach: Coach, open_store: OpenStore, emit: Emit) -> None:
    """Run the coach, store the answer and emit the turn's events; a failure becomes an
    `error` event, since the stream is already a 200."""
    trace_id: str | None = None
    started = False

    def start(trace: str | None) -> None:
        nonlocal trace_id, started
        trace_id, started = trace, True
        emit(
            ServerSentEvent(
                event="start", data=StartData(message_id=turn.answer_id, trace_id=trace)
            )
        )

    def on_event(event: AgentEvent) -> None:
        match event:
            case Started(trace_id=trace):
                start(trace)
            case Step(name=name):
                emit(ServerSentEvent(event="status", data=StatusData(step=name)))
            case Token(text=text):
                emit(ServerSentEvent(event="token", data=TokenData(text=text)))

    def fail(code: ErrorCode) -> None:
        if not started:
            start(None)
        emit(
            ServerSentEvent(event="error", data=ErrorData(code=code, message=_ERROR_MESSAGES[code]))
        )

    question = turn.question
    try:
        reply = coach(question, on_event)
        with open_store() as store:
            saved = store.add_message(
                question.user_id,
                question.conversation_id,
                "assistant",
                reply.answer,
                trace_id,
                message_id=turn.answer_id,
            )
    except AllProvidersFailedError as error:
        _log.warning("Every chat provider failed: %s", error)
        fail("providers_unavailable")
        return
    except Exception:
        _log.exception("A chat turn failed")
        fail("internal")
        return
    if saved is None:
        fail("conversation_deleted")
        return
    final = FinalData(
        text=reply.answer,
        outcome=reply.outcome,
        citations=citations(reply),
        cards=validated_cards(reply.answer),
    )
    emit(ServerSentEvent(event="final", data=final))


def stream_turn(
    turn: PreparedTurn, coach: Coach, open_store: OpenStore
) -> Iterator[ServerSentEvent]:
    """The turn's events as a generator for FastAPI's SSE response.

    The run reports through a callback and must stay in one context (Langfuse keeps the
    open trace in a context variable), while FastAPI pulls each item of a sync generator
    on a pool thread in a fresh copy of the context; a worker thread and a queue bridge
    the two.
    """
    events: queue.Queue[ServerSentEvent | None] = queue.Queue()

    def work() -> None:
        try:
            run_turn(turn, coach, open_store, events.put)
        finally:
            events.put(None)

    threading.Thread(target=work, name=f"turn-{turn.answer_id}", daemon=True).start()
    while (event := events.get()) is not None:
        yield event
