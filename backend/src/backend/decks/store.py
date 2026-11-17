"""Saved Decklists, always scoped to the user who owns them.

Every operation takes the owner's user id, and a deck that belongs to someone else is
indistinguishable from one that does not exist (None / False), so callers can't leak
whether another user's deck id is real. The store keeps the player's text exactly as
written: parsing and import validation run on it (decks/importing.py), never instead of it.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import ColumnElement, Connection, RowMapping, delete, func, insert, select, update

from backend.decks.schema import decks_table

MAX_DECK_NAME_CHARS = 100


@dataclass(frozen=True, slots=True)
class Deck:
    id: uuid.UUID
    name: str
    decklist: str  # the sectioned plain text, as the player wrote it
    created_at: datetime
    updated_at: datetime


class DeckStore(Protocol):
    def create(self, user_id: uuid.UUID, name: str, decklist: str) -> Deck: ...

    def list_for_user(self, user_id: uuid.UUID) -> list[Deck]:
        """The user's decks, most recently updated first."""
        ...

    def get(self, user_id: uuid.UUID, deck_id: uuid.UUID) -> Deck | None: ...

    def update(
        self, user_id: uuid.UUID, deck_id: uuid.UUID, name: str, decklist: str
    ) -> Deck | None:
        """Replace the deck's name and text; None if not the user's."""
        ...

    def delete(self, user_id: uuid.UUID, deck_id: uuid.UUID) -> bool:
        """Delete the deck; False if not the user's."""
        ...


_COLUMNS = (
    decks_table.c.id,
    decks_table.c.name,
    decks_table.c.decklist,
    decks_table.c.created_at,
    decks_table.c.updated_at,
)


def _deck(row: RowMapping) -> Deck:
    return Deck(
        id=row["id"],
        name=row["name"],
        decklist=row["decklist"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _owned(user_id: uuid.UUID, deck_id: uuid.UUID) -> ColumnElement[bool]:
    return (decks_table.c.id == deck_id) & (decks_table.c.user_id == user_id)


class SqlDeckStore:
    """DeckStore over Postgres; runs inside the caller's connection/transaction."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def create(self, user_id: uuid.UUID, name: str, decklist: str) -> Deck:
        statement = (
            insert(decks_table)
            .values(user_id=user_id, name=name, decklist=decklist)
            .returning(*_COLUMNS)
        )
        return _deck(self.connection.execute(statement).mappings().one())

    def list_for_user(self, user_id: uuid.UUID) -> list[Deck]:
        statement = (
            select(*_COLUMNS)
            .where(decks_table.c.user_id == user_id)
            .order_by(decks_table.c.updated_at.desc(), decks_table.c.id)
        )
        return [_deck(row) for row in self.connection.execute(statement).mappings()]

    def get(self, user_id: uuid.UUID, deck_id: uuid.UUID) -> Deck | None:
        statement = select(*_COLUMNS).where(_owned(user_id, deck_id))
        row = self.connection.execute(statement).mappings().first()
        return _deck(row) if row is not None else None

    def update(
        self, user_id: uuid.UUID, deck_id: uuid.UUID, name: str, decklist: str
    ) -> Deck | None:
        statement = (
            update(decks_table)
            .where(_owned(user_id, deck_id))
            .values(name=name, decklist=decklist, updated_at=func.clock_timestamp())
            .returning(*_COLUMNS)
        )
        row = self.connection.execute(statement).mappings().first()
        return _deck(row) if row is not None else None

    def delete(self, user_id: uuid.UUID, deck_id: uuid.UUID) -> bool:
        statement = delete(decks_table).where(_owned(user_id, deck_id))
        return self.connection.execute(statement).rowcount > 0
