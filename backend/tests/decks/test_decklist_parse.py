from backend.decks.parse import DeckLine, parse_decklist
from backend.decks.warnings import DeckWarning

_SPEC_EXAMPLE = """\
Legend:
1 Viktor, Herald of the Arcane

Champion:
1 Viktor, Innovator

MainDeck:
3 Consult the Past

Battlefields:
1 Ravenbloom Conservatory

Runes:
6 Mind Rune
6 Order Rune

Sideboard:
3 Salvage
"""


def test_the_grill_decisions_example_parses_into_its_sections() -> None:
    parsed = parse_decklist(_SPEC_EXAMPLE)

    assert parsed.lines == (
        DeckLine(number=2, section="Legend", count=1, name="Viktor, Herald of the Arcane"),
        DeckLine(number=5, section="Champion", count=1, name="Viktor, Innovator"),
        DeckLine(number=8, section="MainDeck", count=3, name="Consult the Past"),
        DeckLine(number=11, section="Battlefields", count=1, name="Ravenbloom Conservatory"),
        DeckLine(number=14, section="Runes", count=6, name="Mind Rune"),
        DeckLine(number=15, section="Runes", count=6, name="Order Rune"),
        DeckLine(number=18, section="Sideboard", count=3, name="Salvage"),
    )
    assert parsed.warnings == ()


def test_names_keep_their_commas_and_colons() -> None:
    parsed = parse_decklist("MainDeck:\n2 Command: Attack\n1 Sona, Harmonious\n")

    assert [line.name for line in parsed.lines] == ["Command: Attack", "Sona, Harmonious"]
    assert parsed.warnings == ()


def test_headers_forgive_case_spacing_a_missing_colon_and_windows_line_endings() -> None:
    text = "\ufefflegend\r\n  1 Annie, Dark Child  \r\n\r\nMain Deck :\r\n3   Pouty Poro\r\n"

    parsed = parse_decklist(text)

    assert parsed.lines == (
        DeckLine(number=2, section="Legend", count=1, name="Annie, Dark Child"),
        DeckLine(number=5, section="MainDeck", count=3, name="Pouty Poro"),
    )
    assert parsed.warnings == ()


def test_a_repeated_section_keeps_adding_to_it() -> None:
    parsed = parse_decklist("MainDeck:\n3 Pouty Poro\nRunes:\n6 Fury Rune\nMainDeck:\n2 Recruit")

    assert [(line.section, line.name) for line in parsed.lines] == [
        ("MainDeck", "Pouty Poro"),
        ("Runes", "Fury Rune"),
        ("MainDeck", "Recruit"),
    ]


def test_cards_before_any_header_are_reported_and_left_out() -> None:
    parsed = parse_decklist("3 Pouty Poro\nMainDeck:\n1 Recruit")

    assert [line.name for line in parsed.lines] == ["Recruit"]
    assert parsed.warnings == (
        DeckWarning(
            "outside_section",
            "Line 1 ('3 Pouty Poro') is not under a section header, so it was left out.",
            line=1,
        ),
    )


def test_an_unknown_section_is_reported_once_and_its_cards_left_out() -> None:
    parsed = parse_decklist("Tokens:\n1 Recruit\n2 Bird // Bomb\nRunes:\n6 Fury Rune")

    assert [line.name for line in parsed.lines] == ["Fury Rune"]
    assert parsed.warnings == (
        DeckWarning(
            "unknown_section",
            "'Tokens' is not a deck section (expected Legend, Champion, MainDeck, "
            "Battlefields, Runes or Sideboard), so the cards under it were left out.",
            line=1,
        ),
    )


def test_lines_that_are_not_count_and_name_are_reported_with_their_line_number() -> None:
    text = "MainDeck:\nPouty Poro\nthree Recruit\n0 Recruit\n3\nLegend: 1 Annie, Dark Child\n"

    parsed = parse_decklist(text)

    assert parsed.lines == ()
    assert [(w.kind, w.line) for w in parsed.warnings] == [
        ("malformed_line", 2),
        ("malformed_line", 3),
        ("malformed_line", 4),
        ("malformed_line", 5),
        ("malformed_line", 6),
    ]
    assert parsed.warnings[0].message == (
        "Line 2 ('Pouty Poro') could not be read; expected a count and a card name, "
        "like '3 Pouty Poro'."
    )
    assert parsed.warnings[2].message == "Line 4 ('0 Recruit') has a count of 0."


def test_empty_text_parses_to_nothing() -> None:
    assert parse_decklist("") == parse_decklist("  \n\n\t\n")
    assert parse_decklist("").lines == ()
    assert parse_decklist("").warnings == ()
