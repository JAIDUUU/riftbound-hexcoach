"""Card tags: the `[[Card Name]]` markup the coach writes around cards (issue #15, ADR 0005).

Tags are validated once, against the finished answer, through the same CardCatalog as
decklists, so a tag counts only if it names a Card by oracle name or alias.
"""

import re
from dataclasses import dataclass

from backend.cards.catalog import CardCatalog
from backend.cards.collapse import Card

_TAG = re.compile(r"\[\[([^\[\]]+)\]\]")


@dataclass(frozen=True, slots=True)
class ValidatedCard:
    card: Card
    tags: tuple[str, ...]  # every distinct way the answer wrote it, trimmed, first seen first


def validate_card_tags(answer: str, catalog: CardCatalog) -> list[ValidatedCard]:
    """The Cards the answer tags, one entry per Card, in order of first appearance."""
    written = dict.fromkeys(tag.strip() for tag in _TAG.findall(answer))
    by_oracle_id: dict[str, tuple[Card, list[str]]] = {}
    for tag in written:
        card = catalog.find(tag)
        if card is not None:
            by_oracle_id.setdefault(card.oracle_id, (card, []))[1].append(tag)
    return [ValidatedCard(card, tuple(tags)) for card, tags in by_oracle_id.values()]
