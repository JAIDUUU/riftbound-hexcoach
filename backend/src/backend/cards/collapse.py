"""Collapse Rifthunt printings into one Card per oracle id."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.cards.text import clean_card_text

type Printing = Mapping[str, Any]
type Snapshot = Mapping[str, Any]

# Rifthunt marks third-party printings only through the prefix of its legacy `id` field.
# This is the one place that field is read; identity everywhere else is `riftboundId`.
_THIRD_PARTY_ID_PREFIXES = ("tcg:", "dotgg:")


@dataclass(frozen=True, slots=True)
class Card:
    """A distinct Riftbound card, identified by its oracle id.

    Text and stats come from one representative printing; see `collapse_printings`.
    """

    oracle_id: str
    oracle_name: str
    aliases: tuple[str, ...]
    card_type: str
    supertype: str | None
    domains: tuple[str, ...]
    energy: int | None
    might: int | None
    power: int | None
    rarity: str | None
    tags: tuple[str, ...]
    raw_text: str
    cleaned_text: str
    representative_id: str
    set_code: str
    image_path: str | None
    image_url: str | None
    printing_count: int
    snapshot_fetched: datetime


def _is_plain(printing: Printing) -> bool:
    """A plain printing is not alternate art, signature or overnumbered, and has no name suffix."""
    return not (
        printing.get("alt")
        or printing.get("sig")
        or printing.get("over")
        or printing["name"] != printing["cleanName"]
    )


def _is_official(printing: Printing) -> bool:
    return not str(printing["id"]).startswith(_THIRD_PARTY_ID_PREFIXES)


def _stable_order(printing: Printing) -> tuple[str, str]:
    return str(printing["riftboundId"]), str(printing["printing_id"])


def _representative(printings: Iterable[Printing], released: Mapping[str, str]) -> Printing:
    """Pick the printing whose text and stats define the card.

    Preference: plain over variant, official id over third-party id, then the latest set
    release (newest wording). Ties go to the lowest riftboundId so the result is deterministic.
    """
    ordered = sorted(printings, key=_stable_order)
    return max(
        ordered,
        key=lambda printing: (
            _is_plain(printing),
            _is_official(printing),
            released.get(printing["set"], ""),
        ),
    )


def _to_card(printings: list[Printing], released: Mapping[str, str], fetched: datetime) -> Card:
    chosen = _representative(printings, released)
    oracle_name = str(chosen["cleanName"])
    raw_text = chosen.get("text") or ""
    other_names = {str(printing["cleanName"]) for printing in printings} - {oracle_name}
    return Card(
        oracle_id=str(chosen["oracle_id"]),
        oracle_name=oracle_name,
        aliases=tuple(sorted(other_names)),
        card_type=str(chosen["type"]),
        supertype=chosen.get("supertype"),
        domains=tuple(chosen.get("domains") or ()),
        energy=chosen.get("energy"),
        might=chosen.get("might"),
        power=chosen.get("power"),
        rarity=chosen.get("rarity"),
        tags=tuple(chosen.get("tags") or ()),
        raw_text=raw_text,
        cleaned_text=clean_card_text(raw_text),
        representative_id=str(chosen["riftboundId"]),
        set_code=str(chosen["set"]),
        image_path=chosen.get("img"),
        image_url=chosen.get("imgUrl"),
        printing_count=len(printings),
        snapshot_fetched=fetched,
    )


def collapse_printings(snapshot: Snapshot) -> list[Card]:
    """Turn a Rifthunt bulk snapshot into one Card per oracle id, sorted by oracle name."""
    released = {str(entry["id"]): str(entry["released"]) for entry in snapshot["sets"]}
    fetched = datetime.fromisoformat(snapshot["fetched"])
    by_oracle_id: dict[str, list[Printing]] = {}
    for printing in snapshot["cards"]:
        by_oracle_id.setdefault(printing["oracle_id"], []).append(printing)
    cards = (_to_card(group, released, fetched) for group in by_oracle_id.values())
    return sorted(cards, key=lambda card: card.oracle_name)
