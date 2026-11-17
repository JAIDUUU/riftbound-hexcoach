"""Counting rules every UsageStore must honour.

Each test runs against the in-memory fake (always) and the Postgres store (only with
`pytest -m integration`), which keeps the fake behind the quota and API tests honest.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import cast

import pytest
from sqlalchemy import Connection

from backend.quota.store import SqlUsageStore, UsageStore
from tests.quota.memory_usage import InMemoryUsageStore

MONDAY = date(2026, 11, 16)
TUESDAY = date(2026, 11, 17)


@dataclass
class Harness:
    store: UsageStore
    new_user: Callable[[], uuid.UUID]


@pytest.fixture(params=["memory", pytest.param("sql", marks=pytest.mark.integration)])
def harness(request: pytest.FixtureRequest) -> Harness:
    if cast(str, request.param) == "memory":
        return Harness(InMemoryUsageStore(), uuid.uuid4)
    connection = cast(Connection, request.getfixturevalue("db_connection"))
    new_user = cast(Callable[[], uuid.UUID], request.getfixturevalue("new_auth_user"))
    return Harness(SqlUsageStore(connection), new_user)


def test_messages_are_counted_up_to_the_limit_and_then_refused(harness: Harness) -> None:
    alice = harness.new_user()

    counts = [harness.store.consume(alice, MONDAY, limit=3) for _ in range(4)]

    assert counts == [1, 2, 3, None]
    assert harness.store.consume(alice, MONDAY, limit=3) is None  # still full, still uncounted


def test_each_user_and_each_day_has_its_own_count(harness: Harness) -> None:
    alice, bob = harness.new_user(), harness.new_user()
    harness.store.consume(alice, MONDAY, limit=1)

    assert harness.store.consume(alice, MONDAY, limit=1) is None
    assert harness.store.consume(bob, MONDAY, limit=1) == 1
    assert harness.store.consume(alice, TUESDAY, limit=1) == 1


def test_a_lowered_limit_applies_to_what_is_already_counted(harness: Harness) -> None:
    alice = harness.new_user()
    for _ in range(3):
        harness.store.consume(alice, MONDAY, limit=5)

    assert harness.store.consume(alice, MONDAY, limit=2) is None
    assert harness.store.consume(alice, MONDAY, limit=4) == 4  # the refusal counted nothing
