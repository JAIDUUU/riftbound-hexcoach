"""Add title and source_url to chunks for FAQ and card-text sources.

Rules chunks leave both null; FAQ chunks carry the post title and original URL, card-text
chunks carry the card name as title.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("title", sa.Text()))
    op.add_column("chunks", sa.Column("source_url", sa.Text()))


def downgrade() -> None:
    op.drop_column("chunks", "source_url")
    op.drop_column("chunks", "title")
