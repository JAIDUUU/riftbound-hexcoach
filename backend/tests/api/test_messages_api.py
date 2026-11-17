import json
import uuid
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.agent.coach import Question, Reply
from backend.agent.graph import AgentEvent, OnEvent, Started, Step, Token, Turn
from backend.api.app import create_app
from backend.conversations.limits import Limits
from backend.conversations.store import ConversationStore
from backend.llm.providers import AllProvidersFailedError
from backend.retrieval.repository import SearchHit
from tests.api.tokens import fake_verifier, mint
from tests.conversations.memory_store import InMemoryConversationStore

ALICE = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")
BOB = uuid.UUID("bbbbbbbb-0000-4000-8000-000000000002")

RULE_472 = SearchHit(
    chunk_id=1,
    source_type="rules",
    rule_id="472",
    section="Scoring",
    text="A player may only Score once per Battlefield per turn.",
    source_version="2026-10-09",
    source_date=date(2026, 10, 9),
    title=None,
    source_url=None,
)


class FakeCoach:
    """Stands in for the agent graph: replays scripted events, then replies or fails.

    `during` runs mid-answer, for things that happen while the model is still writing.
    """

    def __init__(
        self,
        events: Sequence[AgentEvent] = (),
        reply: Reply | None = None,
        error: Exception | None = None,
        during: Callable[[], object] | None = None,
    ) -> None:
        self.events = list(events)
        self.reply = reply
        self.error = error
        self.during = during
        self.questions: list[Question] = []

    def __call__(self, question: Question, on_event: OnEvent) -> Reply:
        self.questions.append(question)
        for event in self.events:
            on_event(event)
        if self.during is not None:
            self.during()
        if self.error is not None:
            raise self.error
        assert self.reply is not None, "a FakeCoach needs a reply or an error"
        return self.reply


ANSWER = "No - only once per battlefield per turn (rule 472)."
A_FULL_RUN: list[AgentEvent] = [
    Started(trace_id="trace-7"),
    Step("prepare"),
    Step("retrieve"),
    Step("grade"),
    Step("answer"),
    Token("No - only once "),
    Token("per battlefield per turn (rule 472)."),
]


@dataclass(frozen=True)
class Event:
    event: str
    data: dict[str, Any]


def parse_sse(body: str) -> list[Event]:
    """Server-sent events from a response body, skipping keepalive comments."""
    events: list[Event] = []
    for block in body.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ":" in line)
        if "event" in fields:
            events.append(Event(fields["event"], json.loads(fields["data"])))
    return events


@pytest.fixture
def store() -> InMemoryConversationStore:
    return InMemoryConversationStore(Limits())


def _client(store: InMemoryConversationStore, coach: FakeCoach) -> TestClient:
    @contextmanager
    def open_store() -> Generator[ConversationStore]:
        yield store

    return TestClient(create_app(fake_verifier(), open_store, coach))


def _as(user: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint(user)}"}


