"""No table of ours is reachable through Supabase's Data API (migration 0007).

Schema-wide on purpose: a future migration that adds a table inherits Supabase's
default grants to anon/authenticated, and this test fails until it revokes them.
"""

import pytest
from sqlalchemy import Connection, text

pytestmark = pytest.mark.integration

_PUBLIC_TABLES = text(
    "SELECT c.relname, c.relrowsecurity FROM pg_class c "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'public' AND c.relkind = 'r'"
)

_CLIENT_ROLE_GRANTS = text(
    "SELECT table_name, grantee, privilege_type FROM information_schema.role_table_grants "
    "WHERE table_schema = 'public' AND grantee IN ('anon', 'authenticated')"
)


def test_every_public_table_has_row_level_security(db_connection: Connection) -> None:
    tables = dict(db_connection.execute(_PUBLIC_TABLES).tuples().all())

    assert {"cards", "chunks", "conversations", "messages"} <= tables.keys()
    assert [name for name, protected in tables.items() if not protected] == []


def test_the_client_roles_hold_no_privileges_on_public_tables(db_connection: Connection) -> None:
    assert db_connection.execute(_CLIENT_ROLE_GRANTS).all() == []
