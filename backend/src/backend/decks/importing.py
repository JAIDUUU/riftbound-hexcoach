"""Import validation: parse a Decklist, resolve each line to a Card, run structural checks.

`import_decklist` is the one entry point every decklist goes through (preview, create and
update alike), so a check on the decklist itself belongs here and nowhere else. Problems
are warnings and never block the import: the player's text is saved as written.
"""

from dataclasses import dataclass

from backend.cards.catalog import CardCatalog, close_names
from backend.cards.collapse import Card
from backend.decks.parse import DeckLine, parse_decklist
from backend.decks.warnings import DeckWarning


@dataclass(frozen=True, slots=True)
class ResolvedLine:
    line: DeckLine
    card: Card | None  # None when no card answers to the written name
    suggestions: tuple[str, ...] = ()  # close names for an unresolved line, best first


@dataclass(frozen=True, slots=True)
class DeckImport:
    lines: tuple[ResolvedLine, ...]  # in source order
    warnings: tuple[DeckWarning, ...]


def _unknown_card(line: DeckLine, suggestions: list[str]) -> DeckWarning:
    missing = f"Line {line.line}: no card named {line.name!r}"
    if suggestions:
        return DeckWarning(
            "unknown_card", f"{missing}. Did you mean {', '.join(suggestions)}?", line.line
        )
    return DeckWarning("unknown_card", f"{missing}, and no similar name exists.", line.line)


def import_decklist(text: str, cards: CardCatalog) -> DeckImport:
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
    return DeckImport(tuple(resolved), tuple(warnings))
