"""SQLAlchemy Core definition of the `cards` table (mirrored by the Alembic migration)."""

from sqlalchemy import (
    TIMESTAMP,
    Column,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY

metadata = MetaData()

cards_table = Table(
    "cards",
    metadata,
    Column("oracle_id", Uuid, primary_key=True),
    Column("oracle_name", Text, nullable=False),
    Column("aliases", ARRAY(Text), nullable=False, server_default=text("'{}'")),
    Column("card_type", Text, nullable=False),
    Column("supertype", Text),
    Column("domains", ARRAY(Text), nullable=False, server_default=text("'{}'")),
    Column("energy", Integer),
    Column("might", Integer),
    Column("power", Integer),
    Column("rarity", Text, nullable=False),
    Column("tags", ARRAY(Text), nullable=False, server_default=text("'{}'")),
    Column("raw_text", Text, nullable=False),
    Column("cleaned_text", Text, nullable=False),
    Column("representative_id", Text, nullable=False),
    Column("set_code", Text, nullable=False),
    Column("image_path", Text),
    Column("image_url", Text, nullable=False),
    Column("printing_count", Integer, nullable=False),
    Column("snapshot_fetched", TIMESTAMP(timezone=True), nullable=False),
)

Index("ix_cards_oracle_name_lower", func.lower(cards_table.c.oracle_name), unique=True)
