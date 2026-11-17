"""Create conversations and messages, owned by Supabase Auth users.

Deleting a user (auth.users) cascades to their conversations, and deleting a
conversation cascades to its messages. Row level security is enabled with no policies:
the Supabase Data API (anon/authenticated roles) can reach nothing, while the backend
connects as the table owner, which bypasses RLS, and enforces ownership itself.

Timestamps default to clock_timestamp(), not now(): now() is fixed for a whole
transaction, and a request writes several rows in one. Messages are ordered by an
identity column, so two messages written in the same microsecond still have an order.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
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
        "conversations",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("auth.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text()),
        _timestamp("created_at"),
        _timestamp("updated_at"),
    )
    op.create_index(
        "ix_conversations_user_updated", "conversations", ["user_id", sa.text("updated_at DESC")]
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.Text()),
        _timestamp("created_at"),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
    )
    op.create_index("ix_messages_conversation_seq", "messages", ["conversation_id", "seq"])
    op.execute("ALTER TABLE conversations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE messages ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("conversations")
