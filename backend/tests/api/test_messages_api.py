import json
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.agent.coach import Reply
from backend.agent.graph import AgentEvent, Started, Step, Token, Turn
from backend.api.app import create_app
from backend.cards.catalog import CardCatalog
from backend.cards.collapse import Card
from backend.conversations.limits import Limits
from backend.conversations.store import ConversationStore
from backend.llm.providers import AllProvidersFailedError
from backend.retrieval.repository import SearchHit
from tests.api.accounts import unused_account_deletion
from tests.api.coaches import FakeCoach
from tests.api.tokens import fake_verifier, mint
from tests.cards.memory_catalog import InMemoryCardCatalog
from tests.conversations.memory_store import InMemoryConversationStore
from tests.decks.memory_store import no_decks

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
    store: InMemoryConversationStore, coach: FakeCoach, cards: CardCatalog | None = None
) -> TestClient:
    @contextmanager
    def open_store() -> Generator[ConversationStore]:
        yield store

    @contextmanager
    def open_cards() -> Generator[CardCatalog]:
        yield cards if cards is not None else InMemoryCardCatalog([])

    return TestClient(
        create_app(
            fake_verifier(),
            open_store,
            open_decks=no_decks,
            coach=coach,
            delete_account=unused_account_deletion,
            open_cards=open_cards,
        )
    )


def _as(user: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint(user)}"}


def _post(
    store: InMemoryConversationStore,
    coach: FakeCoach,
    conversation_id: uuid.UUID,
    body: dict[str, Any],
    headers: dict[str, str],
    cards: CardCatalog | None = None,
):
    return _client(store, coach, cards).post(
        f"/conversations/{conversation_id}/messages", json=body, headers=headers
    )


def _ask(
    store: InMemoryConversationStore,
    coach: FakeCoach,
    content: str = "Can I score the same battlefield twice?",
    *,
    conversation_id: uuid.UUID | None = None,
    user: uuid.UUID = ALICE,
    cards: CardCatalog | None = None,
) -> list[Event]:
    if conversation_id is None:
        conversation_id = store.create(ALICE, None).id
    response = _post(store, coach, conversation_id, {"content": content}, _as(user), cards)
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


def test_final_carries_each_tagged_card_for_its_preview_and_leaves_unknown_tags_out(
    store: InMemoryConversationStore, cards_by_name: dict[str, Card]
) -> None:
    answer = "No: [[Pouty Poro]] has Deflect, and [[Pouty Poros]] is not a card."
    coach = FakeCoach([Started(None)], Reply(answer, "answered", ()))

    final = _ask(store, coach, cards=InMemoryCardCatalog(cards_by_name.values()))[-1].data

    assert final["text"] == answer
    assert final["cards"] == [
        {
            "oracle_id": "df4c1239-7d32-465d-8811-c95ed6827185",
            "oracle_name": "Pouty Poro",
            "tags": ["Pouty Poro"],
            "image_url": "https://images.rifthunt.com/cards/normal/front/ogn/013/pouty-poro.webp",
            "cleaned_text": (
                "Deflect (Opponents must pay Rainbow Rune to choose me with a spell or ability.)"
            ),
        }
    ]


class _UnreachableCatalog:
    def find(self, name: str) -> Card | None:
        raise ConnectionError("cards table unreachable")

    def all_names(self) -> list[str]:
        raise ConnectionError("cards table unreachable")


def test_an_unreachable_card_catalog_still_ends_with_final_and_its_tags_as_plain_text(
    store: InMemoryConversationStore,
) -> None:
    answer = "No: [[Pouty Poro]] has Deflect."
    coach = FakeCoach([Started(None)], Reply(answer, "answered", ()))

    events = _ask(store, coach, cards=_UnreachableCatalog())

    assert events[-1].event == "final"
    assert events[-1].data["text"] == answer
    assert events[-1].data["cards"] == []


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
