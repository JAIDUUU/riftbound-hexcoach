"""Let the player rate answers that have no trace.

Answers are untraced whenever the Langfuse keys aren't set, and 0009 only allowed
feedback on traced ones, so every vote was refused. The rating is the source of truth
and is stored either way; only a traced answer's rating is also sent to Langfuse.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_messages_feedback_target", "messages", type_="check")
    op.create_check_constraint(
        "ck_messages_feedback_target", "messages", "feedback IS NULL OR role = 'assistant'"
    )


def downgrade() -> None:
    # 0009's constraint refuses feedback on untraced answers, so those ratings go first.
    op.execute(
        "UPDATE messages SET feedback = NULL, feedback_given_at = NULL"
        " WHERE feedback IS NOT NULL AND trace_id IS NULL"
    )
    op.drop_constraint("ck_messages_feedback_target", "messages", type_="check")
    op.create_check_constraint(
        "ck_messages_feedback_target",
        "messages",
        "feedback IS NULL OR (role = 'assistant' AND trace_id IS NOT NULL)",
    )