def _ask(
    store: InMemoryConversationStore,
    coach: FakeCoach,
    content: str = "Can I score the same battlefield twice?",
    *,
    conversation_id: uuid.UUID | None = None,
    user: uuid.UUID = ALICE,
) -> list[Event]:
    if conversation_id is None:
        conversation_id = store.create(ALICE, None).id
    response = _client(store, coach).post(
        f"/conversations/{conversation_id}/messages", json={"content": content}, headers=_as(user)
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


def test_a_successful_run_streams_start_status_token_and_final_in_order(
    store: InMemoryConversationStore,
) -> None:
    coach = FakeCoach(A_FULL_RUN, Reply(ANSWER, "answered", (RULE_472,)))

    events = _ask(store, coach)

    assert [e.event for e in events] == [
        "start",
        "status",
        "status",
        "status",
        "status",
        "token",
        "token",
        "final",
    ]
    start, final = events[0].data, events[-1].data
    assert start["trace_id"] == "trace-7"
    uuid.UUID(start["message_id"])  # a real id, announced before the answer exists
    assert [e.data for e in events if e.event == "status"] == [
        {"step": "prepare"},
        {"step": "retrieve"},
        {"step": "grade"},
        {"step": "answer"},
    ]
    assert [e.data for e in events if e.event == "token"] == [
        {"text": "No - only once "},
        {"text": "per battlefield per turn (rule 472)."},
    ]
    assert final["text"] == ANSWER
    assert final["outcome"] == "answered"
    assert final["cards"] == []
    assert [c["rule_id"] for c in final["citations"]] == ["472"]


def test_both_messages_are_stored_and_the_answer_keeps_its_announced_id_and_trace(
    store: InMemoryConversationStore,
) -> None:
    conversation = store.create(ALICE, None)
    coach = FakeCoach(A_FULL_RUN, Reply(ANSWER, "answered", (RULE_472,)))

    events = _ask(store, coach, "Can I score twice?", conversation_id=conversation.id)

    detail = store.get(ALICE, conversation.id)
    assert detail is not None
    assert [(m.role, m.content, m.trace_id) for m in detail.messages] == [
        ("user", "Can I score twice?", None),
        ("assistant", ANSWER, "trace-7"),
    ]
    assert str(detail.messages[1].id) == events[0].data["message_id"]


def test_the_coach_gets_the_question_and_the_capped_history_before_it() -> None:
    store = InMemoryConversationStore(Limits(max_history_messages=2))
    conversation = store.create(ALICE, None)
    earlier: list[Turn] = [("user", "q1"), ("assistant", "a1"), ("user", "q2")]
    for role, content in earlier:
        store.add_message(ALICE, conversation.id, role, content)
    coach = FakeCoach([Started(None)], Reply("a2", "answered", ()))

    _ask(store, coach, "q3", conversation_id=conversation.id)

    [question] = coach.questions
    assert question.text == "q3"
    assert question.history == (("assistant", "a1"), ("user", "q2"))
    assert question.user_id == ALICE
    assert question.conversation_id == conversation.id


def test_provider_exhaustion_ends_the_stream_with_a_typed_error_event(
    store: InMemoryConversationStore,
) -> None:
    conversation = store.create(ALICE, None)
    exhausted = AllProvidersFailedError([("gemini", RuntimeError("429")), ("groq", TimeoutError())])
    coach = FakeCoach([Started("trace-8"), Step("prepare")], error=exhausted)

    events = _ask(store, coach, "Can I?", conversation_id=conversation.id)

    assert [e.event for e in events] == ["start", "status", "error"]
    assert events[-1].data["code"] == "providers_unavailable"
    assert "try again" in events[-1].data["message"]
    detail = store.get(ALICE, conversation.id)
    assert detail is not None
    assert [m.role for m in detail.messages] == ["user"]  # no half answer is stored


def test_an_unexpected_failure_is_an_error_event_that_leaks_no_internals(
    store: InMemoryConversationStore,
) -> None:
    coach = FakeCoach([Started("trace-9")], error=KeyError("DATABASE_URL=postgres://secret"))

    events = _ask(store, coach)

    assert [e.event for e in events] == ["start", "error"]
    assert events[-1].data["code"] == "internal"
    assert "secret" not in json.dumps(events[-1].data)


def test_a_failure_before_the_trace_exists_still_starts_with_start(
    store: InMemoryConversationStore,
) -> None:
    coach = FakeCoach(error=RuntimeError("langfuse unreachable"))

    events = _ask(store, coach)

    assert [e.event for e in events] == ["start", "error"]
    assert events[0].data["trace_id"] is None
    uuid.UUID(events[0].data["message_id"])


def test_a_conversation_deleted_mid_answer_ends_with_an_error_not_a_final(
    store: InMemoryConversationStore,
) -> None:
    conversation = store.create(ALICE, None)
    coach = FakeCoach(
        A_FULL_RUN,
        Reply(ANSWER, "answered", ()),
        during=lambda: store.delete(ALICE, conversation.id),
    )

    events = _ask(store, coach, conversation_id=conversation.id)

    assert events[-1].event == "error"
    assert events[-1].data["code"] == "conversation_deleted"
