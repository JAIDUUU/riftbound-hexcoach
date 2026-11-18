"""Migration 0011 against Postgres: the account cascade and quota/schema.py's mirror."""

import uuid
from collections.abc import Callable
from datetime import date

import pytest
from sqlalchemy import Connection, func, select, text

from backend.quota.schema import daily_usage_table, metadata
from backend.quota.store import SqlUsageStore
from tests.schema_mirror import assert_schema_mirrors

pytestmark = pytest.mark.integration

DAY = date(2026, 11, 17)


def test_deleting_the_account_deletes_its_usage(
    db_connection: Connection, new_auth_user: Callable[[], uuid.UUID]
) -> None:
    store = SqlUsageStore(db_connection)
    alice, bob = new_auth_user(), new_auth_user()
    store.consume(alice, DAY, limit=5)
    store.consume(bob, DAY, limit=5)

    db_connection.execute(text("DELETE FROM auth.users WHERE id = :id"), {"id": alice})

    owned_by_alice = daily_usage_table.c.user_id == alice
    count = select(func.count()).select_from(daily_usage_table).where(owned_by_alice)
    assert db_connection.execute(count).scalar_one() == 0
    assert store.consume(bob, DAY, limit=5) == 2


def test_the_declared_schema_and_the_migrated_database_match(db_connection: Connection) -> None:
    assert_schema_mirrors(db_connection, metadata)
