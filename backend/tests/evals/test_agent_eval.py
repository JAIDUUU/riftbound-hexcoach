import pytest

from backend.evals.agent_eval import (
    aggregate_behaviour_accuracy,
    aggregate_citation_score,
    cited_rules,
    evaluate_agent_item,
)
from backend.evals.golden import GoldenItem


def _item(behaviour: str, expected_rules: tuple[str, ...]) -> GoldenItem:
    return GoldenItem(
        id="q",
        question="Can I?",
        behaviour=behaviour,  # type: ignore[arg-type]
        expected_rules=expected_rules,
        sources=(),
        lang="en",
        notes=None,
    )


def test_cited_rules_finds_dotted_ids_and_strips_sentence_dots() -> None:
    answer = (
        "No - rule 472 says once per turn. Per 466.2.a. and rule 467.2.c.3, "
        "the trigger resolves first."
    )

    assert cited_rules(answer) == {"472", "466.2.a", "467.2.c.3"}


def test_years_dates_and_short_numbers_are_not_citations() -> None:
    answer = "As of the 2026-10-09 rules, with 4 might and 12 damage, see rule 472."

    assert cited_rules(answer) == {"472"}


def test_a_correct_answer_scores_full_citations() -> None:
    result = evaluate_agent_item(
        _item("answer", ("472", "470.2")), "See 472 and 470.2.", "answered"
    )

    assert result.behaviour_correct
    assert result.citation_score == 1.0
    assert result.missing == ()


def test_missing_citations_lower_the_score_and_are_named() -> None:
    result = evaluate_agent_item(_item("answer", ("472", "470.2")), "See rule 472.", "answered")

    assert result.citation_score == 0.5
    assert result.missing == ("470.2",)


def test_an_answer_item_that_abstains_is_wrong_and_scores_zero_citations() -> None:
    result = evaluate_agent_item(_item("answer", ("472",)), "Which Diana?", "abstained")

    assert not result.behaviour_correct
    assert result.citation_score == 0.0


def test_an_abstain_item_that_abstains_is_correct_with_no_citation_score() -> None:
    result = evaluate_agent_item(_item("abstain", ()), "Which Diana do you mean?", "abstained")

    assert result.behaviour_correct
    assert result.citation_score is None


def test_an_abstain_item_that_answers_is_wrong() -> None:
    result = evaluate_agent_item(_item("abstain", ()), "Sure, rule 472.", "answered")

    assert not result.behaviour_correct


def test_aggregates_cover_behaviour_and_citations() -> None:
    results = [
        evaluate_agent_item(_item("answer", ("472",)), "rule 472.", "answered"),
        evaluate_agent_item(_item("answer", ("470.2",)), "no idea", "answered"),
        evaluate_agent_item(_item("abstain", ()), "Which Diana?", "abstained"),
    ]

    assert aggregate_behaviour_accuracy(results) == 1.0
    assert aggregate_citation_score(results) == 0.5  # (1.0 + 0.0) / 2 answer items


def test_aggregating_nothing_is_an_error() -> None:
    with pytest.raises(ValueError, match="no results"):
        aggregate_behaviour_accuracy([])
    with pytest.raises(ValueError, match="no answer items"):
        aggregate_citation_score([])
