"""Stop Supabase's default privileges from reopening the Data API on new objects.

0007 revoked the anon/authenticated grants on the tables that existed then, but the
postgres role's default privileges in `public` grant both roles everything on every new
table, sequence and function, so each future migration would reopen the hole. This
revokes those defaults for postgres (the role our migrations run as) and the grants the
existing sequences still carry.

Functions are only partly covered: this removes Supabase's explicit anon/authenticated
grant, but Postgres's built-in EXECUTE for PUBLIC can only be revoked globally (not per
schema), which would also reach functions that extensions install. We have no
functions; any future function in public must REVOKE EXECUTE ... FROM PUBLIC itself,
since the Data API exposes callable functions as RPC endpoints.

Objects created by supabase_admin keep Supabase's own defaults; we cannot alter that
role's, and nothing of ours is created as it.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLIENT_ROLES = "anon, authenticated"


def upgrade() -> None:
    defaults = "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public"
    op.execute(f"{defaults} REVOKE ALL ON TABLES FROM {_CLIENT_ROLES}")
    op.execute(f"{defaults} REVOKE ALL ON SEQUENCES FROM {_CLIENT_ROLES}")
    op.execute(f"{defaults} REVOKE ALL ON FUNCTIONS FROM {_CLIENT_ROLES}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {_CLIENT_ROLES}")


def downgrade() -> None:
    # Restores Supabase's defaults, which reopens the Data API for new objects.
    defaults = "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public"
    op.execute(f"{defaults} GRANT ALL ON TABLES TO {_CLIENT_ROLES}")
    op.execute(f"{defaults} GRANT ALL ON SEQUENCES TO {_CLIENT_ROLES}")
    op.execute(f"{defaults} GRANT ALL ON FUNCTIONS TO {_CLIENT_ROLES}")
    op.execute(f"GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO {_CLIENT_ROLES}")
