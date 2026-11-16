from collections.abc import Iterator

import pytest
from sqlalchemy import Connection

from backend.config import MissingConfigError, database_url
from backend.db import make_engine, upgrade_to_head


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
