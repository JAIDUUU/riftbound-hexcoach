"""Deck-construction numbers for import validation's structural checks.

UNVERIFIED. Grill Decisions lists the deck-construction numbers as not yet checked
against the official rules, so treat every default here as a placeholder until a human
confirms it. They were read from the committed documents for the constructed format:
Core Rules 103 (1 Champion Legend, 1 Chosen Champion, a Main Deck of at least 40 cards
counting the Chosen Champion, up to 3 copies of a named card, 12 runes, battlefields
with unique names) and Tournament Rules 402.1/601.1 (a Main Deck of exactly 40, exactly
3 battlefields, a sideboard of 10 or fewer, copy limits spanning Main Deck and
sideboard). Casual play may differ; the checks only ever warn.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeckRules:
    legend_cards: int = 1  # UNVERIFIED: exactly this many in Legend
    champion_cards: int = 1  # UNVERIFIED: exactly this many in Champion
    main_deck_cards: int = 40  # UNVERIFIED: exactly this many in MainDeck plus Champion
    battlefield_cards: int = 3  # UNVERIFIED: exactly this many in Battlefields
    rune_cards: int = 12  # UNVERIFIED: exactly this many in Runes
    max_sideboard_cards: int = 10  # UNVERIFIED: at most this many in Sideboard
    max_copies: int = 3  # UNVERIFIED: per card across Champion, MainDeck and Sideboard
    max_battlefield_copies: int = 1  # UNVERIFIED: per battlefield name


CONSTRUCTED = DeckRules()
