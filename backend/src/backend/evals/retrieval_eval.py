"""Retrieval-level scoring of the golden set: does search surface the expected rules?

Pure logic, so it is unit-testable without a database, network or Langfuse. The wiring
that feeds it real retrieval results and records scores lives in `langfuse_run.py`.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from backend.evals.golden import GoldenItem

Retriever = Callable[[str], Sequence[str]]
"""Takes a question, returns the rule ids of the retrieved chunks, best first."""


@dataclass(frozen=True, slots=True)
class ItemResult:
    item_id: str
    expected: tuple[str, ...]
    found: tuple[str, ...]
    missing: tuple[str, ...]
    hit_rate: float


def rule_hit_rate(expected: Sequence[str], retrieved: Sequence[str]) -> float:
    """The share of expected rule ids that retrieval surfaced (1.0 = all of them)."""
    if not expected:
        raise ValueError("hit rate needs at least one expected rule id")
    hits = set(expected) & set(retrieved)
    return len(hits) / len(set(expected))


def evaluate_item(item: GoldenItem, retrieved: Sequence[str]) -> ItemResult:
    expected = tuple(dict.fromkeys(item.expected_rules))
    found = tuple(rule_id for rule_id in expected if rule_id in set(retrieved))
    missing = tuple(rule_id for rule_id in expected if rule_id not in set(retrieved))
    return ItemResult(item.id, expected, found, missing, rule_hit_rate(expected, retrieved))


def evaluate_retrieval(items: Sequence[GoldenItem], retrieve: Retriever) -> list[ItemResult]:
    """Score every `answer` item; `abstain` items have no expected rules to retrieve."""
    return [
        evaluate_item(item, retrieve(item.question)) for item in items if item.behaviour == "answer"
    ]


def aggregate_hit_rate(results: Sequence[ItemResult]) -> float:
    if not results:
        raise ValueError("no results to aggregate")
    return sum(result.hit_rate for result in results) / len(results)
