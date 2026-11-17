"""SQLAlchemy Core definition of `daily_usage` (mirrored by migration 0011).

The `user_id -> auth.users` foreign key lives only in the migration: auth.users belongs
to Supabase and is not part of our metadata.
"""

from sqlalchemy import CheckConstraint, Column, Date, Integer, MetaData, Table, Uuid

metadata = MetaData()

daily_usage_table = Table(
    "daily_usage",
    metadata,
    Column("user_id", Uuid, primary_key=True),
    Column("day", Date, primary_key=True),  # the UTC calendar day
    Column("messages", Integer, nullable=False),
    CheckConstraint("messages > 0", name="ck_daily_usage_messages_positive"),
)
