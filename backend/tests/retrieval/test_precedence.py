from datetime import date

from backend.retrieval.precedence import order_by_precedence
from backend.retrieval.repository import SearchHit


def hit(chunk_id: int, source_type: str, source_date: date) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        source_type=source_type,
        rule_id=None,
        section=None,
        text=f"chunk {chunk_id}",
        source_version="v",
        source_date=source_date,
        title=None,
        source_url=None,
    )


def test_faq_beats_card_text_beats_rules() -> None:
    rules = hit(1, "rules", date(2026, 10, 9))
    card = hit(2, "card_text", date(2026, 11, 6))
    faq = hit(3, "faq", date(2025, 10, 16))

    ordered = order_by_precedence([rules, card, faq])

    assert [h.source_type for h in ordered] == ["faq", "card_text", "rules"]


def test_relevance_order_is_kept_within_each_class() -> None:
    # An older FAQ that ranked higher on relevance stays ahead: supersession only
    # applies to actual conflicts, which the answerer judges using the hits' dates.
    relevant_old_faq = hit(1, "faq", date(2025, 10, 16))
    newer_faq = hit(2, "faq", date(2026, 4, 29))
    first_rule = hit(3, "rules", date(2026, 10, 9))
    second_rule = hit(4, "rules", date(2026, 10, 9))
    card = hit(5, "card_text", date(2026, 11, 6))

    ordered = order_by_precedence([second_rule, relevant_old_faq, card, first_rule, newer_faq])

    assert [h.chunk_id for h in ordered] == [1, 2, 5, 4, 3]


def test_unknown_source_types_sort_last() -> None:
    mystery = hit(1, "forum_post", date(2026, 1, 1))
    rules = hit(2, "rules", date(2026, 10, 9))

    assert order_by_precedence([mystery, rules]) == [rules, mystery]
