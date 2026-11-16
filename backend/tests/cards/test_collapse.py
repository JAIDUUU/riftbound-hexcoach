from datetime import UTC, datetime

from backend.cards.collapse import Card
from backend.cards.rifthunt import RifthuntSnapshot


def test_printings_collapse_to_one_card_per_oracle_id(cards_by_name: dict[str, Card]) -> None:
    assert sorted(cards_by_name) == [
        "Annie, Dark Child",
        "Bird // Bomb",
        "Blazing Scorcher",
        "Fury Rune",
        "Playful Phantom",
        "Pouty Poro",
        "Recruit",
        "Sona, Harmonious",
    ]
    assert cards_by_name["Fury Rune"].printing_count == 16


def test_text_comes_from_the_latest_released_plain_printing(
    cards_by_name: dict[str, Card],
) -> None:
    sona = cards_by_name["Sona, Harmonious"]

    assert sona.representative_id == "ven-sp2-006"
    assert sona.cleaned_text == (
        "At the end of your turn, if I'm at a battlefield, ready up to 4 friendly runes."
    )


def test_latest_release_wins_among_plain_printings_of_the_same_card(
    cards_by_name: dict[str, Card],
) -> None:
    assert cards_by_name["Fury Rune"].representative_id == "rad-r01"


def test_alternate_and_overnumbered_printings_never_supply_the_card(
    cards_by_name: dict[str, Card],
) -> None:
    poro = cards_by_name["Pouty Poro"]

    assert poro.representative_id == "ogn-013-298"
    assert poro.cleaned_text == (
        "Deflect (Opponents must pay Rainbow Rune to choose me with a spell or ability.)"
    )


def test_a_card_known_only_by_third_party_printings_falls_back_to_a_plain_one(
    cards_by_name: dict[str, Card],
) -> None:
    annie = cards_by_name["Annie, Dark Child"]

    assert annie.representative_id == "opp-017-024"


def test_other_names_sharing_an_oracle_id_become_aliases(cards_by_name: dict[str, Card]) -> None:
    recruit = cards_by_name["Recruit"]

    assert recruit.aliases == ("Recruit (DE)", "Recruit (NX)", "Recruit (ZN)")
    assert cards_by_name["Sona, Harmonious"].aliases == ()


def test_missing_text_yields_empty_raw_and_cleaned_text(cards_by_name: dict[str, Card]) -> None:
    phantom = cards_by_name["Playful Phantom"]

    assert phantom.raw_text == ""
    assert phantom.cleaned_text == ""


def test_raw_text_is_kept_next_to_the_cleaned_text(cards_by_name: dict[str, Card]) -> None:
    scorcher = cards_by_name["Blazing Scorcher"]

    assert scorcher.raw_text.startswith("[Accelerate] (You may pay :rb_energy_1::rb_rune_fury:")
    assert scorcher.cleaned_text.startswith("Accelerate (You may pay 1 Energy Fury Rune")


def test_card_carries_image_path_and_snapshot_date(
    cards_by_name: dict[str, Card], rifthunt_sample: RifthuntSnapshot
) -> None:
    scorcher = cards_by_name["Blazing Scorcher"]

    assert scorcher.image_path == "cards/ogn-001-298.png"
    assert scorcher.snapshot_fetched == datetime(2026, 11, 6, 21, 3, 32, 635000, tzinfo=UTC)
    assert rifthunt_sample["fetched"] == "2026-11-06T21:03:32.635Z"


def test_a_card_with_a_single_third_party_printing_is_still_a_card(
    cards_by_name: dict[str, Card],
) -> None:
    assert cards_by_name["Bird // Bomb"].representative_id == "rad-t01"
