"""Fetch, store and read the committed Rifthunt card snapshot.

Everything that enters as a `RifthuntSnapshot` passes through `_validated` first: the
required top-level keys, the presence of every printing field the pipeline reads, and the
closed vocabularies. Primitive field types are trusted. This is the single boundary that
backs the TypedDicts in `backend.cards.rifthunt`.
"""

import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from backend.cards.rifthunt import RifthuntPrinting, RifthuntSnapshot
from backend.cards.vocabulary import CARD_TYPES, DOMAINS, RARITIES, SUPERTYPES

RIFTHUNT_BULK_URL = "https://api.rifthunt.com/bulk/cards"
SNAPSHOT_FILENAME = "rifthunt-snapshot.json"
CLIENT_INDEX_FILENAME = "card-index.json"

_REQUIRED_KEYS = ("cards", "fetched", "sets")
_PRINTING_KEYS = RifthuntPrinting.__required_keys__


def _missing_printing_fields(cards: list[Any]) -> list[str]:
    missing: set[str] = set()
    for card in cards:
        missing.update(_PRINTING_KEYS - card.keys())
    return sorted(missing)


def _unknown_vocabulary(cards: list[Any]) -> list[str]:
    unknown: set[str] = set()
    for card in cards:
        if card.get("type") not in CARD_TYPES:
            unknown.add(f"type {card.get('type')!r}")
        supertype = card.get("supertype")
        if supertype is not None and supertype not in SUPERTYPES:
            unknown.add(f"supertype {supertype!r}")
        if card.get("rarity") not in RARITIES:
            unknown.add(f"rarity {card.get('rarity')!r}")
        unknown.update(
            f"domain {domain!r}" for domain in card.get("domains") or () if domain not in DOMAINS
        )
    return sorted(unknown)


def _validated(data: Any) -> RifthuntSnapshot:
    missing = [key for key in _REQUIRED_KEYS if key not in data]
    if missing:
        raise ValueError(f"Unexpected Rifthunt payload, missing keys: {missing}")
    missing_fields = _missing_printing_fields(data["cards"])
    if missing_fields:
        raise ValueError(f"Snapshot cards are missing fields: {', '.join(missing_fields)}")
    unknown = _unknown_vocabulary(data["cards"])
    if unknown:
        raise ValueError(
            "Unknown card vocabulary; if Riftbound really added it, extend "
            f"backend/cards/vocabulary.py: {', '.join(unknown)}"
        )
    return cast(RifthuntSnapshot, data)


def fetch_snapshot(url: str = RIFTHUNT_BULK_URL) -> RifthuntSnapshot:
    """Download Rifthunt's bulk card data and stamp the download time as `fetched`.

    The stamp is ours, not upstream's, so the committed date is the date of this refresh.
    Only the manual refresh command calls this.
    """
    request = urllib.request.Request(url, headers={"User-Agent": "hexcoach-card-refresh"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.load(response)
    data["fetched"] = datetime.now(UTC).isoformat()
    return _validated(data)


def write_snapshot(path: Path, snapshot: RifthuntSnapshot) -> None:
    """Write the snapshot with one card per line, so refreshes produce readable git diffs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    dumps = json.dumps
    header = {key: value for key, value in snapshot.items() if key != "cards"}
    cards = sorted(snapshot["cards"], key=lambda card: (card["riftboundId"], card["printing_id"]))
    lines = ",\n".join("  " + dumps(card, ensure_ascii=False, sort_keys=True) for card in cards)
    meta = ",\n".join(
        f" {dumps(key)}: {dumps(value, ensure_ascii=False)}" for key, value in header.items()
    )
    path.write_text(f'{{\n{meta},\n "cards": [\n{lines}\n ]\n}}\n', encoding="utf-8")


def read_snapshot(path: Path) -> RifthuntSnapshot:
    return _validated(json.loads(path.read_text(encoding="utf-8")))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
