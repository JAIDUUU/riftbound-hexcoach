"""conversations/schema.py claims to mirror migrations 0006 and 0009; hold it to that."""

import pytest
from sqlalchemy import Connection

from backend.conversations.schema import metadata
from tests.schema_mirror import assert_schema_mirrors

pytestmark = pytest.mark.integration


def test_the_declared_schema_and_the_migrated_database_match(db_connection: Connection) -> None:
    assert_schema_mirrors(db_connection, metadata)
