"""Two messages taking the last slot of a day at once, on two real connections.

The contract tests run on one connection inside a rolled-back transaction, which can't
show what the single-statement upsert does under concurrency. Here the user is committed
(and deleted afterwards), the first connection takes the slot and holds its transaction
open, and the second, started meanwhile, has to wait for it and then find the day full.
"""

import threading
import time
import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import Connection, Engine, select, text

from backend.db import make_engine
from backend.quota.schema import daily_usage_table
from backend.quota.store import SqlUsageStore

pytestmark = pytest.mark.integration

MONDAY = date(2026, 11, 16)


@pytest.fixture
def engine(migrated_database: None) -> Iterator[Engine]:
    engine = make_engine()
    yield engine
    engine.dispose()


@pytest.fixture
def committed_user(engine: Engine) -> Iterator[uuid.UUID]:
    """A Supabase Auth user both connections can see; deleting it cascades to its usage."""
    user_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO auth.users (id) VALUES (:id)"), {"id": user_id})
    yield user_id
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM auth.users WHERE id = :id"), {"id": user_id})


def _counted(connection: Connection, user_id: uuid.UUID) -> int | None:
    return connection.execute(
        select(daily_usage_table.c.messages).where(
            daily_usage_table.c.user_id == user_id, daily_usage_table.c.day == MONDAY
        )
    ).scalar_one_or_none()


@pytest.mark.parametrize("already_counted", [0, 2], ids=["first message of the day", "last slot"])
def test_two_messages_racing_for_the_last_slot_count_only_one(
    engine: Engine, committed_user: uuid.UUID, already_counted: int
) -> None:
    limit = already_counted + 1
    with engine.begin() as connection:
        for _ in range(already_counted):
            SqlUsageStore(connection).consume(committed_user, MONDAY, limit)

    second: list[int | None] = []
    with engine.connect() as first_connection, engine.connect() as second_connection:
        first_transaction = first_connection.begin()
        assert SqlUsageStore(first_connection).consume(committed_user, MONDAY, limit) == limit

        def race() -> None:
            with second_connection.begin():
                second_connection.execute(text("SET LOCAL lock_timeout = '10s'"))
                second.append(
                    SqlUsageStore(second_connection).consume(committed_user, MONDAY, limit)
                )

        racer = threading.Thread(target=race)
        racer.start()
        time.sleep(0.5)
        assert racer.is_alive(), "the second message should wait for the first's transaction"
        first_transaction.commit()
        racer.join(timeout=15)

    assert not racer.is_alive()
    assert second == [None]
    with engine.connect() as connection:
        assert _counted(connection, committed_user) == limit
