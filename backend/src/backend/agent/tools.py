"""The lookup_card tool (issue #10): card text comes from the database, never from memory.

Data access is injected as two callables, so the tool is unit-testable against a fake
card store; the CLI wires in the cards table. An unknown name returns close-name
suggestions (or an explicit "nothing similar") instead of leaving room for the model to
invent card text.
"""

from collections.abc import Callable, Sequence

from langchain_core.tools import BaseTool, tool

from backend.cards.catalog import close_names

FindCard = Callable[[str], str | None]
"""Formatted card text (name, type line, cleaned text) by name or alias, or None."""

AllCardNames = Callable[[], Sequence[str]]
"""Every name a lookup would match (oracle names and aliases), for suggestions."""


def make_lookup_card(find_card: FindCard, all_card_names: AllCardNames) -> BaseTool:
    @tool
    def lookup_card(name: str) -> str:
        """Look up a Riftbound card's current text by its English name (aliases and
        common nicknames work too). Use it whenever a ruling depends on a card's exact
        text that is not already in the evidence. Never rely on memory for card text."""
        found = find_card(name)
        if found is not None:
            return found
        close = close_names(name, all_card_names())
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
