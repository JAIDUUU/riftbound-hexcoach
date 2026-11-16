from datetime import date
from pathlib import Path

import pytest

from backend.rules.parse import RuleChunk, parse_rules, rules_date, sequence_problems

FIXTURE = Path(__file__).parent.parent / "fixtures" / "core_rules_sample.txt"


@pytest.fixture(scope="module")
def sample_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def by_id(sample_text: str) -> dict[str, RuleChunk]:
    return {chunk.rule_id: chunk for chunk in parse_rules(sample_text)}


def test_every_rule_becomes_one_chunk_in_document_order(sample_text: str) -> None:
    assert [chunk.rule_id for chunk in parse_rules(sample_text)] == [
        "000",
        "001",
        "002",
        "054",
        "054.1",
        "054.2",
        "100",
        "101",
        "102",
        "103",
        "103.1",
        "103.2",
        "103.2.a",
        "103.2.b",
        "104",
    ]


def test_wrapped_lines_join_into_one_text(by_id: dict[str, RuleChunk]) -> None:
    assert by_id["002"].text == (
        "Card text supersedes rules text. Whenever a card fundamentally contradicts the rules, "
        "the card's indication is what is true."
    )


def test_examples_get_their_own_line(by_id: dict[str, RuleChunk]) -> None:
    assert by_id["103.1"].text == (
        "Cards in a player's deck may indicate additional choices to be made while building "
        "the deck.\n"
        'Example: A unit reads in part "If [Name] is in your deck, choose 3 different legends '
        'in addition to your starting legend." This decision is made while building the deck.'
    )


def test_a_page_break_mid_sentence_does_not_split_the_rule(by_id: dict[str, RuleChunk]) -> None:
    assert by_id["103.2.b"].text == (
        "If a card has more than one Domain, then that card is permitted only in a Domain "
        "Identity that contains all of the indicated Domains on that card."
    )


def test_bare_titles_are_headings_even_when_quoted(by_id: dict[str, RuleChunk]) -> None:
    assert [rule_id for rule_id, chunk in by_id.items() if chunk.is_heading] == [
        "000",
        "001",
        "054",
        "100",
        "101",
    ]
    assert not by_id["104"].is_heading  # full sentence, not a title


def test_rules_belong_to_the_nearest_preceding_heading(by_id: dict[str, RuleChunk]) -> None:
    assert by_id["002"].section == "Golden Rule"
    assert by_id["054.1"].section == "\u201cCan\u2019t beats Can\u201d"
    assert by_id["102"].section == "Deck Construction"
    assert by_id["101"].section == "Game Concepts"  # a heading sits under the previous one
    assert by_id["000"].section is None


def test_parent_ids_follow_the_dotted_numbering(by_id: dict[str, RuleChunk]) -> None:
    assert by_id["103"].parent_id is None
    assert by_id["103.2"].parent_id == "103"
    assert by_id["103.2.a"].parent_id == "103.2"


def test_the_rules_version_is_the_documents_own_date(sample_text: str) -> None:
    assert rules_date(sample_text) == date(2026, 10, 9)


def test_a_text_without_a_date_header_is_rejected() -> None:
    with pytest.raises(ValueError, match="Last Updated"):
        rules_date("001.  Golden Rule")


def _chunks(*rule_ids: str) -> list[RuleChunk]:
    return [RuleChunk(rule_id, "text.", None, None, False) for rule_id in rule_ids]


def test_a_correctly_numbered_document_has_no_problems() -> None:
    chunks = _chunks("099", "100", "100.1", "100.1.a", "100.1.b", "100.2", "101")

    assert sequence_problems(chunks) == ([], [])


def test_top_level_jumps_are_reported_as_gaps(sample_text: str) -> None:
    problems, gaps = sequence_problems(parse_rules(sample_text))

    assert problems == []
    assert gaps == ["002 -> 054", "054.2 -> 100"]


def test_a_skipped_first_child_is_a_problem() -> None:
    problems, gaps = sequence_problems(_chunks("100", "100.2"))

    assert problems == ["100 -> 100.2"]
    assert gaps == []


def test_a_skipped_letter_sibling_is_a_problem() -> None:
    problems, _ = sequence_problems(_chunks("100", "100.1", "100.1.a", "100.1.c"))

    assert problems == ["100.1.a -> 100.1.c"]


def test_out_of_order_rules_are_a_problem_not_a_gap() -> None:
    problems, gaps = sequence_problems(_chunks("101", "100"))

    assert problems == ["101 -> 100"]
    assert gaps == []
