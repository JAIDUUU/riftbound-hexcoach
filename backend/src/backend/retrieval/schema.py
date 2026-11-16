"""SQLAlchemy Core definition of the `chunks` table (mirrored by the Alembic migration).

One row per retrievable chunk. Rules are one chunk per rule id; FAQs and card text join
as further source types later (issue #5). The `search` column is a stored tsvector kept
in sync by Postgres itself, so full-text search needs no application-side indexing step.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Computed,
    Date,
    Identity,
    Index,
    MetaData,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR

metadata = MetaData()

chunks_table = Table(
    "chunks",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("source_type", Text, nullable=False),
    Column("rule_id", Text),
    Column("section", Text),
    Column("parent_rule_id", Text),
    Column("is_heading", Boolean, nullable=False),
    Column("text", Text, nullable=False),
    Column("source_version", Text, nullable=False),
    Column("source_date", Date, nullable=False),
    Column("search", TSVECTOR, Computed("to_tsvector('english', text)", persisted=True)),
)

Index("ix_chunks_search", chunks_table.c.search, postgresql_using="gin")
Index(
    "ix_chunks_source_rule",
    chunks_table.c.source_type,
    chunks_table.c.rule_id,
    unique=True,
    postgresql_where=chunks_table.c.rule_id.is_not(None),
)
