"""Answer-level scoring of the golden set: does the agent cite right and abstain right?

Pure logic (regex + set arithmetic), unit-tested without network, database or Langfuse.
The Langfuse experiment wiring that feeds it real agent runs lives in langfuse_run.py.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from backend.agent.citations import cited_rules
from backend.agent.graph import Outcome
from backend.evals.golden import Behaviour, GoldenItem


@dataclass(frozen=True, slots=True)
class AgentItemResult:
    item_id: str
    behaviour: Behaviour
    outcome: Outcome
    behaviour_correct: bool
    expected: tuple[str, ...]
    cited: tuple[str, ...]
    missing: tuple[str, ...]
    citation_score: float | None  # None for abstain items: there is nothing to cite


def evaluate_agent_item(item: GoldenItem, answer: str, outcome: Outcome) -> AgentItemResult:
    """Score one run: did the outcome match the expected behaviour, citing what's expected?

    `citation_score` is the share of expected rule ids the answer actually cites; an
    abstention scores 0.0 on an answer item (it cited nothing) and None on abstain items.
    """
    behaviour_correct = (item.behaviour == "answer") == (outcome == "answered")
    cited: set[str] = cited_rules(answer) if outcome == "answered" else set()
    expected = tuple(dict.fromkeys(item.expected_rules))
    if item.behaviour == "abstain" or not expected:
        citation_score = None
    else:
        citation_score = len(set(expected) & cited) / len(set(expected))
    return AgentItemResult(
        item_id=item.id,
        behaviour=item.behaviour,
        outcome=outcome,
        behaviour_correct=behaviour_correct,
        expected=expected,
        cited=tuple(sorted(cited)),
        missing=tuple(rule for rule in expected if rule not in cited),
        citation_score=citation_score,
    )


def aggregate_citation_score(results: Sequence[AgentItemResult]) -> float | None:
    """Mean citation score over the items that have one; None when nothing was scored
    (a golden set of only abstain items is odd but shouldn't crash a summary)."""
    scored = [r.citation_score for r in results if r.citation_score is not None]
    if not scored:
        return None
    return sum(scored) / len(scored)


def aggregate_behaviour_accuracy(results: Sequence[AgentItemResult]) -> float:
    if not results:
        raise ValueError("no results to aggregate")
    return sum(1 for r in results if r.behaviour_correct) / len(results)
