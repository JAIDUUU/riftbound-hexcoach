from dataclasses import replace

from backend.cards.collapse import Card
from backend.cards.quality import ambiguous_names, data_problems, unknown_shortcodes


def test_the_sample_is_clean(cards_by_name: dict[str, Card]) -> None:
    cards = list(cards_by_name.values())

    assert unknown_shortcodes(cards) == {}
    assert ambiguous_names(cards) == {}
    assert data_problems(cards) == []


def test_an_alias_equal_to_another_cards_name_is_ambiguous_ignoring_case(
    cards_by_name: dict[str, Card], poro_claiming_sonas_name: Card
) -> None:
    collisions = ambiguous_names([poro_claiming_sonas_name, cards_by_name["Sona, Harmonious"]])

    assert collisions == {"sona, harmonious": ["Pouty Poro", "Sona, Harmonious"]}


def test_shortcodes_the_cleaner_left_behind_are_collected_per_card(
    cards_by_name: dict[str, Card],
) -> None:
    broken = replace(cards_by_name["Recruit"], cleaned_text="Gain :rb_mystery: now.")

    found = unknown_shortcodes([broken, cards_by_name["Sona, Harmonious"]])

    assert found == {":rb_mystery:": ["Recruit"]}


def test_data_problems_reports_both_kinds_in_a_stable_order(
    cards_by_name: dict[str, Card], poro_claiming_sonas_name: Card
) -> None:
    broken = replace(poro_claiming_sonas_name, cleaned_text="Gain :rb_mystery: now.")

    problems = data_problems([broken, cards_by_name["Sona, Harmonious"]])

    assert problems == [
        "unknown icon :rb_mystery: left in the text of 1 card(s), e.g. Pouty Poro",
        "'sona, harmonious' looks up more than one card: Pouty Poro, Sona, Harmonious",
    ]
