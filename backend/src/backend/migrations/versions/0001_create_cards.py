"""Enable pgvector and create the cards table.

Revision ID: 0001
Revises:
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "cards",
        sa.Column("oracle_id", sa.Uuid(), primary_key=True),
        sa.Column("oracle_name", sa.Text(), nullable=False),
        sa.Column(
            "aliases", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("card_type", sa.Text(), nullable=False),
        sa.Column("supertype", sa.Text()),
        sa.Column(
            "domains", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("energy", sa.Integer()),
        sa.Column("might", sa.Integer()),
        sa.Column("power", sa.Integer()),
        sa.Column("rarity", sa.Text()),
        sa.Column(
            "tags", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("cleaned_text", sa.Text(), nullable=False),
        sa.Column("representative_id", sa.Text(), nullable=False),
        sa.Column("set_code", sa.Text(), nullable=False),
        sa.Column("image_path", sa.Text()),
        sa.Column("image_url", sa.Text()),
        sa.Column("printing_count", sa.Integer(), nullable=False),
        sa.Column("snapshot_fetched", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_cards_oracle_name_lower", "cards", [sa.text("lower(oracle_name)")], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_cards_oracle_name_lower", table_name="cards")
    op.drop_table("cards")
