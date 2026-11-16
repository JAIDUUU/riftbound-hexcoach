import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.cards.rifthunt import RifthuntPrinting, RifthuntSnapshot
from backend.cards.snapshot import (
    fetch_snapshot,
    read_snapshot,
    write_json,
    write_snapshot,
)


def _stable_identity(card: RifthuntPrinting) -> tuple[str, str]:
    return card["riftboundId"], card["printing_id"]


def test_written_snapshot_reads_back_with_nothing_lost(
    tmp_path: Path, rifthunt_sample: RifthuntSnapshot
) -> None:
    path = tmp_path / "snapshot.json"

    write_snapshot(path, rifthunt_sample)
    read_back = read_snapshot(path)

    # Cards are reordered on write so refreshes diff cleanly; the content is unchanged.
    assert sorted(read_back["cards"], key=_stable_identity) == sorted(
        rifthunt_sample["cards"], key=_stable_identity
    )
    assert {k: v for k, v in read_back.items() if k != "cards"} == {
        k: v for k, v in rifthunt_sample.items() if k != "cards"
    }


def test_snapshot_is_written_one_card_per_line_for_readable_diffs(
    tmp_path: Path, rifthunt_sample: RifthuntSnapshot
) -> None:
    path = tmp_path / "snapshot.json"

    write_snapshot(path, rifthunt_sample)

    card_lines = [line for line in path.read_text().splitlines() if line.startswith("  {")]
    assert len(card_lines) == len(rifthunt_sample["cards"])
    assert all(json.loads(line.rstrip(",")) for line in card_lines)


def test_fetch_snapshot_keeps_the_payload_and_stamps_our_download_time(
    tmp_path: Path, rifthunt_sample: RifthuntSnapshot
) -> None:
    path = tmp_path / "bulk.json"
    path.write_text(json.dumps(rifthunt_sample), encoding="utf-8")
    before = datetime.now(UTC)

    snapshot = fetch_snapshot(url=path.as_uri())

    assert snapshot["cards"] == rifthunt_sample["cards"]
    assert snapshot["sets"] == rifthunt_sample["sets"]
    # `fetched` records this download, not whatever date upstream may claim.
    assert before <= datetime.fromisoformat(snapshot["fetched"]) <= datetime.now(UTC)


def test_fetch_snapshot_rejects_an_unexpected_payload(tmp_path: Path) -> None:
    path = tmp_path / "bulk.json"
    path.write_text(json.dumps({"cards": []}), encoding="utf-8")

    with pytest.raises(ValueError, match=r"missing keys.*sets"):
        fetch_snapshot(url=path.as_uri())


def test_a_snapshot_with_an_incomplete_card_is_rejected(
    tmp_path: Path, rifthunt_sample: RifthuntSnapshot
) -> None:
    first_card = dict(rifthunt_sample["cards"][0])
    del first_card["alt"]
    del first_card["imgUrl"]
    bad = {**rifthunt_sample, "cards": [first_card]}
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(bad), encoding="utf-8")

    with pytest.raises(ValueError, match=r"missing fields: alt, imgUrl"):
        read_snapshot(path)


def test_a_snapshot_with_unknown_vocabulary_is_rejected(
    tmp_path: Path, rifthunt_sample: RifthuntSnapshot
) -> None:
    first_card = dict(rifthunt_sample["cards"][0])
    first_card["type"] = "Artifact"
    first_card["domains"] = ["Fury", "Shadow"]
    bad = {**rifthunt_sample, "cards": [first_card]}
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(bad), encoding="utf-8")

    with pytest.raises(ValueError, match=r"domain 'Shadow', type 'Artifact'"):
        read_snapshot(path)


def test_write_json_writes_compact_json_with_a_trailing_newline(tmp_path: Path) -> None:
    path = tmp_path / "index.json"

    write_json(path, {"cards": [{"name": "Recruit"}]})

    assert path.read_text(encoding="utf-8") == '{"cards":[{"name":"Recruit"}]}\n'
