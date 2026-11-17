"""Answer-level scoring of the golden set: does the agent cite right and abstain right?

Pure logic (regex + set arithmetic), unit-tested without network, database or Langfuse.
The Langfuse experiment wiring that feeds it real agent runs lives in langfuse_run.py.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from backend.evals.golden import GoldenItem

# A rule id as answers cite them: three digits, then dotted alphanumeric segments. The
# lookarounds keep years like 2026 from matching their inner digits, while a sentence
# dot right after a citation ("per 466.2.a.") stays out of the match.
_RULE_CITATION = re.compile(r"(?<![\d.])(\d{3}(?:\.[0-9a-z]+)*)(?!\d)")


@dataclass(frozen=True, slots=True)
class AgentItemResult:
    item_id: str
    behaviour: Literal["answer", "abstain"]
    outcome: str
    behaviour_correct: bool
    expected: tuple[str, ...]
    cited: tuple[str, ...]
    missing: tuple[str, ...]
    citation_score: float | None  # None for abstain items: there is nothing to cite


def cited_rules(answer: str) -> set[str]:
    """Every rule id the answer text cites (trailing sentence dots stripped)."""
    return {match.rstrip(".") for match in _RULE_CITATION.findall(answer)}


def evaluate_agent_item(item: GoldenItem, answer: str, outcome: str) -> AgentItemResult:
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


def aggregate_citation_score(results: Sequence[AgentItemResult]) -> float:
    scored = [r.citation_score for r in results if r.citation_score is not None]
    if not scored:
        raise ValueError("no answer items with expected rules to aggregate")
    return sum(scored) / len(scored)


def aggregate_behaviour_accuracy(results: Sequence[AgentItemResult]) -> float:
    if not results:
        raise ValueError("no results to aggregate")
    return sum(1 for r in results if r.behaviour_correct) / len(results)
