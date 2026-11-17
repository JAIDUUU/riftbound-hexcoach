"""Command line entrypoint for the HexCoach backend."""

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool
    from sqlalchemy import Connection

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
from backend.config import CARDS_DATA_DIR, FAQS_DATA_DIR, GOLDEN_SET_PATH, RULES_DATA_DIR

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
    from backend.cards.chunk_text import card_text_chunk
    from backend.cards.repository import sync_cards
    from backend.db import make_engine
    from backend.retrieval.embedding import embedder
    from backend.retrieval.repository import ChunkRecord, replace_chunks

    cards = collapse_printings(read_snapshot(CARDS_DATA_DIR / SNAPSHOT_FILENAME))
    with_text = [card for card in cards if card.cleaned_text]
    print(f"Embedding {len(with_text)} card texts (bge-small, in-process)\u2026")
    embeddings = embedder().embed_passages([card_text_chunk(card) for card in with_text])
    snapshot_date = cards[0].snapshot_fetched.date()
    records = [
        ChunkRecord(
            text=card_text_chunk(card),
            embedding=embedding,
            source_version=snapshot_date.isoformat(),
            source_date=snapshot_date,
            title=card.oracle_name,
        )
        for card, embedding in zip(with_text, embeddings, strict=True)
    ]

    engine = make_engine()
    with engine.begin() as connection:
        written = sync_cards(connection, cards)
        indexed = replace_chunks(connection, "card_text", records)
    engine.dispose()
    print(f"Synced {written} cards; indexed {indexed} card-text chunks (snapshot {snapshot_date}).")
    report_data_problems(cards)
    return 0


def _ingest_faqs(_: argparse.Namespace) -> int:
    from backend.db import make_engine
    from backend.faqs.parse import FaqDocument, FaqParseError, load_faq
    from backend.retrieval.embedding import embedder
    from backend.retrieval.repository import ChunkRecord, replace_chunks

    paths = sorted(FAQS_DATA_DIR.glob("*.md"))
    if not paths:
        raise SystemExit(f"No FAQ files found in {FAQS_DATA_DIR}.")
    documents: list[FaqDocument] = []
    errors: list[str] = []
    for path in paths:
        try:
            document = load_faq(path)
        except FaqParseError as error:
            errors.append(str(error))
            continue
        for warning in document.warnings:
            print(f"warning: {path.name}: {warning}")
        documents.append(document)
    if errors:
        # Ingesting replaces the faq source wholesale, so a file that parsed fine last
        # time must not silently vanish because it regressed; refuse the whole batch.
        for error in errors:
            print(f"error: {error}")
        print("Nothing was ingested; fix the files above and re-run.")
        return 1

    pairs = [(document, chunk) for document in documents for chunk in document.chunks]
    print(f"Embedding {len(pairs)} FAQ chunks (bge-small, in-process)\u2026")
    embeddings = embedder().embed_passages([chunk.text for _, chunk in pairs])
    records = [
        ChunkRecord(
            text=chunk.text,
            embedding=embedding,
            source_version=document.set_code,
            source_date=document.date,
            section=chunk.section,
            title=document.title,
            source_url=document.url,
        )
        for (document, chunk), embedding in zip(pairs, embeddings, strict=True)
    ]

    engine = make_engine()
    with engine.begin() as connection:
        written = replace_chunks(connection, "faq", records)
    engine.dispose()
    titles = ", ".join(f"{d.title} ({d.date})" for d in documents)
    print(f"Ingested {written} FAQ chunks from {len(documents)} files: {titles}.")
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
    from backend.retrieval.embedding import embedder

    print(f"Embedding {len(chunks)} chunks (bge-small, in-process)\u2026")
    embeddings = embedder().embed_passages([chunk.text for chunk in chunks])

    engine = make_engine()
    with engine.begin() as connection:
        written = replace_rules(connection, chunks, source_date, embeddings)
    engine.dispose()
    print(f"Ingested {written} rule chunks from {pdf.name} (rules version {source_date}).")
    return 0


def format_hit(hit: "SearchHit") -> str:
    first_line = hit.text.split("\n", 1)[0]
    if len(first_line) > 160:
        first_line = first_line[:159] + "\u2026"
    origin = f"{hit.source_type} {hit.source_date.isoformat()}"
    parts = (hit.rule_id, hit.title, hit.section, origin)
    header = " \u00b7 ".join(part for part in parts if part)
    return f"{header}\n  {first_line}"


