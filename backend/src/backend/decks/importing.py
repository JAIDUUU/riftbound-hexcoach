"""Import validation: parse a Decklist, resolve each line to a Card, run structural checks.

`import_decklist` is the one entry point every decklist goes through (preview, create and
update alike), so a check on the decklist itself belongs here and nowhere else. Problems
are warnings and never block the import: the player's text is saved as written. The one
refusal is the size cap (`MAX_DECKLIST_CHARS`), an input cap against abuse rather than a
deck problem.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from backend.cards.catalog import CardCatalog, close_names
from backend.cards.collapse import Card
from backend.config import positive_int_env
from backend.decks.construction import CONSTRUCTED, DeckRules
from backend.decks.parse import DeckLine, Section, parse_decklist
from backend.decks.warnings import DeckWarning

_COPY_LIMITED: tuple[Section, ...] = ("Champion", "MainDeck", "Sideboard")

# Placeholder until the free-tier limits are verified. A full constructed list with long
# names is under 2500 characters; the cap bounds parsing and the per-line name matching.
DEFAULT_MAX_DECKLIST_CHARS = 4000


class DecklistTooLongError(ValueError):
    """A decklist is over the configured size cap; unlike warnings, this refuses it."""

    def __init__(self, length: int, cap: int) -> None:
        self.length = length
        self.cap = cap
        super().__init__(f"Decklist is {length} characters; the limit is {cap}.")


def max_decklist_chars_from_env() -> int:
    return positive_int_env("MAX_DECKLIST_CHARS", DEFAULT_MAX_DECKLIST_CHARS)


@dataclass(frozen=True, slots=True)
class ResolvedLine:
    line: DeckLine
    card: Card | None  # None when no card answers to the written name
    suggestions: tuple[str, ...] = ()  # close names for an unresolved line, best first

    @property
    def copy_key(self) -> str:
        """What counts as "the same card": the Card when resolved, else the written name."""
        return self.card.oracle_id if self.card else self.line.name.lower()

    @property
    def display_name(self) -> str:
        return self.card.oracle_name if self.card else self.line.name


@dataclass(frozen=True, slots=True)
class DeckImport:
    lines: tuple[ResolvedLine, ...]  # in source order
    warnings: tuple[DeckWarning, ...]


def _cards(count: int) -> str:
    return f"{count} card" if count == 1 else f"{count} cards"


def _unknown_card(line: DeckLine, suggestions: list[str]) -> DeckWarning:
    missing = f"Line {line.number}: no card named {line.name!r}"
    if suggestions:
        return DeckWarning(
            "unknown_card", f"{missing}. Did you mean {', '.join(suggestions)}?", line.number
        )
    return DeckWarning("unknown_card", f"{missing}, and no similar name exists.", line.number)


def _section_sizes(lines: Sequence[ResolvedLine], rules: DeckRules) -> list[DeckWarning]:
    size: dict[Section, int] = {}
    for resolved in lines:
        section = resolved.line.section
        size[section] = size.get(section, 0) + resolved.line.count
    main_deck = size.get("MainDeck", 0) + size.get("Champion", 0)
    exact: list[tuple[Section, int, int, str]] = [
        ("Legend", size.get("Legend", 0), rules.legend_cards, ""),
        ("Champion", size.get("Champion", 0), rules.champion_cards, ""),
        ("MainDeck", main_deck, rules.main_deck_cards, " counting the Champion"),
        ("Battlefields", size.get("Battlefields", 0), rules.battlefield_cards, ""),
        ("Runes", size.get("Runes", 0), rules.rune_cards, ""),
    ]
    warnings = [
        DeckWarning(
            "section_size",
            f"{section} has {_cards(actual)}{note}; a deck needs exactly {wanted}.",
        )
        for section, actual, wanted, note in exact
        if actual != wanted
    ]
    sideboard = size.get("Sideboard", 0)
    if sideboard > rules.max_sideboard_cards:
        warnings.append(
            DeckWarning(
                "section_size",
                f"Sideboard has {_cards(sideboard)}; the most allowed is "
                f"{rules.max_sideboard_cards}.",
            )
        )
    return warnings


def _copies(lines: Sequence[ResolvedLine]) -> dict[str, tuple[str, int]]:
    """Copies per card, in first-seen order, named as the first line spelled it."""
    copies: dict[str, tuple[str, int]] = {}
    for resolved in lines:
        name, count = copies.get(resolved.copy_key, (resolved.display_name, 0))
        copies[resolved.copy_key] = (name, count + resolved.line.count)
    return copies


def _copy_limits(lines: Sequence[ResolvedLine], rules: DeckRules) -> list[DeckWarning]:
    limited = [r for r in lines if r.line.section in _COPY_LIMITED]
    battlefields = [r for r in lines if r.line.section == "Battlefields"]
    warnings = [
        DeckWarning(
            "copy_limit",
            f"{count} copies of {name} across Champion, MainDeck and Sideboard; "
            f"the limit is {rules.max_copies}.",
        )
        for name, count in _copies(limited).values()
        if count > rules.max_copies
    ]
    warnings += [
        DeckWarning(
            "copy_limit",
            f"{count} copies of the battlefield {name}; "
            f"the limit is {rules.max_battlefield_copies}.",
        )
        for name, count in _copies(battlefields).values()
        if count > rules.max_battlefield_copies
    ]
    return warnings


def import_decklist(
    text: str,
    cards: CardCatalog,
    rules: DeckRules = CONSTRUCTED,
    *,
    max_chars: int | None = DEFAULT_MAX_DECKLIST_CHARS,
) -> DeckImport:
    """Raises DecklistTooLongError over `max_chars` (None: no cap, for text that was
    already accepted when it was saved)."""
    if max_chars is not None and len(text) > max_chars:
        raise DecklistTooLongError(len(text), max_chars)
    parsed = parse_decklist(text)
    warnings = list(parsed.warnings)
    resolved: list[ResolvedLine] = []
    names: list[str] | None = None  # loaded once, and only if some line misses
    for line in parsed.lines:
        card = cards.find(line.name)
        if card is not None:
            resolved.append(ResolvedLine(line, card))
            continue
        if names is None:
            names = list(cards.all_names())
        suggestions = close_names(line.name, names)
        resolved.append(ResolvedLine(line, None, tuple(suggestions)))
        warnings.append(_unknown_card(line, suggestions))
    warnings += _section_sizes(resolved, rules)
    warnings += _copy_limits(resolved, rules)
    return DeckImport(tuple(resolved), tuple(warnings))
