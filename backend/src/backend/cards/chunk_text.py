"""What gets embedded and searched for a card: its name, type line and cleaned text.

The name is included so that both keyword and vector search find a card by name; the
type line disambiguates cards whose text alone reads alike.
"""

from backend.cards.collapse import Card


def card_text_chunk(card: Card) -> str:
    type_line = f"{card.supertype} {card.card_type}" if card.supertype else card.card_type
    return f"{card.oracle_name} ({type_line})\n{card.cleaned_text}"
