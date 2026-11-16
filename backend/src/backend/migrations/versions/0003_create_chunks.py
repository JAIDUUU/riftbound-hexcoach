"""Create the chunks table with a stored tsvector for full-text search.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chunks",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("rule_id", sa.Text()),
        sa.Column("section", sa.Text()),
        sa.Column("parent_rule_id", sa.Text()),
        sa.Column("is_heading", sa.Boolean(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_version", sa.Text(), nullable=False),
        sa.Column("source_date", sa.Date(), nullable=False),
        sa.Column(
            "search",
            TSVECTOR(),
            sa.Computed("to_tsvector('english', text)", persisted=True),
        ),
    )
    op.create_index("ix_chunks_search", "chunks", ["search"], postgresql_using="gin")
    op.create_index(
        "ix_chunks_source_rule",
        "chunks",
        ["source_type", "rule_id"],
        unique=True,
        postgresql_where=sa.text("rule_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_source_rule", table_name="chunks")
    op.drop_index("ix_chunks_search", table_name="chunks")
    op.drop_table("chunks")
