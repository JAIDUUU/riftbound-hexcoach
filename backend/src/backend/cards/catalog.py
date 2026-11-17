"""Resolving player-written card names to Cards, and suggesting fixes for the ones that miss.

One matcher for every caller: decklist import and the `lookup_card` tool both resolve by
oracle name or alias (`find_by_oracle_name`) and suggest from the same alias-aware pool
(`all_card_names`), so a suggestion is always a name that would resolve if picked.
"""

import difflib
from collections.abc import Iterable, Sequence
from typing import Protocol

from sqlalchemy import Connection

from backend.cards.collapse import Card
from backend.cards.repository import all_card_names, find_by_oracle_name

MAX_SUGGESTIONS = 3
_SIMILARITY_CUTOFF = 0.6


class CardCatalog(Protocol):
    def find(self, name: str) -> Card | None:
        """The Card answering to `name` (oracle name or alias, any case), or None."""
        ...

    def all_names(self) -> Sequence[str]:
        """Every name `find` would match: oracle names and aliases."""
        ...


class SqlCardCatalog:
    """CardCatalog over the cards table, inside the caller's connection."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def find(self, name: str) -> Card | None:
        return find_by_oracle_name(self.connection, name)

    def all_names(self) -> list[str]:
        return all_card_names(self.connection)


def close_names(name: str, candidates: Iterable[str]) -> list[str]:
    """Up to MAX_SUGGESTIONS candidates resembling `name`, best first, in their own casing."""
    by_lower = {candidate.lower(): candidate for candidate in candidates}
    close = difflib.get_close_matches(
        name.strip().lower(), list(by_lower), n=MAX_SUGGESTIONS, cutoff=_SIMILARITY_CUTOFF
    )
    return [by_lower[match] for match in close]
