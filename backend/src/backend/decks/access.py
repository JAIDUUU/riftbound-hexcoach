"""One request's decks: the player's saved Decks and the Card catalog they resolve against.

The Decks endpoints and @ mention resolution both read decks through this, so a decklist
is imported the same way wherever it is used: one the player is sending now is held to
the size cap, and one already saved is read under no cap (it was accepted under the cap
of its day, which may have been higher).
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass

from backend.cards.catalog import CardCatalog
from backend.decks.importing import DEFAULT_MAX_DECKLIST_CHARS, DeckImport, import_decklist
from backend.decks.store import Deck, DeckStore


@dataclass(frozen=True, slots=True)
class DeckAccess:
    decks: DeckStore
    cards: CardCatalog
    max_decklist_chars: int = DEFAULT_MAX_DECKLIST_CHARS

    def import_new(self, decklist: str) -> DeckImport:
        """A decklist the player is sending now, held to the size cap."""
        return import_decklist(decklist, self.cards, max_chars=self.max_decklist_chars)

    def import_saved(self, deck: Deck) -> DeckImport:
        """A deck already saved under the cap of its day, which may have been higher."""
        return import_decklist(deck.decklist, self.cards, max_chars=None)


OpenDecks = Callable[[], AbstractContextManager[DeckAccess]]
"""Opens deck access for one request; leaving the context commits (or rolls back on error)."""
