"""Store the player's feedback (thumbs up/down) on assistant messages.

The rating is the source of truth for what the thumbs show after a reload; Langfuse
gets a copy as a score on the message's trace. feedback_given_at is when feedback was
first given and survives rating changes: Langfuse replaces a score only when its id,
name and timestamp date all match, so the backend resends this timestamp to make a
changed vote replace the old score instead of adding a second one.

Feedback lives on the message row, so it is deleted with the message (and so with the
conversation and the account). No new table, so RLS and grants are unchanged.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("feedback", sa.Text()))
    op.add_column("messages", sa.Column("feedback_given_at", sa.TIMESTAMP(timezone=True)))
    op.create_check_constraint(
        "ck_messages_feedback",
        "messages",
        "(feedback IS NULL AND feedback_given_at IS NULL)"
        " OR (feedback IN ('up', 'down') AND feedback_given_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_messages_feedback_target",
        "messages",
        "feedback IS NULL OR (role = 'assistant' AND trace_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_messages_feedback_target", "messages", type_="check")
    op.drop_constraint("ck_messages_feedback", "messages", type_="check")
    op.drop_column("messages", "feedback_given_at")
    op.drop_column("messages", "feedback")
