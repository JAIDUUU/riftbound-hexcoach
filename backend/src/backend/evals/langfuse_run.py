"""Langfuse wiring for the golden set: upload the dataset and record an experiment run.

Item ids are stable, so re-uploading upserts instead of duplicating. Experiment runs go
through `dataset.run_experiment`, which traces one run per item and attaches the
`rule_hit_rate` score; abstain items are uploaded for later answer-level evals but are
skipped here because they expect no retrieved rules.
"""

from collections.abc import Sequence
from typing import Any, cast

from langfuse import Evaluation, Langfuse
from langfuse.api import DatasetItem

from backend.config import MissingConfigError, optional_env
from backend.evals.golden import GoldenItem
from backend.evals.retrieval_eval import ItemResult, Retriever, evaluate_item

DATASET_NAME = "hexcoach-golden"


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
                "rulings": list(item.rulings),
                "sources": list(item.sources),
            },
            metadata={"notes": item.notes} if item.notes else None,
        )


def run_experiment(
    client: Langfuse, items: Sequence[GoldenItem], retrieve: Retriever, run_name: str
) -> list[ItemResult]:
    """Run retrieval over every `answer` item in the Langfuse dataset and score it."""
    by_id = {item.id: item for item in items if item.behaviour == "answer"}
    results: dict[str, ItemResult] = {}

    def task(*, item: Any, **_: Any) -> dict[str, Any]:
        if not isinstance(item, DatasetItem) or item.id not in by_id:
            return {"skipped": "abstain item or not in the local golden set"}
        golden = by_id[item.id]
        result = evaluate_item(golden, retrieve(golden.question))
        results[golden.id] = result
        return {
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

    dataset = client.get_dataset(DATASET_NAME)
    dataset.run_experiment(
        name="retrieval",
        run_name=run_name,
        description="Share of expected Core Rules ids surfaced by keyword search.",
        task=task,
        evaluators=[hit_rate],
        max_concurrency=1,  # retrieval shares one DB connection
    )
    client.flush()
    return [results[item.id] for item in items if item.id in results]
