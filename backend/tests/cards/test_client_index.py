import json

from backend.cards.client_index import build_client_index
from backend.cards.collapse import collapse_printings
from backend.cards.rifthunt import RifthuntSnapshot


def test_client_index_lists_each_card_with_what_the_at_menu_needs(
    rifthunt_sample: RifthuntSnapshot,
) -> None:
    index = build_client_index(collapse_printings(rifthunt_sample))

    assert index["fetched"] == "2026-11-06T21:03:32.635000+00:00"
    assert [entry["name"] for entry in index["cards"]] == [
        "Annie, Dark Child",
        "Bird // Bomb",
        "Blazing Scorcher",
        "Fury Rune",
        "Playful Phantom",
        "Pouty Poro",
        "Recruit",
        "Sona, Harmonious",
    ]
    scorcher = next(entry for entry in index["cards"] if entry["name"] == "Blazing Scorcher")
    assert scorcher == {
        "id": "f2c16cd8-01a4-4357-b741-34db22446e15",
        "name": "Blazing Scorcher",
        "aliases": [],
        "type": "Unit",
        "domains": ["Fury"],
        "image": "cards/ogn-001-298.png",
    }


def test_client_index_is_plain_json(rifthunt_sample: RifthuntSnapshot) -> None:
    index = build_client_index(collapse_printings(rifthunt_sample))

    assert json.loads(json.dumps(index)) == index
