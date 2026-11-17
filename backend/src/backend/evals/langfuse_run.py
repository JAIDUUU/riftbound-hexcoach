"""Langfuse wiring for the golden set: upload the dataset and record experiment runs.

Item ids are stable, so re-uploading upserts instead of duplicating. Both experiments
(retrieval-only and full-agent) share one frame: run every scored golden item through a
task, keep the typed result locally, and hand Langfuse a JSON-friendly output dict that
the evaluators turn into per-item scores.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

from langfuse import Evaluation, Langfuse
from langfuse.api import DatasetItem

from backend.agent.graph import Outcome
from backend.config import MissingConfigError, optional_env
from backend.evals.agent_eval import (
    AgentItemResult,
    aggregate_behaviour_accuracy,
    aggregate_citation_score,
    evaluate_agent_item,
)
from backend.evals.golden import GoldenItem
from backend.evals.retrieval_eval import ItemResult, Retriever, evaluate_item

AskFunction = Callable[[str], tuple[str, Outcome]]
"""Runs the real agent on a question, returning (answer, outcome)."""

DATASET_NAME = "hexcoach-golden"

_Output = dict[str, Any]
_Evaluator = Callable[..., list[Evaluation]]


def langfuse_client() -> Langfuse:
    if optional_env("LANGFUSE_PUBLIC_KEY") is None or optional_env("LANGFUSE_SECRET_KEY") is None:
        raise MissingConfigError(
            "LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are not set (see backend/.env.example)."
        )
    return Langfuse()  # reads the LANGFUSE_* environment variables


def upload_golden_set(client: Langfuse, items: Sequence[GoldenItem]) -> None:
    client.create_dataset(
        name=DATASET_NAME,
        description="Hand-written Riftbound rulings with expected Core Rules ids.",
    )
    for item in items:
        client.create_dataset_item(
            dataset_name=DATASET_NAME,
            id=item.id,
            input={"question": item.question, "lang": item.lang},
            expected_output={
                "behaviour": item.behaviour,
                "expected_rules": list(item.expected_rules),
                "sources": list(item.sources),
            },
            metadata={"notes": item.notes} if item.notes else None,
        )


def _run_golden_experiment[R](
    client: Langfuse,
    items: Sequence[GoldenItem],
    scored: Mapping[str, GoldenItem],
    *,
    name: str,
    run_name: str,
    description: str,
    run_item: Callable[[GoldenItem], tuple[R, _Output]],
    evaluators: Sequence[_Evaluator],
    run_evaluator: Callable[[Sequence[R]], list[Evaluation]] | None = None,
) -> list[R]:
    """Run every item in `scored` through `run_item` as a Langfuse experiment.

    Results are kept locally (typed) and returned in golden-set order; the dict half of
    `run_item`'s return is what Langfuse stores as the item's output and what the
    per-item `evaluators` see. `run_evaluator` turns the typed results into run-level
    aggregate scores. max_concurrency stays 1: tasks share one DB connection and one
    provider chain.
    """
    results: dict[str, R] = {}

    def task(*, item: Any, **_: Any) -> _Output:
        if not isinstance(item, DatasetItem) or item.id not in scored:
            return {"skipped": "not scored in this experiment"}
        golden = scored[item.id]
        result, output = run_item(golden)
        results[golden.id] = result
        return output

    def aggregate(**_: Any) -> list[Evaluation]:
        if run_evaluator is None or not results:
            return []
        return run_evaluator(list(results.values()))

    dataset = client.get_dataset(DATASET_NAME)
    dataset.run_experiment(
        name=name,
        run_name=run_name,
        description=description,
        task=task,
        evaluators=list(evaluators),
        run_evaluators=[aggregate],
        max_concurrency=1,
    )
    client.flush()
    return [results[item.id] for item in items if item.id in results]


def run_experiment(
    client: Langfuse, items: Sequence[GoldenItem], retrieve: Retriever, run_name: str
) -> list[ItemResult]:
    """Run retrieval over every `answer` item in the Langfuse dataset and score it."""

    def run_item(golden: GoldenItem) -> tuple[ItemResult, _Output]:
        result = evaluate_item(golden, retrieve(golden.question))
        return result, {
            "found": list(result.found),
            "missing": list(result.missing),
            "rule_hit_rate": result.hit_rate,
        }

    def hit_rate(*, output: Any, **_: Any) -> list[Evaluation]:
        if not isinstance(output, dict):
            return []
        value = cast(dict[str, Any], output).get("rule_hit_rate")
        if not isinstance(value, float):
            return []
        return [Evaluation(name="rule_hit_rate", value=value)]

    return _run_golden_experiment(
        client,
        items,
        {item.id: item for item in items if item.behaviour == "answer"},
        name="retrieval",
        run_name=run_name,
        description="Share of expected Core Rules ids surfaced by keyword search.",
        run_item=run_item,
        evaluators=[hit_rate],
    )


def run_agent_experiment(
    client: Langfuse, items: Sequence[GoldenItem], ask: AskFunction, run_name: str
) -> list[AgentItemResult]:
    """Run the real agent over every golden item and score answers and abstentions."""

    def run_item(golden: GoldenItem) -> tuple[AgentItemResult, _Output]:
        answer, outcome = ask(golden.question)
        result = evaluate_agent_item(golden, answer, outcome)
        return result, {
            "answer": answer,
            "outcome": outcome,
            "behaviour_correct": result.behaviour_correct,
            "cited": list(result.cited),
            "missing": list(result.missing),
            "citation_score": result.citation_score,
        }

    def behaviour(*, output: Any, **_: Any) -> list[Evaluation]:
        if not isinstance(output, dict) or "behaviour_correct" not in output:
            return []
        correct = cast(dict[str, Any], output)["behaviour_correct"]
        return [Evaluation(name="behaviour_correct", value=bool(correct), data_type="BOOLEAN")]

    def citation(*, output: Any, **_: Any) -> list[Evaluation]:
        if not isinstance(output, dict):
            return []
        score = cast(dict[str, Any], output).get("citation_score")
        if not isinstance(score, int | float):
            return []
        return [Evaluation(name="citation_score", value=float(score))]

    def aggregates(results: Sequence[AgentItemResult]) -> list[Evaluation]:
        scores = [
            Evaluation(name="behaviour_accuracy", value=aggregate_behaviour_accuracy(results))
        ]
        citation_avg = aggregate_citation_score(results)
        if citation_avg is not None:
            scores.append(Evaluation(name="citation_score_avg", value=citation_avg))
        return scores

    return _run_golden_experiment(
        client,
        items,
        {item.id: item for item in items},
        name="agent",
        run_name=run_name,
        description="Full agent runs: citation match and abstain correctness.",
        run_item=run_item,
        evaluators=[behaviour, citation],
        run_evaluator=aggregates,
    )