def _search(args: argparse.Namespace) -> int:
    from backend.db import make_engine
    from backend.retrieval.repository import hybrid_search_chunks, search_chunks

    query = " ".join(args.query)
    engine = make_engine()
    with engine.connect() as connection:
        if args.keyword_only:
            hits = search_chunks(connection, query, limit=args.limit)
        else:
            from backend.retrieval.embedding import embedder

            hits = hybrid_search_chunks(
                connection, query, embedder().embed_query(query), limit=args.limit
            )
    engine.dispose()
    if not hits:
        print("No matching chunks.")
        return 1
    for hit in hits:
        print(format_hit(hit))
    return 0


def _check_golden(_: argparse.Namespace) -> int:
    from backend.evals.golden import load_golden_set

    items = load_golden_set(GOLDEN_SET_PATH)
    answers = sum(1 for item in items if item.behaviour == "answer")
    print(
        f"{len(items)} golden items ({answers} answer, {len(items) - answers} abstain). All valid."
    )
    return 0


def _eval_retrieval(args: argparse.Namespace) -> int:
    from backend.db import make_engine
    from backend.evals.golden import load_golden_set
    from backend.evals.langfuse_run import langfuse_client, run_experiment, upload_golden_set
    from backend.evals.retrieval_eval import aggregate_hit_rate
    from backend.retrieval.embedding import embedder
    from backend.retrieval.repository import hybrid_search_chunks

    items = load_golden_set(GOLDEN_SET_PATH)
    client = langfuse_client()
    upload_golden_set(client, items)
    print(f"Uploaded {len(items)} items to the Langfuse dataset.")

    engine = make_engine()
    with engine.connect() as connection:

        def retrieve(question: str) -> list[str]:
            hits = hybrid_search_chunks(
                connection, question, embedder().embed_query(question), limit=args.limit
            )
            return [hit.rule_id for hit in hits if hit.rule_id is not None]

        results = run_experiment(client, items, retrieve, args.run_name)
    engine.dispose()

    for result in results:
        missing = f" missing: {', '.join(result.missing)}" if result.missing else ""
        print(f"{result.item_id}: hit rate {result.hit_rate:.2f}{missing}")
    print(f"Aggregate rule hit rate over {len(results)} items: {aggregate_hit_rate(results):.2f}")
    return 0


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "backend.api.app:production_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def _ping(args: argparse.Namespace) -> int:
    from backend.llm.providers import chat_chain

    chain = chat_chain()
    for provider in chain.skipped:
        print(f"note: {provider} has no API key and was skipped")
    provider, message = chain.ask(" ".join(args.prompt))
    print(f"[{provider}] {message.text}")
    return 0


def _card_lookup_tool(connection: "Connection") -> "BaseTool":
    """The lookup_card tool backed by the cards table (issue #10)."""
    from backend.agent.tools import make_lookup_card
    from backend.cards.chunk_text import card_text_chunk
    from backend.cards.repository import all_card_names, find_by_oracle_name

    def find_card(name: str) -> str | None:
        card = find_by_oracle_name(connection, name)
        return card_text_chunk(card) if card else None

    return make_lookup_card(find_card, lambda: all_card_names(connection))


def _ask(args: argparse.Namespace) -> int:
    from backend.agent.tracing import traced_run, tracing_enabled
    from backend.db import make_engine
    from backend.llm.providers import chat_chain
    from backend.retrieval.embedding import embedder
    from backend.retrieval.repository import SearchHit, hybrid_search_chunks

    chain = chat_chain()
    for provider in chain.skipped:
        print(f"note: {provider} has no API key and was skipped")
    if not tracing_enabled():
        print("note: LANGFUSE keys not set, this run will not be traced")

    engine = make_engine()
    with engine.connect() as connection:

        def retrieve(query: str) -> list[SearchHit]:
            return hybrid_search_chunks(
                connection, query, embedder().embed_query(query), limit=args.limit
            )

        state, trace_id = traced_run(
            chain, retrieve, " ".join(args.question), tools=[_card_lookup_tool(connection)]
        )
    engine.dispose()

    print(state["answer"])
    print()
    label = "answered" if state["outcome"] == "answered" else "abstained"
    trace = f" \u00b7 trace {trace_id}" if trace_id else ""
    print(f"[{label} \u00b7 query: {state['query']!r} \u00b7 {len(state['hits'])} chunks{trace}]")
    return 0


