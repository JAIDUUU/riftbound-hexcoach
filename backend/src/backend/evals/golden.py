"""Load and validate the golden set (data/golden/golden-set.yaml).

The format is documented in the file itself. Validation collects every problem before
failing, so a hand-editing session gets one complete report instead of a drip of errors.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import yaml

Behaviour = Literal["answer", "abstain"]

_RULE_ID = re.compile(r"^\d{3}(\.[0-9a-z]+)*$")
_BEHAVIOURS = ("answer", "abstain")


@dataclass(frozen=True, slots=True)
class GoldenItem:
    """One hand-written ruling with the evidence a correct answer must cite."""

    id: str
    question: str
    behaviour: Behaviour
    rulings: tuple[str, ...]
    sources: tuple[str, ...]
    lang: str
    notes: str | None


def _rulings(entry: dict[str, Any]) -> tuple[str, ...]:
    raw: object = entry.get("rulings") or []
    if not isinstance(raw, list):
        return ()
    return tuple(str(rule_id) for rule_id in cast(list[Any], raw))


def _item_problems(entry: dict[str, Any], index: int) -> list[str]:
    label = str(entry.get("id") or f"item {index + 1}")
    problems: list[str] = []
    if not entry.get("id"):
        problems.append(f"{label}: missing id")
    if not str(entry.get("question") or "").strip():
        problems.append(f"{label}: missing question")
    behaviour = entry.get("behaviour")
    if behaviour not in _BEHAVIOURS:
        problems.append(f"{label}: behaviour must be answer or abstain, got {behaviour!r}")
    if not isinstance(entry.get("rulings") or [], list):
        problems.append(f"{label}: rulings must be a list")
    rulings = _rulings(entry)
    for rule_id in rulings:
        if not _RULE_ID.match(rule_id):
            problems.append(f"{label}: {rule_id!r} is not a rule id (like 471.1, no trailing dot)")
    if behaviour == "answer" and not rulings:
        problems.append(f"{label}: an answer item needs at least one ruling")
    if behaviour == "abstain" and rulings:
        problems.append(f"{label}: an abstain item must not list rulings")
    if len(set(rulings)) != len(rulings):
        problems.append(f"{label}: duplicate rulings")
    return problems


def parse_golden(data: Any) -> list[GoldenItem]:
    raw = cast(dict[str, Any], data) if isinstance(data, dict) else {}
    entries = cast(list[dict[str, Any]], raw.get("items") or [])
    if not entries:
        raise ValueError("The golden set has no items.")
    problems: list[str] = []
    seen_ids: set[str] = set()
    items: list[GoldenItem] = []
    for index, entry in enumerate(entries):
        problems.extend(_item_problems(entry, index))
        item_id = str(entry.get("id") or "")
        if item_id in seen_ids:
            problems.append(f"{item_id}: duplicate id")
        seen_ids.add(item_id)
        items.append(
            GoldenItem(
                id=item_id,
                question=str(entry.get("question") or "").strip(),
                behaviour=cast(Behaviour, entry.get("behaviour", "answer")),
                rulings=_rulings(entry),
                sources=tuple(
                    str(source) for source in cast(list[Any], entry.get("sources") or [])
                ),
                lang=str(entry.get("lang") or "en"),
                notes=str(entry["notes"]).strip() if entry.get("notes") else None,
            )
        )
    if problems:
        raise ValueError("Malformed golden set:\n" + "\n".join(f"- {p}" for p in problems))
    return items


def load_golden_set(path: Path) -> list[GoldenItem]:
    return parse_golden(yaml.safe_load(path.read_text(encoding="utf-8")))
