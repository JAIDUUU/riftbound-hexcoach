"""Migration 0011 against Postgres: the account cascade and quota/schema.py's mirror."""

import uuid
from collections.abc import Callable
from datetime import date

import pytest
from sqlalchemy import CheckConstraint, Connection, func, inspect, select, text

from backend.quota.schema import daily_usage_table, metadata
from backend.quota.store import SqlUsageStore

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


def test_every_declared_column_and_check_exists_in_the_migrated_database(
    db_connection: Connection,
) -> None:
    inspector = inspect(db_connection)
    for table in metadata.tables.values():
        live_checks = {check["name"] for check in inspector.get_check_constraints(table.name)}
        live_columns = {column["name"] for column in inspector.get_columns(table.name)}
        live_key = inspector.get_pk_constraint(table.name)["constrained_columns"]

        declared_checks = {c.name for c in table.constraints if isinstance(c, CheckConstraint)}
        assert declared_checks <= live_checks, table.name
        assert set(table.columns.keys()) == live_columns, table.name
        assert live_key == [column.name for column in table.primary_key.columns], table.name
