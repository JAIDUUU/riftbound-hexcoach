"""An in-memory DeckStore for DB-free API tests.

test_deck_store_contract.py runs the same ownership rules against this and the real
SqlDeckStore, so API tests built on this fake can't drift from production.
"""

import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from backend.api.app import DeckAccess
from backend.decks.store import Deck
from tests.cards.memory_catalog import InMemoryCardCatalog

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass
class _Row:
    owner: uuid.UUID
    deck: Deck


class InMemoryDeckStore:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, _Row] = {}
        self._ticks = 0

    def _now(self) -> datetime:
        self._ticks += 1  # strictly increasing, so ordering never ties
        return _EPOCH + timedelta(microseconds=self._ticks)

    def _owned(self, user_id: uuid.UUID, deck_id: uuid.UUID) -> _Row | None:
        row = self.rows.get(deck_id)
        return row if row is not None and row.owner == user_id else None

    def create(self, user_id: uuid.UUID, name: str, decklist: str) -> Deck:
        now = self._now()
        deck = Deck(id=uuid.uuid4(), name=name, decklist=decklist, created_at=now, updated_at=now)
        self.rows[deck.id] = _Row(owner=user_id, deck=deck)
        return deck

    def list_for_user(self, user_id: uuid.UUID) -> list[Deck]:
        mine = [row.deck for row in self.rows.values() if row.owner == user_id]
        return sorted(mine, key=lambda deck: deck.updated_at, reverse=True)

    def get(self, user_id: uuid.UUID, deck_id: uuid.UUID) -> Deck | None:
        row = self._owned(user_id, deck_id)
        return row.deck if row is not None else None

    def update(
        self, user_id: uuid.UUID, deck_id: uuid.UUID, name: str, decklist: str
    ) -> Deck | None:
        row = self._owned(user_id, deck_id)
        if row is None:
            return None
        row.deck = replace(row.deck, name=name, decklist=decklist, updated_at=self._now())
        return row.deck

    def delete(self, user_id: uuid.UUID, deck_id: uuid.UUID) -> bool:
        if self._owned(user_id, deck_id) is None:
            return False
        del self.rows[deck_id]
        return True


@contextmanager
def no_decks() -> Generator[DeckAccess]:
    """Deck access for API tests that never touch decks."""
    yield DeckAccess(InMemoryDeckStore(), InMemoryCardCatalog([]))
