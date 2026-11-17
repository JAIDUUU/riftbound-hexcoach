"""Close Supabase's Data API over our tables.

Supabase exposes the public schema through its Data API to anyone holding the anon key
(which the frontend ships), and its default privileges grant the anon and authenticated
roles everything on new tables - including DELETE and TRUNCATE on cards, chunks and
alembic_version. Nothing of ours uses the Data API: the backend connects as the table
owner, which bypasses RLS. So every table gets row level security with no policies, and
the two client roles lose their privileges (TRUNCATE is not subject to RLS).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("cards", "chunks", "alembic_version", "conversations", "messages")
_NEWLY_PROTECTED = ("cards", "chunks", "alembic_version")  # 0006 already covered the rest


def upgrade() -> None:
    for table in _NEWLY_PROTECTED:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    for table in _TABLES:
        op.execute(f"REVOKE ALL ON {table} FROM anon, authenticated")


def downgrade() -> None:
    # Restores Supabase's defaults, which reopens the Data API.
    for table in _TABLES:
        op.execute(f"GRANT ALL ON {table} TO anon, authenticated")
    for table in _NEWLY_PROTECTED:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
