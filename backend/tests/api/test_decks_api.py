import uuid
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.api.app import DeckAccess, create_app
from backend.cards.collapse import Card
from backend.conversations.limits import Limits
from tests.api.accounts import unused_account_deletion
from tests.api.coaches import unused_coach
from tests.api.tokens import fake_verifier, mint
from tests.cards.memory_catalog import InMemoryCardCatalog
from tests.conversations.memory_store import InMemoryConversationStore
from tests.decks.memory_store import InMemoryDeckStore

ALICE = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")
BOB = uuid.UUID("bbbbbbbb-0000-4000-8000-000000000002")

DECKLIST = (
    "Legend:\n1 Annie, Dark Child\n\nChampion:\n1 sona, harmonious\n\nMainDeck:\n3 Pouty Porro\n"
)


@pytest.fixture
def decks() -> InMemoryDeckStore:
    return InMemoryDeckStore()


@pytest.fixture
def client(decks: InMemoryDeckStore, cards_by_name: dict[str, Card]) -> TestClient:
    conversations = InMemoryConversationStore(Limits())
    cards = InMemoryCardCatalog(cards_by_name.values())

    @contextmanager
    def open_store() -> Generator[InMemoryConversationStore]:
        yield conversations

    @contextmanager
    def open_decks() -> Generator[DeckAccess]:
        yield DeckAccess(decks, cards)

    return TestClient(
        create_app(
            fake_verifier(),
            open_store,
            open_decks=open_decks,
            coach=unused_coach,
            delete_account=unused_account_deletion,
        )
    )


def _as(user: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint(user)}"}


