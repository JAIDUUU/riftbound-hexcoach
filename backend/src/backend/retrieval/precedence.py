"""Source precedence for conflicting evidence (ADR 0001): FAQ > card text > rules.

Retrieval ranks by relevance; precedence is for the downstream answerer, which must know
which source wins when two chunks disagree. Between two FAQs the newer one wins, because
later FAQs supersede earlier rulings. Card text and rules keep their relevance order
within their class; their dates are edition stamps, not supersessions.
"""

from collections.abc import Sequence

from backend.retrieval.repository import SearchHit

_CLASS_ORDER = {"faq": 0, "card_text": 1, "rules": 2}


def order_by_precedence(hits: Sequence[SearchHit]) -> list[SearchHit]:
    """Stable-sort hits so that authoritative sources come first.

    FAQ chunks first (newer FAQ before older), then card text, then rules; unknown source
    types last. Within a class the incoming (relevance) order is preserved, except FAQs,
    which are ordered by date descending.
    """

    def key(indexed: tuple[int, SearchHit]) -> tuple[int, int, int]:
        index, hit = indexed
        class_rank = _CLASS_ORDER.get(hit.source_type, len(_CLASS_ORDER))
        recency = -hit.source_date.toordinal() if hit.source_type == "faq" else 0
        return (class_rank, recency, index)

    return [hit for _, hit in sorted(enumerate(hits), key=key)]
