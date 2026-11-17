"""Create daily_usage: how many messages each user has sent per UTC day.

The daily message quota (issue #20) counts here, so the count survives restarts and is
shared by every API process. One row per user per day they sent a message; the key is
(user_id, day), which is also what the counting upsert conflicts on. A refunded message
(its run failed) is subtracted again, so a row can drop back to zero. Deleting a user
(auth.users) cascades to their rows. Old days are never read again and stay small (one
row per active user per day); nothing prunes them yet.

Locked like every other table (0007, 0008): row level security with no policies, and no
privileges for the Data API's client roles.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_usage",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("auth.users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("messages", sa.Integer(), nullable=False),
        sa.CheckConstraint("messages >= 0", name="ck_daily_usage_messages_not_negative"),
    )
    op.execute("ALTER TABLE daily_usage ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON daily_usage FROM anon, authenticated")


def downgrade() -> None:
    op.drop_table("daily_usage")
