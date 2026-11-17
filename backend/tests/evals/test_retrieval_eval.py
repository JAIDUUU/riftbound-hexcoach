import pytest

from backend.evals.golden import Behaviour, GoldenItem
from backend.evals.retrieval_eval import (
    aggregate_hit_rate,
    evaluate_retrieval,
    rule_hit_rate,
)


def _item(item_id: str, behaviour: Behaviour, expected_rules: tuple[str, ...]) -> GoldenItem:
    return GoldenItem(
        id=item_id,
        question=f"question {item_id}",
        behaviour=behaviour,
        expected_rules=expected_rules,
        sources=(),
        lang="en",
        notes=None,
    )


def test_hit_rate_is_the_share_of_expected_rules_found() -> None:
    assert rule_hit_rate(["471.1", "472"], ["472", "100", "469"]) == 0.5
    assert rule_hit_rate(["471.1"], ["471.1"]) == 1.0
    assert rule_hit_rate(["471.1"], []) == 0.0


def test_hit_rate_without_expectations_is_an_error() -> None:
    with pytest.raises(ValueError, match="at least one"):
        rule_hit_rate([], ["471.1"])


def test_only_answer_items_are_evaluated_and_misses_are_named() -> None:
    items = [
        _item("q1", "answer", ("471.1", "472")),
        _item("q2", "abstain", ()),
    ]
    retrieved = {"question q1": ["471.1", "059"]}

    results = evaluate_retrieval(items, lambda question: retrieved[question])

    assert [result.item_id for result in results] == ["q1"]
    assert results[0].found == ("471.1",)
    assert results[0].missing == ("472",)
    assert results[0].hit_rate == 0.5


def test_aggregate_is_the_mean_over_items() -> None:
    items = [_item("q1", "answer", ("471.1",)), _item("q2", "answer", ("472",))]

    results = evaluate_retrieval(items, lambda question: ["471.1"])

    assert aggregate_hit_rate(results) == 0.5


def test_aggregating_nothing_is_an_error() -> None:
    with pytest.raises(ValueError, match="no results"):
        aggregate_hit_rate([])
