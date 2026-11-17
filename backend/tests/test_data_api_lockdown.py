"""Nothing of ours is reachable through Supabase's Data API (migrations 0007 and 0008).

Schema-wide on purpose, and it also creates objects to prove that new tables, sequences
and functions start out closed. These are integration tests (deselected by default), so
they run wherever `pytest -m integration` runs: before merging any migration.
"""

import pytest
from sqlalchemy import Connection, text

pytestmark = pytest.mark.integration

_PUBLIC_TABLES = text(
    "SELECT c.relname, c.relrowsecurity FROM pg_class c "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'public' AND c.relkind = 'r'"
)

_CLIENT_TABLE_GRANTS = text(
    "SELECT table_name, grantee, privilege_type FROM information_schema.role_table_grants "
    "WHERE table_schema = 'public' AND grantee IN ('anon', 'authenticated')"
)

_CLIENT_SEQUENCE_GRANTS = text(
    "SELECT object_name, grantee FROM information_schema.role_usage_grants "
    "WHERE object_schema = 'public' AND grantee IN ('anon', 'authenticated')"
)


def test_every_public_table_has_row_level_security(db_connection: Connection) -> None:
    tables = dict(db_connection.execute(_PUBLIC_TABLES).tuples().all())

    assert {"cards", "chunks", "conversations", "messages", "decks"} <= tables.keys()
    assert [name for name, protected in tables.items() if not protected] == []


def test_the_client_roles_hold_no_privileges_on_tables_or_sequences(
    db_connection: Connection,
) -> None:
    assert db_connection.execute(_CLIENT_TABLE_GRANTS).all() == []
    assert db_connection.execute(_CLIENT_SEQUENCE_GRANTS).all() == []


def test_new_tables_and_sequences_start_without_client_role_privileges(
    db_connection: Connection,
) -> None:
    # Created in the test transaction (rolled back), as a migration would create them.
    db_connection.execute(text("CREATE TABLE public.lockdown_probe (id bigserial PRIMARY KEY)"))

    assert db_connection.execute(_CLIENT_TABLE_GRANTS).all() == []
    assert db_connection.execute(_CLIENT_SEQUENCE_GRANTS).all() == []


def test_new_functions_get_no_explicit_client_role_grant(db_connection: Connection) -> None:
    # Only the explicit Supabase grant is gone; Postgres's built-in EXECUTE for PUBLIC
    # remains (see migration 0008), so a future function must revoke that itself.
    function_defaults = db_connection.execute(
        text(
            "SELECT defaclacl::text FROM pg_default_acl "
            "WHERE defaclrole = 'postgres'::regrole "
            "AND defaclnamespace = 'public'::regnamespace AND defaclobjtype = 'f'"
        )
    ).scalar_one()

    assert "anon=" not in function_defaults
    assert "authenticated=" not in function_defaults
