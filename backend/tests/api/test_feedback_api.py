"""Feedback (issue #19): a thumbs up/down on an answer, stored and sent to Langfuse."""

import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import pytest
from fastapi.testclient import TestClient

from backend.cards.collapse import Card
from backend.conversations.limits import Limits
from backend.conversations.store import ConversationStore
from tests.api.app_factory import make_app, opening_cards
from tests.api.tokens import mint
from tests.cards.memory_catalog import InMemoryCardCatalog
from tests.conversations.memory_store import InMemoryConversationStore

ALICE = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")
BOB = uuid.UUID("bbbbbbbb-0000-4000-8000-000000000002")


class FakeLangfuse:
    """Records create_score calls the way the Langfuse client receives them."""

    def __init__(self) -> None:
        self.scores: list[dict[str, object]] = []

    def create_score(
        self,
        *,
        name: str,
        value: float,
        trace_id: str | None = None,
        score_id: str | None = None,
        data_type: Literal["BOOLEAN"] | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        self.scores.append(
            {
                "name": name,
                "value": value,
                "trace_id": trace_id,
                "score_id": score_id,
                "data_type": data_type,
                "timestamp": timestamp,
            }
        )


@pytest.fixture
def store() -> InMemoryConversationStore:
    return InMemoryConversationStore(Limits())


@pytest.fixture
def langfuse() -> FakeLangfuse:
    return FakeLangfuse()


@pytest.fixture
def client(store: InMemoryConversationStore, langfuse: FakeLangfuse) -> TestClient:
    return TestClient(make_app(store=store, scores=langfuse))


def _as(user: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint(user)}"}


@dataclass(frozen=True)
class Answer:
    conversation_id: uuid.UUID
    message_id: uuid.UUID


def _answered(store: InMemoryConversationStore, trace_id: str | None = "trace-1") -> Answer:
    """A new conversation of Alice's holding a question and its answer."""
    conversation = store.create(ALICE, None)
    store.add_message(ALICE, conversation.id, "user", "Can I score twice?")
    answer = store.add_message(ALICE, conversation.id, "assistant", "No (rule 472).", trace_id)
    assert answer is not None
    return Answer(conversation.id, answer.id)


def _vote(
    client: TestClient,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    rating: str,
    user: uuid.UUID = ALICE,
):  # starlette's TestClient response type (httpx2) isn't a dependency of ours
    url = f"/conversations/{conversation_id}/messages/{message_id}/feedback"
    return client.put(url, json={"rating": rating}, headers=_as(user))


def _feedback_shown(client: TestClient, conversation_id: uuid.UUID) -> list[str | None]:
    """The feedback each message carries when Alice reloads the conversation."""
    detail = client.get(f"/conversations/{conversation_id}", headers=_as(ALICE)).json()
    return [message["feedback"] for message in detail["messages"]]


def test_a_thumbs_up_is_scored_on_the_answers_trace_and_shown_on_reload(
    client: TestClient, store: InMemoryConversationStore, langfuse: FakeLangfuse
) -> None:
    answer = _answered(store)

    response = _vote(client, answer.conversation_id, answer.message_id, "up")

    assert response.status_code == 200
    assert response.json()["feedback"] == "up"
    [score] = langfuse.scores
    assert score["trace_id"] == "trace-1"
    assert (score["name"], score["value"], score["data_type"]) == ("feedback", 1.0, "BOOLEAN")
    assert _feedback_shown(client, answer.conversation_id) == [None, "up"]


def test_the_rated_answer_comes_back_with_its_cards_as_on_reload(
    store: InMemoryConversationStore, cards_by_name: dict[str, Card]
) -> None:
    catalog = InMemoryCardCatalog(cards_by_name.values())
    client = TestClient(make_app(store=store, open_cards=opening_cards(catalog)))
    conversation = store.create(ALICE, None)
    answer = store.add_message(
        ALICE, conversation.id, "assistant", "[[Pouty Poro]] has Deflect.", "trace-1"
    )
    assert answer is not None

    response = _vote(client, conversation.id, answer.id, "up")

    assert [card["oracle_name"] for card in response.json()["cards"]] == ["Pouty Poro"]


def test_changing_the_vote_replaces_the_langfuse_score_instead_of_adding_one(
    client: TestClient, store: InMemoryConversationStore, langfuse: FakeLangfuse
) -> None:
    answer = _answered(store)

    _vote(client, answer.conversation_id, answer.message_id, "up")
    response = _vote(client, answer.conversation_id, answer.message_id, "down")

    assert response.json()["feedback"] == "down"
    first, second = langfuse.scores
    assert second["value"] == 0.0
    # Langfuse overwrites a score only when id, name and timestamp date all match.
    assert second["score_id"] is not None
    assert (second["score_id"], second["name"]) == (first["score_id"], first["name"])
    assert second["timestamp"] is not None
    assert second["timestamp"] == first["timestamp"]


def test_without_langfuse_the_vote_is_still_stored(store: InMemoryConversationStore) -> None:
    client = TestClient(make_app(store=store, scores=None))
    answer = _answered(store, trace_id=None)  # without Langfuse keys no answer has a trace

    response = _vote(client, answer.conversation_id, answer.message_id, "down")

    assert response.status_code == 200
    assert _feedback_shown(client, answer.conversation_id) == [None, "down"]


def test_a_vote_that_fails_to_commit_is_never_scored(
    store: InMemoryConversationStore, langfuse: FakeLangfuse
) -> None:
    @contextmanager
    def failing_commit() -> Generator[ConversationStore]:
        yield store
        raise RuntimeError("commit failed")

    client = TestClient(
        make_app(open_store=failing_commit, scores=langfuse), raise_server_exceptions=False
    )
    answer = _answered(store)

    response = _vote(client, answer.conversation_id, answer.message_id, "up")

    assert response.status_code == 500
    assert langfuse.scores == []


def test_feedback_needs_a_token_and_a_thumbs_up_or_down(
    client: TestClient, store: InMemoryConversationStore, langfuse: FakeLangfuse
) -> None:
    answer = _answered(store)
    url = f"/conversations/{answer.conversation_id}/messages/{answer.message_id}/feedback"

    assert client.put(url, json={"rating": "up"}).status_code == 401
    assert _vote(client, answer.conversation_id, answer.message_id, "meh").status_code == 422
    assert langfuse.scores == []


def test_each_answer_gets_its_own_score(
    client: TestClient, store: InMemoryConversationStore, langfuse: FakeLangfuse
) -> None:
    for answer in (_answered(store), _answered(store)):
        _vote(client, answer.conversation_id, answer.message_id, "up")

    first, second = langfuse.scores
    assert first["score_id"] != second["score_id"]


def test_only_the_owner_can_give_feedback_and_others_get_a_plain_404(
    client: TestClient, store: InMemoryConversationStore, langfuse: FakeLangfuse
) -> None:
    answer = _answered(store)

    response = _vote(client, answer.conversation_id, answer.message_id, "down", user=BOB)

    assert response.status_code == 404
    assert langfuse.scores == []
    assert _feedback_shown(client, answer.conversation_id) == [None, None]


def test_a_message_from_another_conversation_or_a_made_up_one_is_not_found(
    client: TestClient, store: InMemoryConversationStore, langfuse: FakeLangfuse
) -> None:
    answer = _answered(store)
    other_conversation = store.create(ALICE, None).id

    assert _vote(client, other_conversation, answer.message_id, "up").status_code == 404
    assert _vote(client, other_conversation, uuid.uuid4(), "up").status_code == 404
    assert langfuse.scores == []


def test_only_answers_can_receive_feedback(
    client: TestClient, store: InMemoryConversationStore, langfuse: FakeLangfuse
) -> None:
    answer = _answered(store)
    detail = store.get(ALICE, answer.conversation_id)
    assert detail is not None
    question = detail.messages[0]

    response = _vote(client, answer.conversation_id, question.id, "up")

    assert response.status_code == 409
    assert response.json() == {"detail": "Only answers can receive feedback."}
    assert langfuse.scores == []
    assert _feedback_shown(client, answer.conversation_id) == [None, None]


def test_an_answer_without_a_trace_is_rated_but_not_scored(
    client: TestClient, store: InMemoryConversationStore, langfuse: FakeLangfuse
) -> None:
    untraced = _answered(store, trace_id=None)

    response = _vote(client, untraced.conversation_id, untraced.message_id, "up")

    assert response.status_code == 200
    assert langfuse.scores == []
    assert _feedback_shown(client, untraced.conversation_id) == [None, "up"]


class UnreachableLangfuse(FakeLangfuse):
    def create_score(self, **score: Any) -> None:
        raise ConnectionError("Langfuse is unreachable")


def test_a_score_that_fails_to_send_is_logged_with_what_it_takes_to_resend_it(
    store: InMemoryConversationStore, caplog: pytest.LogCaptureFixture
) -> None:
    client = TestClient(make_app(store=store, scores=UnreachableLangfuse()))
    answer = _answered(store)

    response = _vote(client, answer.conversation_id, answer.message_id, "down")

    assert response.status_code == 200
    assert _feedback_shown(client, answer.conversation_id) == [None, "down"]
    detail = store.get(ALICE, answer.conversation_id)
    assert detail is not None and detail.messages[1].feedback is not None
    given_at = detail.messages[1].feedback.given_at
    for needed in (str(answer.message_id), "trace-1", "down", given_at.isoformat()):
        assert needed in caplog.text
