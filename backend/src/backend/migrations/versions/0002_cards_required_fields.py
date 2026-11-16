"""Make rarity and image_url required, matching the Card domain model.

Every printing in the Rifthunt bulk data carries both, and sync always writes them.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("cards", "rarity", existing_type=sa.Text(), nullable=False)
    op.alter_column("cards", "image_url", existing_type=sa.Text(), nullable=False)


def downgrade() -> None:
    op.alter_column("cards", "image_url", existing_type=sa.Text(), nullable=True)
    op.alter_column("cards", "rarity", existing_type=sa.Text(), nullable=True)
