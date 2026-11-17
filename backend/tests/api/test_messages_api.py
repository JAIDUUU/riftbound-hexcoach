import json
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.agent.coach import Reply
from backend.agent.graph import AgentEvent, Started, Step, Token, Turn
from backend.api.app import create_app
from backend.conversations.limits import Limits
from backend.conversations.store import ConversationStore
from backend.llm.providers import AllProvidersFailedError
from backend.quota.admission import MessageQuota, QuotaSettings
from backend.retrieval.repository import SearchHit
from tests.api.coaches import FakeCoach
from tests.api.tokens import fake_verifier, mint
from tests.conversations.memory_store import InMemoryConversationStore
from tests.decks.memory_store import no_decks
from tests.quota.fake_clock import FakeClock
from tests.quota.memory_usage import memory_quota

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


def _client(
    store: InMemoryConversationStore, coach: FakeCoach, quota: MessageQuota | None = None
) -> TestClient:
    @contextmanager
    def open_store() -> Generator[ConversationStore]:
        yield store

    return TestClient(
        create_app(fake_verifier(), open_store, open_decks=no_decks, coach=coach, quota=quota)
    )


def _as(user: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint(user)}"}


def _post(
    store: InMemoryConversationStore,
    coach: FakeCoach,
    conversation_id: uuid.UUID,
    body: dict[str, Any],
    headers: dict[str, str],
    quota: MessageQuota | None = None,
):
    return _client(store, coach, quota).post(
        f"/conversations/{conversation_id}/messages", json=body, headers=headers
    )


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
    response = _post(store, coach, conversation_id, {"content": content}, _as(user))
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


def test_final_cites_only_the_evidence_the_answer_names(
    store: InMemoryConversationStore,
) -> None:
    uncited = replace(RULE_472, chunk_id=2, rule_id="315.2.b.2", text="Unrelated.")
    coach = FakeCoach(A_FULL_RUN, Reply(ANSWER, "answered", (uncited, RULE_472)))

    final = _ask(store, coach)[-1].data

    assert final["citations"] == [
        {
            "source_type": "rules",
            "rule_id": "472",
            "title": None,
            "section": "Scoring",
            "source_date": "2026-10-09",
            "source_url": None,
            "text": "A player may only Score once per Battlefield per turn.",
        }
    ]


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


def test_someone_elses_conversation_is_a_plain_404_and_nothing_runs(
    store: InMemoryConversationStore,
) -> None:
    conversation = store.create(ALICE, None)
    coach = FakeCoach([Started(None)], Reply("a", "answered", ()))

    response = _post(store, coach, conversation.id, {"content": "hi"}, _as(BOB))

    assert response.status_code == 404
    assert coach.questions == []
    detail = store.get(ALICE, conversation.id)
    assert detail is not None
    assert detail.messages == ()


def test_a_message_over_the_cap_is_a_plain_422_before_any_stream_opens() -> None:
    store = InMemoryConversationStore(Limits(max_message_chars=10))
    conversation = store.create(ALICE, None)
    coach = FakeCoach([Started(None)], Reply("a", "answered", ()))

    response = _post(store, coach, conversation.id, {"content": "x" * 11}, _as(ALICE))

    assert response.status_code == 422
    assert response.json() == {"detail": "Message is 11 characters; the limit is 10."}
    assert coach.questions == []


def test_an_empty_message_is_refused(store: InMemoryConversationStore) -> None:
    conversation = store.create(ALICE, None)
    coach = FakeCoach([Started(None)], Reply("a", "answered", ()))

    response = _post(store, coach, conversation.id, {"content": ""}, _as(ALICE))

    assert response.status_code == 422
    assert coach.questions == []


def test_sending_a_message_needs_a_token(store: InMemoryConversationStore) -> None:
    conversation = store.create(ALICE, None)
    coach = FakeCoach([Started(None)], Reply("a", "answered", ()))

    response = _post(store, coach, conversation.id, {"content": "hi"}, {})

    assert response.status_code == 401
    assert coach.questions == []


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


EVENING = datetime(2026, 11, 17, 22, 30, tzinfo=UTC)  # 90 minutes before the UTC day ends


def _quota(per_minute: int = 100, per_day: int = 100) -> MessageQuota:
    settings = QuotaSettings(messages_per_minute=per_minute, messages_per_day=per_day)
    return memory_quota(settings, FakeClock(EVENING))


def _send(
    store: InMemoryConversationStore,
    coach: FakeCoach,
    quota: MessageQuota,
    conversation_id: uuid.UUID,
    content: str = "Can I score twice?",
):
    return _post(store, coach, conversation_id, {"content": content}, _as(ALICE), quota)


def test_a_used_up_daily_quota_is_a_typed_429_before_any_stream_opens(
    store: InMemoryConversationStore,
) -> None:
    conversation = store.create(ALICE, None)
    coach = FakeCoach([Started(None)], Reply("a", "answered", ()))
    quota = _quota(per_day=1)
    assert _send(store, coach, quota, conversation.id, "first").status_code == 200

    response = _send(store, coach, quota, conversation.id, "second")

    assert response.status_code == 429
    assert response.headers["retry-after"] == str(90 * 60)
    body = response.json()
    assert (body["code"], body["retry_after"]) == ("daily_quota_reached", 90 * 60)
    assert "00:00 UTC" in body["detail"]
    assert [q.text for q in coach.questions] == ["first"]
    detail = store.get(ALICE, conversation.id)
    assert detail is not None
    assert [m.content for m in detail.messages if m.role == "user"] == ["first"]


def test_a_burst_of_messages_is_throttled_with_a_typed_429(
    store: InMemoryConversationStore,
) -> None:
    conversation = store.create(ALICE, None)
    coach = FakeCoach([Started(None)], Reply("a", "answered", ()))
    quota = _quota(per_minute=1)
    _send(store, coach, quota, conversation.id)

    response = _send(store, coach, quota, conversation.id)

    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert response.json()["code"] == "rate_limited"
    assert len(coach.questions) == 1


def test_a_message_refused_for_its_length_still_counts_against_the_quota() -> None:
    store = InMemoryConversationStore(Limits(max_message_chars=10))
    conversation = store.create(ALICE, None)
    coach = FakeCoach([Started(None)], Reply("a", "answered", ()))
    quota = _quota(per_day=1)
    assert _send(store, coach, quota, conversation.id, "x" * 11).status_code == 422

    assert _send(store, coach, quota, conversation.id, "short").status_code == 429


def test_a_run_that_fails_still_counts_against_the_quota(
    store: InMemoryConversationStore,
) -> None:
    conversation = store.create(ALICE, None)
    exhausted = AllProvidersFailedError([("gemini", RuntimeError("429"))])
    quota = _quota(per_day=1)
    _send(store, FakeCoach([Started(None)], error=exhausted), quota, conversation.id)

    retry = _send(
        store, FakeCoach([Started(None)], Reply("a", "answered", ())), quota, conversation.id
    )

    assert retry.status_code == 429
