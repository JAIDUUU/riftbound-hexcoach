"""SQLAlchemy Core definition of `decks` (mirrored by migration 0010).

The `user_id -> auth.users` foreign key lives only in the migration: auth.users belongs
to Supabase and is not part of our metadata.
"""

from sqlalchemy import TIMESTAMP, Column, Index, MetaData, Table, Text, Uuid, text

metadata = MetaData()

_CLOCK = text("clock_timestamp()")

decks_table = Table(
    "decks",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("user_id", Uuid, nullable=False),
    Column("name", Text, nullable=False),
    Column("decklist", Text, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=_CLOCK),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=_CLOCK),
)

Index("ix_decks_user_updated", decks_table.c.user_id, decks_table.c.updated_at.desc())
