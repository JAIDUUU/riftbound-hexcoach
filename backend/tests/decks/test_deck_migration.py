"""Migration 0009 against Postgres: the account cascade and decks/schema.py's mirror."""

import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import Connection, func, inspect, select, text

from backend.decks.schema import decks_table, metadata
from backend.decks.store import SqlDeckStore

pytestmark = pytest.mark.integration


def test_deleting_the_account_deletes_its_decks(
    db_connection: Connection, new_auth_user: Callable[[], uuid.UUID]
) -> None:
    store = SqlDeckStore(db_connection)
    alice, bob = new_auth_user(), new_auth_user()
    store.create(alice, "Annie burn", "Legend:\n1 Annie, Dark Child\n")
    kept = store.create(bob, "Sona control", "")

    db_connection.execute(text("DELETE FROM auth.users WHERE id = :id"), {"id": alice})

    owned_by_alice = decks_table.c.user_id == alice
    count = select(func.count()).select_from(decks_table).where(owned_by_alice)
    assert db_connection.execute(count).scalar_one() == 0
    assert store.get(bob, kept.id) == kept


def test_every_declared_column_and_index_exists_in_the_migrated_database(
    db_connection: Connection,
) -> None:
    inspector = inspect(db_connection)
    for table in metadata.tables.values():
        live_indexes = {index["name"] for index in inspector.get_indexes(table.name)}
        live_columns = {column["name"] for column in inspector.get_columns(table.name)}

        assert {index.name for index in table.indexes} <= live_indexes, table.name
        assert set(table.columns.keys()) == live_columns, table.name
