"""Which evidence an answer cites, as structured citations for the client (issue #12).

The answer prompt has the model cite rules by number and FAQs and cards by name, so a
retrieved chunk counts as cited when its rule id, or its title, appears in the answer.
A rule the model cites from memory has no chunk behind it and is left out: a citation
is something the player can open and read.
"""

import re
from collections.abc import Sequence

from backend.retrieval.precedence import order_by_precedence
from backend.retrieval.repository import SearchHit

# A rule id as answers cite them: three digits, then dotted alphanumeric segments. The
# lookarounds keep years like 2026 from matching their inner digits, while a sentence
# dot right after a citation ("per 466.2.a.") stays out of the match.
_RULE_CITATION = re.compile(r"(?<![\d.])(\d{3}(?:\.[0-9a-z]+)*)(?!\d)")


def cited_rules(answer: str) -> set[str]:
    """Every rule id the answer text cites (trailing sentence dots stripped)."""
    return {match.rstrip(".") for match in _RULE_CITATION.findall(answer)}


def cited_evidence(answer: str, hits: Sequence[SearchHit]) -> list[SearchHit]:
    """The hits the answer cites, most authoritative source first (ADR 0001)."""
    rules = cited_rules(answer)
    lowered = answer.casefold()

    def is_cited(hit: SearchHit) -> bool:
        if hit.rule_id is not None:
            return hit.rule_id in rules
        return hit.title is not None and hit.title.casefold() in lowered

    return [hit for hit in order_by_precedence(hits) if is_cited(hit)]
