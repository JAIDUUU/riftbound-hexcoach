"""The lookup_card tool (issue #10): card text comes from the database, never from memory.

The tool reads through a CardCatalog, the same matcher decklists and Card tags use, so it
is unit-testable against an in-memory catalog and the CLI and API wire in the cards
table. An unknown name returns close-name suggestions (or an explicit "nothing similar")
instead of leaving room for the model to invent card text.
"""

from langchain_core.tools import BaseTool, tool

from backend.cards.catalog import CardCatalog, close_names
from backend.cards.chunk_text import card_text_chunk


def make_lookup_card(cards: CardCatalog) -> BaseTool:
    @tool
    def lookup_card(name: str) -> str:
        """Look up a Riftbound card's current text by its English name (aliases and
        common nicknames work too). Use it whenever a ruling depends on a card's exact
        text that is not already in the evidence. Never rely on memory for card text."""
        found = cards.find(name)
        if found is not None:
            return card_text_chunk(found)
        close = close_names(name, cards.all_names())
        if close:
            return (
                f"No card named {name!r} was found. Close names: {', '.join(close)}. "
                "If one of these is the card you meant, call lookup_card again with it."
            )
        return (
            f"No card named {name!r} was found and no similar name exists. Do not invent "
            "this card's text; tell the player you do not know the card."
        )

    return lookup_card
