import pytest

from backend.cards.collapse import Card
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
