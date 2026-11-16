from typing import Any

import pytest

from backend.config import GOLDEN_SET_PATH
from backend.evals.golden import load_golden_set, parse_golden


def _entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": "q01",
        "question": "Can I?",
        "behaviour": "answer",
        "expected_rules": ["471.1"],
    }
    entry.update(overrides)
    return entry


def test_the_committed_golden_set_is_valid() -> None:
    items = load_golden_set(GOLDEN_SET_PATH)

    assert len(items) >= 7
    assert {item.behaviour for item in items} == {"answer", "abstain"}
    assert any(item.lang != "en" for item in items)  # the set keeps non-English questions


def test_a_valid_item_parses_with_defaults() -> None:
    (item,) = parse_golden({"items": [_entry(notes="  watch the timing  ")]})

    assert item.id == "q01"
    assert item.expected_rules == ("471.1",)
    assert item.sources == ()
    assert item.lang == "en"
    assert item.notes == "watch the timing"


def test_an_answer_item_without_expected_rules_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one expected rule"):
        parse_golden({"items": [_entry(expected_rules=[])]})


def test_an_abstain_item_with_expected_rules_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not list expected rules"):
        parse_golden({"items": [_entry(behaviour="abstain")]})


def test_rule_ids_with_trailing_dots_are_rejected() -> None:
    with pytest.raises(ValueError, match=r"'471\.1\.' is not a rule id"):
        parse_golden({"items": [_entry(expected_rules=["471.1."])]})


def test_duplicate_ids_and_expected_rules_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate id"):
        parse_golden({"items": [_entry(), _entry()]})
    with pytest.raises(ValueError, match="duplicate expected rules"):
        parse_golden({"items": [_entry(expected_rules=["471.1", "471.1"])]})


def test_unknown_behaviour_and_missing_question_are_rejected_together() -> None:
    with pytest.raises(ValueError) as caught:
        parse_golden({"items": [_entry(behaviour="guess", question=" ")]})

    message = str(caught.value)
    assert "behaviour must be answer or abstain" in message
    assert "missing question" in message


def test_an_empty_file_is_rejected() -> None:
    with pytest.raises(ValueError, match="no items"):
        parse_golden(None)
