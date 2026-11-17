"""Feedback (issue #19): a thumbs up/down on an answer, stored and sent to Langfuse."""

import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from typing import Literal

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.conversations.limits import Limits
from backend.conversations.store import ConversationStore
from tests.api.tokens import fake_verifier, mint
from tests.conversations.memory_store import InMemoryConversationStore

ALICE = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")


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
    @contextmanager
    def open_store() -> Generator[ConversationStore]:
        yield store

    return TestClient(create_app(fake_verifier(), open_store, scores=langfuse))


def _as(user: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint(user)}"}


def _answered(store: InMemoryConversationStore, trace_id: str | None = "trace-1") -> str:
    """Alice's conversation with one traced answer; returns that answer's feedback URL."""
    conversation = store.create(ALICE, None)
    store.add_message(ALICE, conversation.id, "user", "Can I score twice?")
    answer = store.add_message(ALICE, conversation.id, "assistant", "No (rule 472).", trace_id)
    assert answer is not None
    return f"/conversations/{conversation.id}/messages/{answer.id}/feedback"


def test_a_thumbs_up_is_scored_on_the_answers_trace_and_shown_on_reload(
    client: TestClient, store: InMemoryConversationStore, langfuse: FakeLangfuse
) -> None:
    url = _answered(store)

    response = client.put(url, json={"rating": "up"}, headers=_as(ALICE))

    assert response.status_code == 200
    assert response.json()["feedback"] == "up"
    [score] = langfuse.scores
    assert score["trace_id"] == "trace-1"
    assert (score["name"], score["value"], score["data_type"]) == ("feedback", 1.0, "BOOLEAN")
    conversation_url = url.split("/messages/")[0]
    messages = client.get(conversation_url, headers=_as(ALICE)).json()["messages"]
    assert [m["feedback"] for m in messages] == [None, "up"]


def test_changing_the_vote_replaces_the_langfuse_score_instead_of_adding_one(
    client: TestClient, store: InMemoryConversationStore, langfuse: FakeLangfuse
) -> None:
    url = _answered(store)

    client.put(url, json={"rating": "up"}, headers=_as(ALICE))
    response = client.put(url, json={"rating": "down"}, headers=_as(ALICE))

    assert response.json()["feedback"] == "down"
    first, second = langfuse.scores
    assert second["value"] == 0.0
    # Langfuse overwrites a score only when id, name and timestamp date all match.
    assert second["score_id"] is not None
    assert (second["score_id"], second["name"]) == (first["score_id"], first["name"])
    assert second["timestamp"] is not None
    assert second["timestamp"] == first["timestamp"]


def test_each_answer_gets_its_own_score(
    client: TestClient, store: InMemoryConversationStore, langfuse: FakeLangfuse
) -> None:
    client.put(_answered(store), json={"rating": "up"}, headers=_as(ALICE))
    client.put(_answered(store), json={"rating": "up"}, headers=_as(ALICE))

    first, second = langfuse.scores
    assert first["score_id"] != second["score_id"]
