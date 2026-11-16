"""Add the embedding column to chunks for hybrid retrieval.

Chunks are derived data (re-created by `ingest-rules`), so instead of backfilling the
new NOT NULL column the migration clears the table; re-ingest after upgrading.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSIONS = 384  # bge-small-en-v1.5


def upgrade() -> None:
    op.execute("DELETE FROM chunks")
    op.add_column("chunks", sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False))
    op.create_index(
        "ix_chunks_embedding",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_embedding", table_name="chunks")
    op.drop_column("chunks", "embedding")
