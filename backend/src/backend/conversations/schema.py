"""SQLAlchemy Core definitions of `conversations` and `messages` (mirrored by migration 0006).

The `user_id -> auth.users` foreign key lives only in the migration: auth.users belongs
to Supabase and is not part of our metadata.
"""

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    CheckConstraint,
    Column,
    ForeignKey,
    Identity,
    Index,
    MetaData,
    Table,
    Text,
    Uuid,
    text,
)

metadata = MetaData()

_CLOCK = text("clock_timestamp()")

conversations_table = Table(
    "conversations",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("user_id", Uuid, nullable=False),
    Column("title", Text),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=_CLOCK),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=_CLOCK),
)

Index(
    "ix_conversations_user_updated",
    conversations_table.c.user_id,
    conversations_table.c.updated_at.desc(),
)

messages_table = Table(
    "messages",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column(
        "conversation_id",
        Uuid,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("seq", BigInteger, Identity(always=True), nullable=False),
    Column("role", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("trace_id", Text),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=_CLOCK),
    CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
)

Index("ix_messages_conversation_seq", messages_table.c.conversation_id, messages_table.c.seq)
