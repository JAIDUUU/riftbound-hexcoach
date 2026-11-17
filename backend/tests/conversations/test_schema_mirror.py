"""conversations/schema.py claims to mirror migration 0006; hold it to that."""

import pytest
from sqlalchemy import CheckConstraint, Connection, inspect

from backend.conversations.schema import metadata

pytestmark = pytest.mark.integration


def test_every_declared_index_and_check_exists_in_the_migrated_database(
    db_connection: Connection,
) -> None:
    inspector = inspect(db_connection)
    for table in metadata.tables.values():
        live_indexes = {index["name"] for index in inspector.get_indexes(table.name)}
        live_checks = {check["name"] for check in inspector.get_check_constraints(table.name)}
        live_columns = {column["name"] for column in inspector.get_columns(table.name)}

        assert {index.name for index in table.indexes} <= live_indexes, table.name
        declared_checks = {c.name for c in table.constraints if isinstance(c, CheckConstraint)}
        assert declared_checks <= live_checks, table.name
        assert set(table.columns.keys()) == live_columns, table.name