def _eval_agent(args: argparse.Namespace) -> int:
    from backend.agent.graph import Outcome
    from backend.agent.tracing import run_in_open_trace
    from backend.db import make_engine
    from backend.evals.agent_eval import (
        aggregate_behaviour_accuracy,
        aggregate_citation_score,
    )
    from backend.evals.golden import load_golden_set
    from backend.evals.langfuse_run import langfuse_client, run_agent_experiment, upload_golden_set
    from backend.llm.providers import chat_chain
    from backend.retrieval.embedding import embedder
    from backend.retrieval.repository import SearchHit, hybrid_search_chunks

    items = load_golden_set(GOLDEN_SET_PATH)
    client = langfuse_client()
    upload_golden_set(client, items)
    chain = chat_chain()

    engine = make_engine()
    with engine.connect() as connection:

        def retrieve(query: str) -> list[SearchHit]:
            return hybrid_search_chunks(
                connection, query, embedder().embed_query(query), limit=args.limit
            )

        lookup = _card_lookup_tool(connection)

        def ask(question: str) -> tuple[str, Outcome]:
            # run_experiment already opens a trace per item; adding traced_run's own
            # "ask" span inside it would just nest a redundant wrapper.
            state = run_in_open_trace(chain, retrieve, question, tools=[lookup])
            return state["answer"], state["outcome"]

        results = run_agent_experiment(client, items, ask, args.run_name)
    engine.dispose()

    for result in results:
        behaviour = "ok" if result.behaviour_correct else f"WRONG ({result.outcome})"
        citation = (
            f" \u00b7 citations {result.citation_score:.2f}"
            + (f" missing: {', '.join(result.missing)}" if result.missing else "")
            if result.citation_score is not None
            else ""
        )
        print(f"{result.item_id}: behaviour {behaviour}{citation}")
    citation_avg = aggregate_citation_score(results)
    print(
        f"Aggregate over {len(results)} items: behaviour accuracy "
        f"{aggregate_behaviour_accuracy(results):.2f}, citation score "
        f"{f'{citation_avg:.2f}' if citation_avg is not None else 'n/a'}"
    )
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
    add("ingest-faqs", _ingest_faqs, "Chunk the FAQ files in data/FAQs into the database.")
    searcher = add("search", _search, "Hybrid (keyword + vector) search across the chunks.")
    searcher.add_argument("query", nargs="+", help="Search terms, e.g. combat damage order")
    searcher.add_argument("-k", "--limit", type=int, default=10, help="Max hits (default 10)")
    searcher.add_argument(
        "--keyword-only",
        action="store_true",
        help="Skip the embedding model and use full-text search alone",
    )
    server = add("serve", _serve, "Run the HTTP API (Supabase-authenticated conversations).")
    server.add_argument("--host", default="127.0.0.1", help="Interface to bind")
    server.add_argument("--port", type=int, default=8000, help="Port to listen on")
    server.add_argument("--reload", action="store_true", help="Restart on code changes (dev)")
    pinger = add("ping", _ping, "Send one raw prompt through the provider chain (smoke test).")
    pinger.add_argument("prompt", nargs="+", help="The prompt to send")
    asker = add("ask", _ask, "Answer a rules question judge-style, with citations.")
    asker.add_argument("question", nargs="+", help="The rules question, any language")
    asker.add_argument("-k", "--limit", type=int, default=8, help="Chunks per retrieval")
    add("check-golden", _check_golden, "Validate the golden set file.")
    evaluator = add(
        "eval-retrieval", _eval_retrieval, "Run the golden set against retrieval via Langfuse."
    )
    evaluator.add_argument("--run-name", required=True, help="Experiment run name in Langfuse")
    evaluator.add_argument("-k", "--limit", type=int, default=10, help="Chunks per query")
    agent_eval = add(
        "eval-agent", _eval_agent, "Run the golden set through the full agent via Langfuse."
    )
    agent_eval.add_argument("--run-name", required=True, help="Experiment run name in Langfuse")
    agent_eval.add_argument("-k", "--limit", type=int, default=8, help="Chunks per retrieval")
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
