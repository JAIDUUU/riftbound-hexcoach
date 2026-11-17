import uuid
from collections.abc import Generator
from contextlib import contextmanager

import jwt
import pytest
from fastapi.testclient import TestClient
from tests.api.tokens import ISSUER, fake_verifier, mint
from tests.conversations.memory_store import InMemoryConversationStore

from backend.api.app import create_app
from backend.api.auth import TokenVerifier
from backend.conversations.limits import MAX_TITLE_CHARS, Limits
from backend.conversations.store import ConversationStore

ALICE = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")
BOB = uuid.UUID("bbbbbbbb-0000-4000-8000-000000000002")


@pytest.fixture
def store() -> InMemoryConversationStore:
    return InMemoryConversationStore(Limits())


def _client(store: InMemoryConversationStore, verifier: TokenVerifier) -> TestClient:
    @contextmanager
    def open_store() -> Generator[ConversationStore]:
        yield store

    return TestClient(create_app(verifier, open_store))


@pytest.fixture
def client(store: InMemoryConversationStore) -> TestClient:
    return _client(store, fake_verifier())


def _as(user: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint(user)}"}


def test_requests_without_a_token_are_rejected_with_a_bearer_challenge(client: TestClient) -> None:
    response = client.get("/conversations")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_requests_with_an_invalid_token_are_rejected(client: TestClient) -> None:
    response = client.get("/conversations", headers={"Authorization": "Bearer not.a.jwt"})

    assert response.status_code == 401


def test_a_signing_key_outage_is_a_503_not_a_401(store: InMemoryConversationStore) -> None:
    def keys_down(token: str) -> object:
        raise jwt.PyJWKClientConnectionError("down")

    client = _client(store, TokenVerifier(keys_down, ISSUER))

    assert client.get("/conversations", headers=_as(ALICE)).status_code == 503


def test_the_owner_can_create_list_read_and_delete(client: TestClient) -> None:
    created = client.post("/conversations", json={"title": "Scoring"}, headers=_as(ALICE))
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    listed = client.get("/conversations", headers=_as(ALICE)).json()
    assert [c["id"] for c in listed] == [conversation_id]

    read = client.get(f"/conversations/{conversation_id}", headers=_as(ALICE))
    assert read.status_code == 200
    assert read.json()["title"] == "Scoring"
    assert read.json()["messages"] == []

    deleted = client.delete(f"/conversations/{conversation_id}", headers=_as(ALICE))
    assert deleted.status_code == 204
    gone = client.get(f"/conversations/{conversation_id}", headers=_as(ALICE))
    assert gone.status_code == 404


def test_the_verified_user_id_is_what_the_store_sees(
    client: TestClient, store: InMemoryConversationStore
) -> None:
    client.post("/conversations", json={}, headers=_as(ALICE))

    assert [row.owner for row in store.rows.values()] == [ALICE]


def test_another_users_conversation_is_not_found_for_read_and_delete(
    client: TestClient,
) -> None:
    conversation_id = client.post("/conversations", json={}, headers=_as(ALICE)).json()["id"]

    assert client.get("/conversations", headers=_as(BOB)).json() == []
    assert client.get(f"/conversations/{conversation_id}", headers=_as(BOB)).status_code == 404
    assert client.delete(f"/conversations/{conversation_id}", headers=_as(BOB)).status_code == 404
    # Alice's conversation survived Bob's delete attempt.
    assert client.get(f"/conversations/{conversation_id}", headers=_as(ALICE)).status_code == 200


def test_reading_returns_messages_with_their_trace_ids(
    client: TestClient, store: InMemoryConversationStore
) -> None:
    conversation_id = client.post("/conversations", json={}, headers=_as(ALICE)).json()["id"]
    store.add_message(ALICE, uuid.UUID(conversation_id), "user", "Can I score twice?")
    store.add_message(ALICE, uuid.UUID(conversation_id), "assistant", "No.", "trace-9")

    messages = client.get(f"/conversations/{conversation_id}", headers=_as(ALICE)).json()[
        "messages"
    ]

    assert [(m["role"], m["content"], m["trace_id"]) for m in messages] == [
        ("user", "Can I score twice?", None),
        ("assistant", "No.", "trace-9"),
    ]


def test_titles_over_the_cap_are_refused(client: TestClient) -> None:
    response = client.post(
        "/conversations", json={"title": "x" * (MAX_TITLE_CHARS + 1)}, headers=_as(ALICE)
    )

    assert response.status_code == 422


def test_a_malformed_conversation_id_is_a_validation_error(client: TestClient) -> None:
    assert client.get("/conversations/not-a-uuid", headers=_as(ALICE)).status_code == 422
