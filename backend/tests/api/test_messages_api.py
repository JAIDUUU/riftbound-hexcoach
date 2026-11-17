import json
import uuid
from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.agent.coach import Reply
from backend.agent.graph import (
    AgentEvent,
    MentionedCard,
    MentionedDeck,
    Started,
    Step,
    Token,
    Turn,
)
from backend.api.app import DeckAccess, OpenDecks, create_app
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
from tests.decks.memory_store import InMemoryDeckStore, no_decks

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
    store: InMemoryConversationStore,
    coach: FakeCoach,
    open_decks: OpenDecks = no_decks,
    limits: Limits | None = None,
) -> TestClient:
    @contextmanager
    def open_store() -> Generator[ConversationStore]:
        yield store

    return TestClient(
        create_app(
            fake_verifier(),
            open_store,
            open_decks=open_decks,
            coach=coach,
            delete_account=unused_account_deletion,
            limits=limits,
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
):
    return _client(store, coach).post(
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


SONA_ID = "f30de1e6-73f9-4b64-9211-791d0fc422e7"  # its `id` in data/cards/card-index.json
SONA_DECK = "Champion:\n1 Sona, Harmonious\nMainDeck:\n3 Blazing Scorcher\n"


@dataclass
class Library:
    """The decks and cards a test's messages can mention."""

    decks: InMemoryDeckStore
    cards: InMemoryCardCatalog

    def open(self) -> AbstractContextManager[DeckAccess]:
        return nullcontext(DeckAccess(self.decks, self.cards))


@pytest.fixture
def library(cards_by_name: dict[str, Card]) -> Library:
    return Library(InMemoryDeckStore(), InMemoryCardCatalog(cards_by_name.values()))


def _mention(
    store: InMemoryConversationStore,
    coach: FakeCoach,
    library: Library,
    mentions: list[dict[str, str]],
    *,
    user: uuid.UUID = ALICE,
    conversation_id: uuid.UUID | None = None,
    limits: Limits | None = None,
):
    if conversation_id is None:
        conversation_id = store.create(ALICE, None).id
    return _client(store, coach, library.open, limits).post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "Does she ready runes?", "mentions": mentions},
        headers=_as(user),
    )


def test_mentioned_cards_and_decks_reach_the_coach_resolved(
    store: InMemoryConversationStore, library: Library
) -> None:
    deck = library.decks.create(ALICE, "Sona ramp", SONA_DECK)
    coach = FakeCoach([Started(None)], Reply("Yes.", "answered", ()))

    response = _mention(
        store,
        coach,
        library,
        [{"kind": "card", "id": SONA_ID}, {"kind": "deck", "id": str(deck.id)}],
    )

    assert response.status_code == 200, response.text
    [question] = coach.questions
    card, mentioned_deck = question.mentions
    assert isinstance(card, MentionedCard) and card.name == "Sona, Harmonious"
    assert "ready up to 4 friendly runes" in card.text
    assert mentioned_deck == MentionedDeck(
        name="Sona ramp",
        sections=(("Champion", ("Sona, Harmonious",)), ("MainDeck", ("Blazing Scorcher",))),
    )


def test_a_message_without_mentions_resolves_none_and_needs_no_decks(
    store: InMemoryConversationStore,
) -> None:
    coach = FakeCoach([Started(None)], Reply("a", "answered", ()))

    _ask(store, coach)

    assert coach.questions[0].mentions == ()


@pytest.mark.parametrize("kind", ["card", "deck"])
def test_an_unknown_mention_is_a_plain_422_and_nothing_is_stored_or_run(
    store: InMemoryConversationStore, library: Library, kind: str
) -> None:
    conversation = store.create(ALICE, None)
    coach = FakeCoach([Started(None)], Reply("a", "answered", ()))
    unknown = str(uuid.uuid4())

    response = _mention(
        store, coach, library, [{"kind": kind, "id": unknown}], conversation_id=conversation.id
    )

    assert response.status_code == 422
    assert response.json() == {"detail": f"No {kind} with id {unknown}."}
    assert coach.questions == []
    detail = store.get(ALICE, conversation.id)
    assert detail is not None and detail.messages == ()


def test_someone_elses_deck_is_refused_like_a_missing_one(
    store: InMemoryConversationStore, library: Library
) -> None:
    bobs = library.decks.create(BOB, "Bob's deck", SONA_DECK)
    coach = FakeCoach([Started(None)], Reply("a", "answered", ()))

    response = _mention(store, coach, library, [{"kind": "deck", "id": str(bobs.id)}])

    assert response.status_code == 422
    assert response.json() == {"detail": f"No deck with id {bobs.id}."}
    assert coach.questions == []


def test_someone_elses_conversation_is_still_a_404_whatever_it_mentions(
    store: InMemoryConversationStore, library: Library
) -> None:
    conversation = store.create(ALICE, None)
    coach = FakeCoach([Started(None)], Reply("a", "answered", ()))

    response = _mention(
        store,
        coach,
        library,
        [{"kind": "card", "id": SONA_ID}],
        user=BOB,
        conversation_id=conversation.id,
    )

    assert response.status_code == 404


def test_more_mentions_than_the_cap_is_a_plain_422(
    store: InMemoryConversationStore, library: Library
) -> None:
    conversation = store.create(ALICE, None)
    coach = FakeCoach([Started(None)], Reply("a", "answered", ()))

    response = _mention(
        store,
        coach,
        library,
        [{"kind": "card", "id": SONA_ID}] * 3,
        conversation_id=conversation.id,
        limits=Limits(max_mentions=2),
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Message has 3 mentions; the limit is 2."}
    assert coach.questions == []
    detail = store.get(ALICE, conversation.id)
    assert detail is not None and detail.messages == ()


@pytest.mark.parametrize(
    "mention", [{"kind": "rule", "id": SONA_ID}, {"kind": "card", "id": "Sona, Harmonious"}]
)
def test_a_malformed_mention_is_refused(
    store: InMemoryConversationStore, library: Library, mention: dict[str, str]
) -> None:
    coach = FakeCoach([Started(None)], Reply("a", "answered", ()))

    response = _mention(store, coach, library, [mention])

    assert response.status_code == 422
    assert coach.questions == []


def test_a_turn_after_a_mentioning_one_sees_its_text_but_not_its_mentions(
    store: InMemoryConversationStore, library: Library
) -> None:
    conversation = store.create(ALICE, None)
    first = FakeCoach([Started(None)], Reply("Yes.", "answered", ()))
    _mention(
        store, first, library, [{"kind": "card", "id": SONA_ID}], conversation_id=conversation.id
    )
    second = FakeCoach([Started(None)], Reply("Still yes.", "answered", ()))

    events = _ask(store, second, "And on her first turn?", conversation_id=conversation.id)

    assert events[-1].event == "final"
    [question] = second.questions
    assert question.history == (("user", "Does she ready runes?"), ("assistant", "Yes."))
    assert question.mentions == ()
