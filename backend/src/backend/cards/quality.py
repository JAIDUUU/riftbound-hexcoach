"""Data-quality checks over collapsed Cards.

Problems the pipeline can store but a human should look at: icon shortcodes the cleaner
doesn't know, and names that would make a lookup ambiguous. The CLI prints these as
warnings after `refresh-cards` and `load-cards`.
"""

from collections.abc import Iterable, Sequence

from backend.cards.collapse import Card
from backend.cards.text import leftover_shortcodes


def unknown_shortcodes(cards: Iterable[Card]) -> dict[str, list[str]]:
    """Each icon shortcode the cleaner left in a card's text, with the cards carrying it."""
    found: dict[str, list[str]] = {}
    for card in cards:
        for shortcode in leftover_shortcodes(card.cleaned_text):
            found.setdefault(shortcode, []).append(card.oracle_name)
    return found


def ambiguous_names(cards: Iterable[Card]) -> dict[str, list[str]]:
    """Lookup keys (lowercased names and aliases) that more than one card would answer to.

    `find_by_oracle_name` matches names and aliases case-insensitively, and only the oracle
    name is unique in the database, so an alias equal to another card's name or alias makes
    that lookup ambiguous. Returns each ambiguous key with the oracle names claiming it.
    """
    claims: dict[str, set[str]] = {}
    for card in cards:
        for name in (card.oracle_name, *card.aliases):
            claims.setdefault(name.lower(), set()).add(card.oracle_name)
    return {key: sorted(names) for key, names in claims.items() if len(names) > 1}


def data_problems(cards: Sequence[Card]) -> list[str]:
    """Human-readable problem reports, in a stable order; empty when the data is clean."""
    problems = [
        f"unknown icon {shortcode} left in the text of {len(names)} card(s), e.g. {names[0]}"
        for shortcode, names in sorted(unknown_shortcodes(cards).items())
    ]
    problems += [
        f"'{key}' looks up more than one card: {', '.join(names)}"
        for key, names in sorted(ambiguous_names(cards).items())
    ]
    return problems
