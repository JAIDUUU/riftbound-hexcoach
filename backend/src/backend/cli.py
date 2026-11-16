"""Command line entrypoint for the HexCoach backend."""

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.retrieval.repository import SearchHit

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
from backend.config import CARDS_DATA_DIR, RULES_DATA_DIR

CORE_RULES_PDF_GLOB = "RiftboundCoreRules-*.pdf"


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


def _latest_core_rules_pdf() -> Path:
    candidates = sorted(RULES_DATA_DIR.glob(CORE_RULES_PDF_GLOB))
    if not candidates:
        raise SystemExit(f"No {CORE_RULES_PDF_GLOB} found in {RULES_DATA_DIR}.")
    return candidates[-1]  # the date is in the name, so the newest sorts last


def _ingest_rules(args: argparse.Namespace) -> int:
    from backend.retrieval.repository import replace_rules
    from backend.rules.extract import extract_pdf_text
    from backend.rules.parse import parse_rules, rules_date, sequence_problems

    pdf = Path(args.pdf) if args.pdf else _latest_core_rules_pdf()
    text = extract_pdf_text(pdf)
    source_date = rules_date(text)
    chunks = parse_rules(text)
    problems, gaps = sequence_problems(chunks)
    for gap in gaps:
        print(f"note: rule numbering jumps {gap} (expected between rule groups)")
    if problems:
        for problem in problems:
            print(f"error: rule numbering breaks at {problem}")
        print("Extraction looks mangled; nothing was ingested.")
        return 1

    from backend.db import make_engine

    engine = make_engine()
    with engine.begin() as connection:
        written = replace_rules(connection, chunks, source_date)
    engine.dispose()
    print(f"Ingested {written} rule chunks from {pdf.name} (rules version {source_date}).")
    return 0


def format_hit(hit: "SearchHit") -> str:
    first_line = hit.text.split("\n", 1)[0]
    if len(first_line) > 160:
        first_line = first_line[:159] + "\u2026"
    origin = f"{hit.source_type} {hit.source_date.isoformat()}"
    header = " \u00b7 ".join(part for part in (hit.rule_id, hit.section, origin) if part)
    return f"{header}\n  {first_line}"


def _search(args: argparse.Namespace) -> int:
    from backend.db import make_engine
    from backend.retrieval.repository import search_chunks

    engine = make_engine()
    with engine.connect() as connection:
        hits = search_chunks(connection, " ".join(args.query), limit=args.limit)
    engine.dispose()
    if not hits:
        print("No matching chunks.")
        return 1
    for hit in hits:
        print(format_hit(hit))
    return 0


def _ask(args: argparse.Namespace) -> int:
    from backend.llm.providers import chat_chain

    chain = chat_chain()
    for provider in chain.skipped:
        print(f"note: {provider} has no API key and was skipped")
    provider, message = chain.ask(" ".join(args.prompt))
    print(f"[{provider}] {message.text()}")
    return 0


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
    ingest = add("ingest-rules", _ingest_rules, "Chunk the Core Rules PDF into the database.")
    ingest.add_argument("--pdf", help=f"Rules PDF (default: newest {CORE_RULES_PDF_GLOB})")
    searcher = add("search", _search, "Full-text search across the ingested chunks.")
    searcher.add_argument("query", nargs="+", help="Search terms, e.g. combat damage order")
    searcher.add_argument("-k", "--limit", type=int, default=10, help="Max hits (default 10)")
    asker = add("ask", _ask, "Send one prompt through the real provider chain (smoke test).")
    asker.add_argument("prompt", nargs="+", help="The prompt to send")
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
