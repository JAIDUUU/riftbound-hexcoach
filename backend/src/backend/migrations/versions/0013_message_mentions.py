"""Store what each player message @-mentioned.

A mention is the kind and id the player picked (`[{"kind": "card" | "deck", "id": ...}]`),
not its resolved text, so a later turn resolves it afresh: a card shows its current text,
and a deck deleted since simply drops out. Later turns of the conversation re-inject the
mentions in their history window, and a reloaded conversation shows each message's
chips. Assistant messages, and every message stored before this, mention nothing.

The column is on `messages`, so it goes with the message (and the conversation and the
account) and RLS and grants are unchanged.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("mentions", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("messages", "mentions")
