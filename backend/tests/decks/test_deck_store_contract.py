"""Ownership rules every DeckStore must honour.

Each test runs against the in-memory fake (always) and the Postgres store (only with
`pytest -m integration`), which keeps the fake behind the API tests honest.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

import pytest
from sqlalchemy import Connection

from backend.decks.store import DeckStore, SqlDeckStore
from tests.decks.memory_store import InMemoryDeckStore

LIST = "Legend:\n1 Annie, Dark Child\n"


@dataclass
class Harness:
    store: DeckStore
    new_user: Callable[[], uuid.UUID]


@pytest.fixture(params=["memory", pytest.param("sql", marks=pytest.mark.integration)])
def harness(request: pytest.FixtureRequest) -> Harness:
    if cast(str, request.param) == "memory":
        return Harness(InMemoryDeckStore(), uuid.uuid4)
    connection = cast(Connection, request.getfixturevalue("db_connection"))
    new_user = cast(Callable[[], uuid.UUID], request.getfixturevalue("new_auth_user"))
    return Harness(SqlDeckStore(connection), new_user)


def test_a_created_deck_is_listed_and_read_by_its_owner_only(harness: Harness) -> None:
    alice, bob = harness.new_user(), harness.new_user()

    created = harness.store.create(alice, "Annie burn", LIST)

    assert (created.name, created.decklist) == ("Annie burn", LIST)
    assert [deck.id for deck in harness.store.list_for_user(alice)] == [created.id]
    assert harness.store.get(alice, created.id) == created
    assert harness.store.list_for_user(bob) == []
    assert harness.store.get(bob, created.id) is None  # someone else's: not found
    assert harness.store.get(alice, uuid.uuid4()) is None  # and so is a made-up id


def test_the_owner_can_replace_a_decks_name_and_text(harness: Harness) -> None:
    alice = harness.new_user()
    created = harness.store.create(alice, "Draft", LIST)

    updated = harness.store.update(alice, created.id, "Annie burn v2", "Runes:\n12 Fury Rune\n")

    assert updated is not None
    assert (updated.id, updated.name, updated.decklist) == (
        created.id,
        "Annie burn v2",
        "Runes:\n12 Fury Rune\n",
    )
    assert updated.created_at == created.created_at
    assert updated.updated_at > created.updated_at
    assert harness.store.get(alice, created.id) == updated


def test_nobody_can_update_someone_elses_deck(harness: Harness) -> None:
    alice, bob = harness.new_user(), harness.new_user()
    created = harness.store.create(alice, "Annie burn", LIST)

    assert harness.store.update(bob, created.id, "Mine now", "") is None
    assert harness.store.update(alice, uuid.uuid4(), "Ghost", "") is None
    assert harness.store.get(alice, created.id) == created  # untouched


def test_decks_are_listed_most_recently_updated_first(harness: Harness) -> None:
    alice = harness.new_user()
    older = harness.store.create(alice, "older", LIST)
    newer = harness.store.create(alice, "newer", LIST)
    assert [deck.id for deck in harness.store.list_for_user(alice)] == [newer.id, older.id]

    harness.store.update(alice, older.id, "older, edited", LIST)

    assert [deck.id for deck in harness.store.list_for_user(alice)] == [older.id, newer.id]


def test_only_the_owner_can_delete(harness: Harness) -> None:
    alice, bob = harness.new_user(), harness.new_user()
    created = harness.store.create(alice, "Annie burn", LIST)

    assert harness.store.delete(bob, created.id) is False
    assert harness.store.get(alice, created.id) is not None  # untouched

    assert harness.store.delete(alice, created.id) is True
    assert harness.store.get(alice, created.id) is None
    assert harness.store.delete(alice, created.id) is False  # already gone
