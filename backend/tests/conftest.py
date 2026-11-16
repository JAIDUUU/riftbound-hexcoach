from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import Connection

from backend.cards.collapse import Card, collapse_printings
from backend.cards.rifthunt import RifthuntSnapshot
from backend.cards.snapshot import read_snapshot
from backend.config import MissingConfigError, database_url
from backend.db import make_engine, upgrade_to_head

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def rifthunt_sample() -> RifthuntSnapshot:
    """A slice of the real Rifthunt bulk snapshot: 32 printings of 8 distinct cards."""
    return read_snapshot(FIXTURES / "rifthunt_sample.json")


@pytest.fixture(scope="session")
def cards_by_name(rifthunt_sample: RifthuntSnapshot) -> dict[str, Card]:
    """The sample snapshot collapsed into Cards, keyed by oracle name."""
    return {card.oracle_name: card for card in collapse_printings(rifthunt_sample)}


@pytest.fixture
def poro_claiming_sonas_name(cards_by_name: dict[str, Card]) -> Card:
    """A Pouty Poro whose alias is another card's oracle name, making that lookup ambiguous."""
    return replace(cards_by_name["Pouty Poro"], aliases=("SONA, Harmonious",))


@pytest.fixture(scope="session")
def migrated_database() -> None:
    """Apply the Alembic migrations once, so the schema under test is the one Alembic produces.

    Skipped when DATABASE_URL is not configured (for example in CI).
    """
    try:
        database_url()
    except MissingConfigError:
        pytest.skip("DATABASE_URL is not configured")
    upgrade_to_head()
    upgrade_to_head()  # twice: re-runnability is part of the migrations' contract


@pytest.fixture
def db_connection(migrated_database: None) -> Iterator[Connection]:
    """A connection to the real database inside a transaction that is always rolled back."""
    engine = make_engine()
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()
    engine.dispose()
