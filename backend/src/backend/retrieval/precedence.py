"""Source precedence for conflicting evidence (ADR 0001): FAQ > card text > rules.

Retrieval ranks by relevance; precedence is for the downstream answerer, which must know
which source wins when two chunks disagree. Within each class the relevance order is
preserved — supersession ("between two FAQs the newer wins") only applies when two FAQs
actually conflict, which is a judgment the answerer makes with the dates on the hits;
re-sorting all FAQs by date here would bury an older but highly relevant ruling.
"""

from collections.abc import Sequence

from backend.retrieval.repository import SearchHit, SourceType

_CLASS_ORDER: dict[SourceType, int] = {"faq": 0, "card_text": 1, "rules": 2}


def order_by_precedence(hits: Sequence[SearchHit]) -> list[SearchHit]:
    """Stable-sort hits so that authoritative source classes come first.

    FAQ chunks first, then card text, then rules. The incoming (relevance) order is
    preserved within each class.
    """
    return sorted(hits, key=lambda hit: _CLASS_ORDER[hit.source_type])
