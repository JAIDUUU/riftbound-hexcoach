"""Feedback (issue #19): a thumbs up/down on an answer, stored and sent to Langfuse."""

import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.turn import OpenStore
from backend.conversations.limits import Limits
from backend.conversations.store import ConversationStore
from tests.api.accounts import unused_account_deletion
from tests.api.coaches import unused_coach
from tests.api.tokens import fake_verifier, mint
from tests.conversations.memory_store import InMemoryConversationStore
from tests.decks.memory_store import no_decks

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


def _opener(store: InMemoryConversationStore) -> OpenStore:
    @contextmanager
    def open_store() -> Generator[ConversationStore]:
        yield store

    return open_store


@pytest.fixture
def client(store: InMemoryConversationStore, langfuse: FakeLangfuse) -> TestClient:
    return TestClient(
        create_app(
            fake_verifier(),
            _opener(store),
            open_decks=no_decks,
            coach=unused_coach,
            delete_account=unused_account_deletion,
            scores=langfuse,
        )
    )


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
    client = TestClient(
        create_app(
            fake_verifier(),
            _opener(store),
            open_decks=no_decks,
            coach=unused_coach,
            delete_account=unused_account_deletion,
            scores=None,
        )
    )
    answer = _answered(store)

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
        create_app(
            fake_verifier(),
            failing_commit,
            open_decks=no_decks,
            coach=unused_coach,
            delete_account=unused_account_deletion,
            scores=langfuse,
        ),
        raise_server_exceptions=False,
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


def test_only_answers_with_a_trace_can_receive_feedback(
    client: TestClient, store: InMemoryConversationStore, langfuse: FakeLangfuse
) -> None:
    untraced = _answered(store, trace_id=None)
    detail = store.get(ALICE, untraced.conversation_id)
    assert detail is not None
    question = detail.messages[0]

    on_question = _vote(client, untraced.conversation_id, question.id, "up")
    on_untraced_answer = _vote(client, untraced.conversation_id, untraced.message_id, "up")

    assert on_question.status_code == 409
    assert on_untraced_answer.status_code == 409
    assert on_untraced_answer.json() == {
        "detail": "Only answers with a trace can receive feedback."
    }
    assert langfuse.scores == []
    assert _feedback_shown(client, untraced.conversation_id) == [None, None]
