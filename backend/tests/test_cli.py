from datetime import date

import pytest

from backend.cards.collapse import Card
from backend.cli import format_card, format_hit, main, report_data_problems
from backend.retrieval.repository import SearchHit


def test_running_without_a_command_prints_usage_and_succeeds(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "HexCoach backend" in output
    assert "usage:" in output


def test_a_card_is_formatted_with_header_stats_and_text(cards_by_name: dict[str, Card]) -> None:
    sona = cards_by_name["Sona, Harmonious"]

    assert format_card(sona) == (
        "Sona, Harmonious [Unit] Calm\n"
        "Energy 4 Might 4 Power 1\n"
        "At the end of your turn, if I'm at a battlefield, ready up to 4 friendly runes."
    )


def test_a_card_without_text_prints_a_placeholder(cards_by_name: dict[str, Card]) -> None:
    phantom = cards_by_name["Playful Phantom"]

    assert phantom.cleaned_text == ""
    assert "(no text)" in format_card(phantom)


def test_aliases_are_listed_after_the_text(cards_by_name: dict[str, Card]) -> None:
    formatted = format_card(cards_by_name["Recruit"])

    assert formatted.endswith("Also known as: Recruit (DE), Recruit (NX), Recruit (ZN)")


def test_each_data_problem_is_printed_as_a_warning(
    cards_by_name: dict[str, Card],
    poro_claiming_sonas_name: Card,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report_data_problems([poro_claiming_sonas_name, cards_by_name["Sona, Harmonious"]])

    assert capsys.readouterr().out == (
        "warning: 'sona, harmonious' looks up more than one card: Pouty Poro, Sona, Harmonious\n"
    )


def test_clean_cards_are_reported_quietly(
    cards_by_name: dict[str, Card], capsys: pytest.CaptureFixture[str]
) -> None:
    report_data_problems(list(cards_by_name.values()))

    assert capsys.readouterr().out == ""


def test_a_search_hit_shows_rule_id_section_origin_and_first_line() -> None:
    hit = SearchHit(
        chunk_id=1,
        source_type="rules",
        rule_id="054.1",
        section="\u201cCan\u2019t beats Can\u201d",
        text="Cards that forbid actions or effects supersede cards that allow them.\n"
        "Example: not shown in the summary line.",
        source_version="2026-10-09",
        source_date=date(2026, 10, 9),
        title=None,
        source_url=None,
    )

    assert format_hit(hit) == (
        "054.1 \u00b7 \u201cCan\u2019t beats Can\u201d \u00b7 rules 2026-10-09\n"
        "  Cards that forbid actions or effects supersede cards that allow them."
    )


def test_a_faq_hit_shows_its_title_and_section() -> None:
    hit = SearchHit(
        chunk_id=2,
        source_type="faq",
        rule_id=None,
        section="Scoring",
        text="Q: How do I score?\nA: By conquering or holding.",
        source_version="OGN",
        source_date=date(2025, 10, 16),
        title="Riftbound Origins FAQ",
        source_url="https://example.com/origins-faq/",
    )

    assert format_hit(hit) == (
        "Riftbound Origins FAQ \u00b7 Scoring \u00b7 faq 2025-10-16\n  Q: How do I score?"
    )
