import pytest

from backend.cards.collapse import Card
from backend.decks.construction import DeckRules
from backend.decks.importing import import_decklist
from backend.decks.warnings import DeckWarning
from tests.cards.memory_catalog import InMemoryCardCatalog


@pytest.fixture
def catalog(cards_by_name: dict[str, Card]) -> InMemoryCardCatalog:
    return InMemoryCardCatalog(cards_by_name.values())


def _kind(warnings: tuple[DeckWarning, ...], kind: str) -> list[DeckWarning]:
    return [warning for warning in warnings if warning.kind == kind]


def test_each_line_resolves_to_its_card_by_oracle_name_or_alias_ignoring_case(
    catalog: InMemoryCardCatalog,
) -> None:
    imported = import_decklist("MainDeck:\n3 pouty poro\n2 Recruit (NX)\n", catalog)

    assert [(line.line.name, line.card and line.card.oracle_name) for line in imported.lines] == [
        ("pouty poro", "Pouty Poro"),
        ("Recruit (NX)", "Recruit"),
    ]
    assert _kind(imported.warnings, "unknown_card") == []


def test_an_unknown_name_gets_close_suggestions_including_aliases(
    catalog: InMemoryCardCatalog,
) -> None:
    imported = import_decklist("MainDeck:\n3 Pouty Porro\n1 Recruit (NZ)\n", catalog)

    poro, recruit = imported.lines
    assert poro.card is None
    assert poro.suggestions == ("Pouty Poro",)
    assert recruit.card is None
    assert "Recruit (NX)" in recruit.suggestions  # an alias: picking it would resolve
    assert _kind(imported.warnings, "unknown_card") == [
        DeckWarning(
            "unknown_card", "Line 2: no card named 'Pouty Porro'. Did you mean Pouty Poro?", 2
        ),
        DeckWarning(
            "unknown_card",
            f"Line 3: no card named 'Recruit (NZ)'. Did you mean {', '.join(recruit.suggestions)}?",
            3,
        ),
    ]


def test_a_name_unlike_any_card_says_there_is_nothing_similar(
    catalog: InMemoryCardCatalog,
) -> None:
    imported = import_decklist("MainDeck:\n1 Xyzzyplugh\n", catalog)

    assert imported.lines[0].suggestions == ()
    assert _kind(imported.warnings, "unknown_card") == [
        DeckWarning(
            "unknown_card", "Line 2: no card named 'Xyzzyplugh', and no similar name exists.", 2
        )
    ]


def test_parse_warnings_come_through_the_import(catalog: InMemoryCardCatalog) -> None:
    imported = import_decklist("3 Pouty Poro\n", catalog)

    assert [warning.kind for warning in imported.warnings][:1] == ["outside_section"]


def _structural(warnings: tuple[DeckWarning, ...]) -> list[str]:
    return [w.message for w in warnings if w.kind in ("section_size", "copy_limit")]


def _constructed_deck() -> str:
    """A deck built to the constructed numbers in the Core and Tournament Rules: 1 Legend,
    a 40-card Main Deck counting the Champion, 3 unique Battlefields, 12 Runes and a
    10-card Sideboard, no name over 3 copies."""
    main = "\n".join(f"3 Main Card {n}" for n in range(13))  # 39, plus the Champion
    side = "\n".join(["3 Side Card A", "3 Side Card B", "3 Side Card C", "1 Side Card D"])
    return (
        "Legend:\n1 Annie, Dark Child\nChampion:\n1 Sona, Harmonious\n"
        f"MainDeck:\n{main}\n"
        "Battlefields:\n1 Field A\n1 Field B\n1 Field C\n"
        "Runes:\n6 Fury Rune\n6 Calm Rune\n"
        f"Sideboard:\n{side}\n"
    )


def test_a_deck_built_to_the_documented_numbers_has_no_structural_warnings(
    catalog: InMemoryCardCatalog,
) -> None:
    assert _structural(import_decklist(_constructed_deck(), catalog).warnings) == []


SMALL = DeckRules(
    legend_cards=1,
    champion_cards=1,
    main_deck_cards=4,
    battlefield_cards=2,
    rune_cards=3,
    max_sideboard_cards=1,
    max_copies=2,
    max_battlefield_copies=1,
)


def test_each_section_off_its_size_is_a_warning(catalog: InMemoryCardCatalog) -> None:
    text = (
        "Champion:\n1 Sona, Harmonious\n1 Pouty Poro\n"
        "MainDeck:\n1 Recruit\n"
        "Battlefields:\n1 Field A\n"
        "Runes:\n2 Fury Rune\n"
        "Sideboard:\n1 Playful Phantom\n1 Blazing Scorcher\n"
    )

    assert _structural(import_decklist(text, catalog, SMALL).warnings) == [
        "Legend has 0 cards; a deck needs exactly 1.",
        "Champion has 2 cards; a deck needs exactly 1.",
        "MainDeck has 3 cards counting the Champion; a deck needs exactly 4.",
        "Battlefields has 1 card; a deck needs exactly 2.",
        "Runes has 2 cards; a deck needs exactly 3.",
        "Sideboard has 2 cards; the most allowed is 1.",
    ]


def test_the_main_deck_counts_the_champion_and_unknown_cards(
    catalog: InMemoryCardCatalog,
) -> None:
    text = "Champion:\n1 Sona, Harmonious\nMainDeck:\n2 Pouty Poro\n1 Not A Card\n"

    warnings = import_decklist(text, catalog, SMALL).warnings

    assert not any(w.message.startswith("MainDeck has") for w in warnings)


def test_copies_of_one_card_are_counted_across_champion_main_deck_and_sideboard(
    catalog: InMemoryCardCatalog,
) -> None:
    text = (
        "Champion:\n1 Sona, Harmonious\n"
        "MainDeck:\n1 Sona, Harmonious\n1 Recruit\n1 Recruit (NX)\n"
        "Sideboard:\n1 sona, harmonious\n"
    )

    copy_warnings = _kind(import_decklist(text, catalog, SMALL).warnings, "copy_limit")

    assert [w.message for w in copy_warnings] == [
        "3 copies of Sona, Harmonious across Champion, MainDeck and Sideboard; the limit is 2.",
    ]  # Recruit and its alias are one card, at 2 copies: within the limit


def test_unknown_names_are_counted_by_the_name_as_written(
    catalog: InMemoryCardCatalog,
) -> None:
    text = "MainDeck:\n2 Pouty Porro\nSideboard:\n1 pouty porro\n"

    copy_warnings = _kind(import_decklist(text, catalog, SMALL).warnings, "copy_limit")

    assert [w.message for w in copy_warnings] == [
        "3 copies of Pouty Porro across Champion, MainDeck and Sideboard; the limit is 2.",
    ]


def test_battlefields_must_be_unique_and_runes_have_no_copy_limit(
    catalog: InMemoryCardCatalog,
) -> None:
    text = "Battlefields:\n1 Field A\n1 field a\nRunes:\n3 Fury Rune\n"

    copy_warnings = _kind(import_decklist(text, catalog, SMALL).warnings, "copy_limit")

    assert [w.message for w in copy_warnings] == [
        "2 copies of the battlefield Field A; the limit is 1.",
    ]