def _section(validation: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return next(s["cards"] for s in validation["sections"] if s["section"] == name)


def test_deck_endpoints_need_a_token(client: TestClient) -> None:
    assert client.get("/decks").status_code == 401
    assert client.post("/decks", json={"name": "x", "decklist": ""}).status_code == 401
    assert client.post("/decks/preview", json={"decklist": ""}).status_code == 401


def test_saving_a_deck_returns_its_import_validation_by_section(client: TestClient) -> None:
    response = client.post(
        "/decks", json={"name": "Annie burn", "decklist": DECKLIST}, headers=_as(ALICE)
    )

    assert response.status_code == 201
    body = response.json()
    assert (body["name"], body["decklist"]) == ("Annie burn", DECKLIST)
    validation = body["validation"]
    assert [s["section"] for s in validation["sections"]] == [
        "Legend",
        "Champion",
        "MainDeck",
        "Battlefields",
        "Runes",
        "Sideboard",
    ]
    (champion,) = _section(validation, "Champion")
    assert champion["count"] == 1
    assert champion["name"] == "sona, harmonious"
    assert champion["card"]["oracle_name"] == "Sona, Harmonious"
    assert uuid.UUID(champion["card"]["oracle_id"])
    (unknown,) = _section(validation, "MainDeck")
    assert unknown["card"] is None
    assert unknown["suggestions"] == ["Pouty Poro"]


def test_warnings_are_reported_but_never_block_saving(
    client: TestClient, decks: InMemoryDeckStore
) -> None:
    response = client.post(
        "/decks", json={"name": "Messy", "decklist": "nonsense\n4 Xyzzy"}, headers=_as(ALICE)
    )

    assert response.status_code == 201
    warnings = response.json()["validation"]["warnings"]
    assert (warnings[0]["kind"], warnings[0]["line"]) == ("malformed_line", 1)
    assert {w["kind"] for w in warnings} >= {"malformed_line", "outside_section", "section_size"}
    assert [row.deck.decklist for row in decks.rows.values()] == ["nonsense\n4 Xyzzy"]


def test_a_preview_validates_without_saving(client: TestClient, decks: InMemoryDeckStore) -> None:
    response = client.post("/decks/preview", json={"decklist": DECKLIST}, headers=_as(ALICE))

    assert response.status_code == 200
    (legend,) = _section(response.json(), "Legend")
    assert legend["card"]["oracle_name"] == "Annie, Dark Child"
    assert any(w["kind"] == "unknown_card" for w in response.json()["warnings"])
    assert decks.rows == {}


def test_the_owner_can_list_read_update_and_delete(client: TestClient) -> None:
    deck_id = client.post(
        "/decks", json={"name": "Annie burn", "decklist": DECKLIST}, headers=_as(ALICE)
    ).json()["id"]

    listed = client.get("/decks", headers=_as(ALICE)).json()
    assert [(d["id"], d["name"]) for d in listed] == [(deck_id, "Annie burn")]
    assert "decklist" not in listed[0]  # the list is for picking a deck; read for the rest

    read = client.get(f"/decks/{deck_id}", headers=_as(ALICE))
    assert read.status_code == 200
    assert _section(read.json()["validation"], "Legend")[0]["card"] is not None

    fixed = DECKLIST.replace("Pouty Porro", "Pouty Poro")
    updated = client.put(
        f"/decks/{deck_id}", json={"name": "Annie burn v2", "decklist": fixed}, headers=_as(ALICE)
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Annie burn v2"
    (poro,) = _section(updated.json()["validation"], "MainDeck")
    assert poro["card"]["oracle_name"] == "Pouty Poro"

    assert client.delete(f"/decks/{deck_id}", headers=_as(ALICE)).status_code == 204
    assert client.get(f"/decks/{deck_id}", headers=_as(ALICE)).status_code == 404


def test_another_users_deck_is_not_found_for_read_update_and_delete(
    client: TestClient,
) -> None:
    deck_id = client.post(
        "/decks", json={"name": "Annie burn", "decklist": DECKLIST}, headers=_as(ALICE)
    ).json()["id"]
    edit = {"name": "Mine now", "decklist": ""}

    assert client.get("/decks", headers=_as(BOB)).json() == []
    assert client.get(f"/decks/{deck_id}", headers=_as(BOB)).status_code == 404
    assert client.put(f"/decks/{deck_id}", json=edit, headers=_as(BOB)).status_code == 404
    assert client.delete(f"/decks/{deck_id}", headers=_as(BOB)).status_code == 404
    survivor = client.get(f"/decks/{deck_id}", headers=_as(ALICE)).json()
    assert (survivor["name"], survivor["decklist"]) == ("Annie burn", DECKLIST)


def test_reading_a_deck_validates_it_against_the_current_cards(
    decks: InMemoryDeckStore, cards_by_name: dict[str, Card]
) -> None:
    cards = InMemoryCardCatalog([])

    @contextmanager
    def open_decks() -> Generator[DeckAccess]:
        yield DeckAccess(decks, cards)

    @contextmanager
    def no_conversations() -> Generator[InMemoryConversationStore]:
        yield InMemoryConversationStore(Limits())

    client = TestClient(
        create_app(
            fake_verifier(),
            no_conversations,
            open_decks=open_decks,
            coach=unused_coach,
            delete_account=unused_account_deletion,
        )
    )
    saved = client.post(
        "/decks",
        json={"name": "Early", "decklist": "Legend:\n1 Annie, Dark Child"},
        headers=_as(ALICE),
    ).json()
    assert _section(saved["validation"], "Legend")[0]["card"] is None

    cards.cards.append(cards_by_name["Annie, Dark Child"])  # a later card snapshot has it
    read = client.get(f"/decks/{saved['id']}", headers=_as(ALICE)).json()

    assert _section(read["validation"], "Legend")[0]["card"]["oracle_name"] == "Annie, Dark Child"


@pytest.mark.parametrize("name", ["", "x" * 101])
def test_a_deck_name_must_be_present_and_short(client: TestClient, name: str) -> None:
    response = client.post("/decks", json={"name": name, "decklist": ""}, headers=_as(ALICE))

    assert response.status_code == 422


def _capped_client(decks: InMemoryDeckStore, max_chars: int) -> TestClient:
    @contextmanager
    def open_decks() -> Generator[DeckAccess]:
        yield DeckAccess(decks, InMemoryCardCatalog([]), max_decklist_chars=max_chars)

    @contextmanager
    def no_conversations() -> Generator[InMemoryConversationStore]:
        yield InMemoryConversationStore(Limits())

    return TestClient(
        create_app(
            fake_verifier(),
            no_conversations,
            open_decks=open_decks,
            coach=unused_coach,
            delete_account=unused_account_deletion,
        )
    )


def test_a_decklist_over_the_size_cap_is_a_plain_422_and_nothing_is_saved(
    decks: InMemoryDeckStore,
) -> None:
    client = _capped_client(decks, max_chars=10)
    saved = decks.create(ALICE, "Short", "Runes:")
    too_long = "x" * 11
    expected = {"detail": "Decklist is 11 characters; the limit is 10."}

    preview = client.post("/decks/preview", json={"decklist": too_long}, headers=_as(ALICE))
    create = client.post("/decks", json={"name": "Long", "decklist": too_long}, headers=_as(ALICE))
    update = client.put(
        f"/decks/{saved.id}", json={"name": "Long", "decklist": too_long}, headers=_as(ALICE)
    )

    assert [r.status_code for r in (preview, create, update)] == [422, 422, 422]
    assert [r.json() for r in (preview, create, update)] == [expected] * 3
    assert decks.list_for_user(ALICE) == [saved]


def test_a_deck_saved_before_the_cap_was_lowered_can_still_be_read(
    decks: InMemoryDeckStore,
) -> None:
    saved = decks.create(ALICE, "Old", "Runes:\n12 Fury Rune\n")

    response = _capped_client(decks, max_chars=5).get(f"/decks/{saved.id}", headers=_as(ALICE))

    assert response.status_code == 200
    assert response.json()["decklist"] == "Runes:\n12 Fury Rune\n"
