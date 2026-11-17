"""Create decks, owned by Supabase Auth users.

Deleting a user (auth.users) cascades to their decks, which account deletion relies on.
A deck stores the player's Decklist text as written; parsing and card resolution happen
in code on every import, so a card snapshot refresh never leaves stale rows behind.

Locked like every other table (0007, 0008): row level security with no policies, and no
privileges for the Data API's client roles. 0008's default privileges already keep new
tables closed; the explicit REVOKE holds even if this runs as a different role.

Timestamps default to clock_timestamp(), not now(), matching 0006.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamp(name: str) -> sa.Column[object]:
    return sa.Column(
        name,
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("clock_timestamp()"),
    )


def upgrade() -> None:
    op.create_table(
        "decks",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("auth.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("decklist", sa.Text(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
    )
    op.create_index("ix_decks_user_updated", "decks", ["user_id", sa.text("updated_at DESC")])
    op.execute("ALTER TABLE decks ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON decks FROM anon, authenticated")


def downgrade() -> None:
    op.drop_table("decks")
