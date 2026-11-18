"""Holding a module's schema.py to the migrated database, in both directions.

Every declared column, index, check constraint and primary key must exist live, and every
live one must be declared, so a migration that adds a column or a constraint without
updating its mirror fails just as a mirror that claims something the migration never made.
Foreign keys to `auth.users` live only in the migrations and aren't compared.
"""

from sqlalchemy import CheckConstraint, Connection, MetaData, inspect


def assert_schema_mirrors(connection: Connection, metadata: MetaData) -> None:
    inspector = inspect(connection)
    for table in metadata.tables.values():
        name = table.name
        live_columns = {column["name"] for column in inspector.get_columns(name)}
        live_indexes = {index["name"] for index in inspector.get_indexes(name)}
        live_checks = {check["name"] for check in inspector.get_check_constraints(name)}
        live_key = inspector.get_pk_constraint(name)["constrained_columns"]

        declared_checks = {c.name for c in table.constraints if isinstance(c, CheckConstraint)}
        assert set(table.columns.keys()) == live_columns, name
        assert {index.name for index in table.indexes} == live_indexes, name
        assert declared_checks == live_checks, name
        assert [column.name for column in table.primary_key.columns] == live_key, name
