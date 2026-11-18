"""Parse sectioned plain-text Decklists, deterministically and never by the LLM.

The format (Grill Decisions, Decklists) is a header line per Deck section followed by
"<count> <card name>" lines. Card names can contain commas and even colons
("Command: Attack"), but none starts with a digit, so the leading count is unambiguous.
Parsing never fails: lines it cannot read become warnings and the rest still parses.
"""

import re
from dataclasses import dataclass
from typing import Literal, get_args

from backend.decks.warnings import DeckWarning

Section = Literal["Legend", "Champion", "MainDeck", "Battlefields", "Runes", "Sideboard"]
SECTIONS: tuple[Section, ...] = get_args(Section)

# A header is a name, then optionally a colon and a section count like "(40)", in either
# order: "Main Deck (40):", "Rune Deck: (12)".
_HEADER = re.compile(
    r"(?P<label>[A-Za-z][A-Za-z _-]*?)\s*(?P<colon>:)?"
    r"\s*(?P<count>\(\s*\d+\s*\))?\s*(?P<colon_after>:)?"
)
_CARD = re.compile(r"(?P<count>\d+)\s+(?P<name>\S.*)")
_SECTION_BY_KEY: dict[str, Section] = {
    **{section.lower().removesuffix("s"): section for section in SECTIONS},
    "main": "MainDeck",
    "championlegend": "Legend",
    "chosenchampion": "Champion",
    "runedeck": "Runes",
}
_SECTION_LIST = f"{', '.join(SECTIONS[:-1])} or {SECTIONS[-1]}"


@dataclass(frozen=True, slots=True)
class DeckLine:
    number: int  # the 1-based line number, so warnings and the editor agree on where a card is
    section: Section
    count: int
    name: str  # as written; resolving it to a Card is import validation's job


@dataclass(frozen=True, slots=True)
class ParsedDecklist:
    lines: tuple[DeckLine, ...]  # in source order
    warnings: tuple[DeckWarning, ...]


def _known_section(label: str) -> Section | None:
    """The section a header names, ignoring case, spaces, hyphens and underscores and
    singular or plural: `MainDeck`, `Main Deck` and `main-deck` are one, as are `Rune` and
    `Runes`. The Core Rules' own names (`Champion Legend`, `Chosen Champion`, `Rune Deck`)
    and a bare `Main` count too."""
    key = re.sub(r"[\s_-]+", "", label).lower().removesuffix("s")
    return _SECTION_BY_KEY.get(key)


def parse_decklist(text: str) -> ParsedDecklist:
    lines: list[DeckLine] = []
    warnings: list[DeckWarning] = []
    section: Section | None = None
    in_unknown_section = False
    for number, raw in enumerate(text.removeprefix("\ufeff").splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        # A bare card name ("Pouty Poro") looks like a header without its colon, so only
        # the known section names may leave both the colon and the count off.
        header = _HEADER.fullmatch(stripped)
        if header and (known := _known_section(header["label"])):
            section, in_unknown_section = known, False
            continue
        if header and (header["colon"] or header["count"] or header["colon_after"]):
            section, in_unknown_section = None, True
            warnings.append(
                DeckWarning(
                    "unknown_section",
                    f"{header['label']!r} is not a deck section (expected {_SECTION_LIST}), "
                    "so the cards under it were left out.",
                    line=number,
                )
            )
            continue
        if in_unknown_section:
            continue
        card = _CARD.fullmatch(stripped)
        if card is None:
            warnings.append(
                DeckWarning(
                    "malformed_line",
                    f"Line {number} ({stripped!r}) could not be read; expected a count and a "
                    "card name, like '3 Pouty Poro'.",
                    line=number,
                )
            )
        elif int(card["count"]) == 0:
            warnings.append(
                DeckWarning(
                    "malformed_line", f"Line {number} ({stripped!r}) has a count of 0.", number
                )
            )
        elif section is None:
            warnings.append(
                DeckWarning(
                    "outside_section",
                    f"Line {number} ({stripped!r}) is not under a section header, "
                    "so it was left out.",
                    line=number,
                )
            )
        else:
            lines.append(DeckLine(number, section, int(card["count"]), card["name"]))
    return ParsedDecklist(tuple(lines), tuple(warnings))
