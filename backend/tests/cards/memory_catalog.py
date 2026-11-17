"""An in-memory CardCatalog for DB-free tests.

test_catalog_contract.py holds this and SqlCardCatalog to the same matching rules (oracle
name or alias, ignoring case, the oracle name winning a clash).
"""

import uuid
from collections.abc import Iterable

from backend.cards.collapse import Card


class InMemoryCardCatalog:
    def __init__(self, cards: Iterable[Card]) -> None:
        self.cards = list(cards)

    def find(self, name: str) -> Card | None:
        key = name.strip().lower()
        by_oracle_name = [card for card in self.cards if card.oracle_name.lower() == key]
        by_alias = [
            card for card in self.cards if any(alias.lower() == key for alias in card.aliases)
        ]
        return next(iter(by_oracle_name + by_alias), None)

    def find_by_id(self, oracle_id: uuid.UUID) -> Card | None:
        return next((card for card in self.cards if uuid.UUID(card.oracle_id) == oracle_id), None)

    def all_names(self) -> list[str]:
        names = {card.oracle_name for card in self.cards}
        return sorted(names.union(*(card.aliases for card in self.cards)))
