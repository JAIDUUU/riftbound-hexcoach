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


def test_between_two_faqs_the_newer_wins() -> None:
    older = hit(1, "faq", date(2025, 10, 16))
    newer = hit(2, "faq", date(2026, 4, 29))

    assert order_by_precedence([older, newer]) == [newer, older]


def test_relevance_order_is_kept_within_card_text_and_rules() -> None:
    first_rule = hit(1, "rules", date(2026, 10, 9))
    second_rule = hit(2, "rules", date(2026, 10, 9))
    first_card = hit(3, "card_text", date(2026, 11, 6))
    second_card = hit(4, "card_text", date(2026, 11, 6))

    ordered = order_by_precedence([second_rule, first_card, first_rule, second_card])

    assert [h.chunk_id for h in ordered] == [3, 4, 2, 1]


def test_unknown_source_types_sort_last() -> None:
    mystery = hit(1, "forum_post", date(2026, 1, 1))
    rules = hit(2, "rules", date(2026, 10, 9))

    assert order_by_precedence([mystery, rules]) == [rules, mystery]
