import uuid

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.auth import TokenVerifier
from backend.api.dependencies import Store, User
from backend.cards.collapse import Card
from backend.conversations.limits import MAX_TITLE_CHARS, Limits
from tests.api.app_factory import make_app, opening_cards
from tests.api.tokens import ISSUER, fake_verifier, mint
from tests.cards.memory_catalog import InMemoryCardCatalog
from tests.conversations.memory_store import InMemoryConversationStore

ALICE = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")
BOB = uuid.UUID("bbbbbbbb-0000-4000-8000-000000000002")


@pytest.fixture
def store() -> InMemoryConversationStore:
    return InMemoryConversationStore(Limits())


def _app(store: InMemoryConversationStore, verifier: TokenVerifier) -> FastAPI:
    return make_app(store=store, verifier=verifier)


def _client(store: InMemoryConversationStore, verifier: TokenVerifier) -> TestClient:
    return TestClient(_app(store, verifier))


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


def test_reading_gives_each_answer_its_validated_cards_as_final_did(
    store: InMemoryConversationStore, cards_by_name: dict[str, Card]
) -> None:
    catalog = InMemoryCardCatalog(cards_by_name.values())
    client = TestClient(make_app(store=store, open_cards=opening_cards(catalog)))
    conversation = store.create(ALICE, None)
    store.add_message(ALICE, conversation.id, "user", "Can [[Pouty Poro]] be targeted?")
    store.add_message(
        ALICE, conversation.id, "assistant", "Not cheaply: [[Pouty Poro]] has Deflect.", "t-1"
    )
    store.add_message(ALICE, conversation.id, "user", "And [[Pouty Poros]]?")
    store.add_message(ALICE, conversation.id, "assistant", "[[Pouty Poros]] is not a card.", "t-2")

    messages = client.get(f"/conversations/{conversation.id}", headers=_as(ALICE)).json()[
        "messages"
    ]

    assert [[c["oracle_name"] for c in m["cards"]] for m in messages] == [
        [],  # the player's own tags are not validated
        ["Pouty Poro"],
        [],
        [],  # an unknown tag stays plain text
    ]
    assert messages[1]["cards"][0] == {
        "oracle_id": "df4c1239-7d32-465d-8811-c95ed6827185",
        "oracle_name": "Pouty Poro",
        "tags": ["Pouty Poro"],
        "image_url": "https://images.rifthunt.com/cards/normal/front/ogn/013/pouty-poro.webp",
        "cleaned_text": (
            "Deflect (Opponents must pay Rainbow Rune to choose me with a spell or ability.)"
        ),
    }


class _UnreachableCatalog:
    def find(self, name: str) -> Card | None:
        raise ConnectionError("cards table unreachable")

    def find_by_id(self, oracle_id: str) -> Card | None:
        raise ConnectionError("cards table unreachable")

    def all_names(self) -> list[str]:
        raise ConnectionError("cards table unreachable")


def test_an_unreachable_card_catalog_still_reads_the_conversation_with_plain_tags(
    store: InMemoryConversationStore,
) -> None:
    client = TestClient(make_app(store=store, open_cards=opening_cards(_UnreachableCatalog())))
    conversation = store.create(ALICE, None)
    store.add_message(ALICE, conversation.id, "assistant", "[[Pouty Poro]] has Deflect.", "t-1")

    response = client.get(f"/conversations/{conversation.id}", headers=_as(ALICE))

    assert response.status_code == 200
    assert response.json()["messages"][0]["content"] == "[[Pouty Poro]] has Deflect."
    assert response.json()["messages"][0]["cards"] == []


def test_titles_over_the_cap_are_refused(client: TestClient) -> None:
    response = client.post(
        "/conversations", json={"title": "x" * (MAX_TITLE_CHARS + 1)}, headers=_as(ALICE)
    )

    assert response.status_code == 422


def test_a_player_message_over_the_cap_is_a_422_not_a_500() -> None:
    # No message endpoint exists until #12, so a probe route stands in for it; the
    # handler is app-wide, which is what makes #12's endpoint inherit the mapping.
    store = InMemoryConversationStore(Limits(max_message_chars=10))
    app = _app(store, fake_verifier())

    @app.post("/probe/{conversation_id}")
    def probe(conversation_id: uuid.UUID, user: User, conversations: Store) -> None:
        conversations.add_message(user.id, conversation_id, "user", "x" * 11)

    conversation = store.create(ALICE, None)
    response = TestClient(app).post(f"/probe/{conversation.id}", headers=_as(ALICE))

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Message is 11 characters; the limit is 10.",
        "code": "message_too_long",
    }


def test_a_malformed_conversation_id_is_a_validation_error(client: TestClient) -> None:
    assert client.get("/conversations/not-a-uuid", headers=_as(ALICE)).status_code == 422
