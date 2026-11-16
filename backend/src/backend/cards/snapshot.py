"""Fetch, store and read the committed Rifthunt card snapshot."""

import json
import urllib.request
from pathlib import Path
from typing import Any

from backend.cards.collapse import Snapshot

RIFTHUNT_BULK_URL = "https://api.rifthunt.com/bulk/cards"
SNAPSHOT_FILENAME = "rifthunt-snapshot.json"
CLIENT_INDEX_FILENAME = "card-index.json"

_REQUIRED_KEYS = ("cards", "fetched", "sets")


def fetch_snapshot(url: str = RIFTHUNT_BULK_URL) -> dict[str, Any]:
    """Download Rifthunt's bulk card data. Only the manual refresh script calls this."""
    request = urllib.request.Request(url, headers={"User-Agent": "hexcoach-card-refresh"})
    with urllib.request.urlopen(request, timeout=60) as response:
        snapshot: dict[str, Any] = json.load(response)
    missing = [key for key in _REQUIRED_KEYS if key not in snapshot]
    if missing:
        raise ValueError(f"Unexpected Rifthunt payload, missing keys: {missing}")
    return snapshot


def write_snapshot(path: Path, snapshot: Snapshot) -> None:
    """Write the snapshot with one card per line, so refreshes produce readable git diffs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    dumps = json.dumps
    header = {key: value for key, value in snapshot.items() if key != "cards"}
    cards = sorted(snapshot["cards"], key=lambda card: str(card["id"]))
    lines = ",\n".join("  " + dumps(card, ensure_ascii=False, sort_keys=True) for card in cards)
    meta = ",\n".join(
        f" {dumps(key)}: {dumps(value, ensure_ascii=False)}" for key, value in header.items()
    )
    path.write_text(f'{{\n{meta},\n "cards": [\n{lines}\n ]\n}}\n', encoding="utf-8")


def read_snapshot(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
