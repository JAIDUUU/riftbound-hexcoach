"""Command line entrypoint for the HexCoach backend."""

import argparse
from collections.abc import Callable, Sequence

from backend.cards.client_index import build_client_index
from backend.cards.collapse import Card, collapse_printings
from backend.cards.quality import data_problems
from backend.cards.snapshot import (
    CLIENT_INDEX_FILENAME,
    SNAPSHOT_FILENAME,
    fetch_snapshot,
    read_snapshot,
    write_json,
    write_snapshot,
)
from backend.config import CARDS_DATA_DIR


def report_data_problems(cards: Sequence[Card]) -> None:
    for problem in data_problems(cards):
        print(f"warning: {problem}")


def _refresh_cards(_: argparse.Namespace) -> int:
    snapshot = fetch_snapshot()
    write_snapshot(CARDS_DATA_DIR / SNAPSHOT_FILENAME, snapshot)
    cards = collapse_printings(snapshot)
    write_json(CARDS_DATA_DIR / CLIENT_INDEX_FILENAME, build_client_index(cards))
    print(
        f"Snapshot of {len(snapshot['cards'])} printings fetched {snapshot['fetched']}: "
        f"{len(cards)} cards. Wrote {SNAPSHOT_FILENAME} and {CLIENT_INDEX_FILENAME}."
    )
    report_data_problems(cards)
    return 0


def _migrate(_: argparse.Namespace) -> int:
    from backend.db import upgrade_to_head

    upgrade_to_head()
    print("Database is up to date.")
    return 0


def _load_cards(_: argparse.Namespace) -> int:
    from backend.cards.repository import sync_cards
    from backend.db import make_engine

    cards = collapse_printings(read_snapshot(CARDS_DATA_DIR / SNAPSHOT_FILENAME))
    engine = make_engine()
    with engine.begin() as connection:
        written = sync_cards(connection, cards)
    engine.dispose()
    print(f"Synced {written} cards to the database.")
    report_data_problems(cards)
    return 0


def format_card(card: Card) -> str:
    stats = [
        f"{label} {value}"
        for label, value in (("Energy", card.energy), ("Might", card.might), ("Power", card.power))
        if value is not None
    ]
    header = f"{card.oracle_name} [{card.card_type}] {' / '.join(card.domains)}"
    lines = [header, " ".join(stats)] if stats else [header]
    lines.append(card.cleaned_text or "(no text)")
    if card.aliases:
        lines.append("Also known as: " + ", ".join(card.aliases))
    return "\n".join(lines)


def _card(args: argparse.Namespace) -> int:
    from backend.cards.repository import find_by_oracle_name
    from backend.db import make_engine

    engine = make_engine()
    with engine.connect() as connection:
        card = find_by_oracle_name(connection, " ".join(args.name))
    engine.dispose()
    if card is None:
        print("No card with that name.")
        return 1
    print(format_card(card))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backend",
        description="HexCoach backend: Riftbound rules coach.",
    )
    commands = parser.add_subparsers(dest="command")

    def add(name: str, handler: Callable[[argparse.Namespace], int], help_text: str):
        command = commands.add_parser(name, help=help_text)
        command.set_defaults(handler=handler)
        return command

    add(
        "refresh-cards",
        _refresh_cards,
        "Fetch Rifthunt cards into the committed snapshot (manual).",
    )
    add("migrate", _migrate, "Apply database migrations.")
    add("load-cards", _load_cards, "Load the committed card snapshot into the database.")
    lookup = add("card", _card, "Look a card up by oracle name.")
    lookup.add_argument("name", nargs="+", help="Card name, e.g. Sona, Harmonious")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler: Callable[[argparse.Namespace], int] | None = getattr(args, "handler", None)
    if handler is None:
        print("HexCoach backend")
        parser.print_usage()
        return 0
    return handler(args)
