import pytest

from backend.cards.collapse import Card
from backend.cards.tags import validate_card_tags
from tests.cards.memory_catalog import InMemoryCardCatalog


@pytest.fixture
def catalog(cards_by_name: dict[str, Card]) -> InMemoryCardCatalog:
    return InMemoryCardCatalog(cards_by_name.values())


def _found(answer: str, catalog: InMemoryCardCatalog) -> list[tuple[str, tuple[str, ...]]]:
    return [(v.card.oracle_name, v.tags) for v in validate_card_tags(answer, catalog)]


def test_tags_naming_cards_are_validated_in_the_order_they_appear(
    catalog: InMemoryCardCatalog,
) -> None:
    answer = "Yes: [[Pouty Poro]] has Deflect, so [[Blazing Scorcher]] must pay a rune."

    assert _found(answer, catalog) == [
        ("Pouty Poro", ("Pouty Poro",)),
        ("Blazing Scorcher", ("Blazing Scorcher",)),
    ]


def test_unknown_and_misspelled_tags_are_not_validated_even_when_a_close_name_exists(
    catalog: InMemoryCardCatalog,
) -> None:
    answer = "[[Pouty Poros]] and [[Blazing Scorch]] differ from [[Zhonya's Hourglass]]."

    assert _found(answer, catalog) == []


def test_a_card_tagged_again_by_alias_or_in_other_casing_is_one_entry_with_each_spelling(
    catalog: InMemoryCardCatalog,
) -> None:
    answer = (
        "[[Recruit (DE)]] tokens are [[Recruit]] units. Each [[Recruit]] is a 1-might"
        " unit, and [[ recruit ]] counts too; [[Pouty Poro]] doesn't."
    )

    assert _found(answer, catalog) == [
        ("Recruit", ("Recruit (DE)", "Recruit", "recruit")),
        ("Pouty Poro", ("Pouty Poro",)),
    ]


def test_names_with_punctuation_validate_and_malformed_markup_is_ignored(
    catalog: InMemoryCardCatalog,
) -> None:
    answer = (
        "[[Sona, Harmonious]] readies [[Bird // Bomb]]. Not tags: [Pouty Poro], [[ ]],"
        " [[Blazing [Scorcher]] and [[Playful Phantom"
    )

    assert _found(answer, catalog) == [
        ("Sona, Harmonious", ("Sona, Harmonious",)),
        ("Bird // Bomb", ("Bird // Bomb",)),
    ]
