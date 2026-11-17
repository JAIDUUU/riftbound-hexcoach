# HexCoach backend

A Riftbound rules coach. This package holds the card data pipeline, the database layer and the
`backend` CLI. Project-wide decisions live in [`docs/adr/`](../docs/adr/) and
[`docs/Grill Decisions.md`](../docs/Grill%20Decisions.md); domain terms in
[`docs/CONTEXT.md`](../docs/CONTEXT.md).

Riftbound is a Riot Games trading card game. This project is unofficial fan content.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13. Ingesting the rules PDF also
needs Poppler's `pdftotext` (`sudo apt install poppler-utils`); it is only used by the
manual `ingest-rules` command, never in CI.

```bash
cd backend
uv sync
cp .env.example .env   # then fill in DATABASE_URL
```

`DATABASE_URL` is the Supabase Postgres connection string. Use the **session pooler** string if
the direct connection fails: the direct host is IPv6-only. Only `DATABASE_URL` is needed for the
card pipeline; the other keys in `.env.example` belong to later milestones.

## Commands

```bash
uv run backend refresh-cards   # fetch Rifthunt bulk data into the committed snapshot (manual only)
uv run backend migrate         # apply Alembic migrations (re-runnable; enables pgvector)
uv run backend load-cards      # sync the committed snapshot into the cards table
uv run backend card <name>     # look a card up by oracle name or alias and print its cleaned text
uv run backend ingest-rules    # chunk + embed the newest Core Rules PDF in data/rules into the DB
uv run backend ingest-faqs     # chunk + embed the FAQ files in data/FAQs into the database
uv run backend search <query>  # hybrid keyword+vector search across the chunks (-k for more hits)
uv run backend ask <question>  # answer a rules question judge-style, with citations (any language)
uv run backend ping <prompt>   # smoke-test the LLM provider fallback chain with one raw prompt
uv run backend check-golden    # validate data/golden/golden-set.yaml
uv run backend eval-retrieval --run-name <name>  # score retrieval on the golden set via Langfuse
```

`refresh-cards` rewrites `data/cards/rifthunt-snapshot.json` (one card per line, so diffs stay
readable) and regenerates `data/cards/card-index.json`, the static index for the frontend's `@`
menu. Per Rifthunt's request it is run at most daily. Commit the result.

`load-cards` makes the `cards` table match the snapshot: every card is upserted and cards no
longer present are deleted. Both commands warn about icon shortcodes the cleaner doesn't know
and about names that would look up more than one card.

`ingest-rules` extracts the Core Rules PDF (one chunk per rule number, with its section and
parent rule as metadata), checks that the numbering came out sequential, embeds every chunk,
and replaces the previous rules version in the `chunks` table (ADR 0008: single current
version). The rules version is the document's own "Last Updated" date. The Tournament Rules
PDF in `data/rules/` is a separate document (organized-play procedures) and is not ingested.

### Retrieval sources

Three source types live in the `chunks` table and all come back from `search`, each hit
showing its source type and date:

- **rules** — one chunk per Core Rules rule number (`ingest-rules`)
- **faq** — official post-set FAQ posts from `data/FAQs/*.md` (`ingest-faqs`); each file
  needs a frontmatter header (title, url, date, set) and is chunked by Q/A pair, with
  essay-style rulings grouped into paragraph chunks under their headings
- **card_text** — each card's name, type line and cleaned text (`load-cards`, which keeps
  the chunks in sync with the cards table; stamped with the snapshot date)

Each ingest command replaces its own source type wholesale, so re-running never
duplicates (and `ingest-faqs` refuses the whole batch if any file fails to parse, so a
regressed file can't silently vanish from the index). When sources conflict, downstream
consumers apply source precedence (ADR 0001: FAQ > card text > rules) via
`backend.retrieval.precedence.order_by_precedence`, which keeps relevance order within
each class; "between two FAQs the newer wins" is a conflict rule the answerer applies
using the dates on the hits. `search` itself ranks purely by relevance.

### The agent behind `ask`

`ask` runs a corrective-RAG-lite LangGraph: an LLM first rewrites the question as one
compact English search query (card nicknames expanded, backstory stripped, non-English
questions translated) and detects the player's language; hybrid retrieval runs; an LLM
grades whether the evidence actually covers the question. Strong evidence gets a
judge-style answer citing rule numbers and FAQ titles, in the player's language with
card names and rule quotes kept in English. Weak evidence gets exactly one corrective
retry with the grader's rewritten query; if the evidence is still weak the agent asks a
clarifying question or honestly declines instead of guessing. Prompts live in
`backend/agent/prompts.py` (and only there); the answer prompt states the source
precedence. The graph takes message history as input, so the API can later run it fresh
per request.

### Embeddings and hybrid search

Chunks and queries are embedded in-process with bge-small-en-v1.5 via fastembed's ONNX
runtime — no external embedding API. The ~130 MB model downloads to the local HuggingFace
cache on first use. `search` runs keyword (FTS) and vector (pgvector cosine) retrieval and
merges the two rankings with reciprocal rank fusion; `--keyword-only` skips the model.

Memory footprint (matters for hosting): embedding a query costs about **270 MB RSS** for
the whole Python process with the model loaded. Bulk ingestion peaks around **1.2 GB RSS**
(batches of 32 passages; fastembed's default batch of 256 peaked near 7 GB) and takes
roughly two minutes for the ~2,500 rule chunks on CPU.

`eval-retrieval` uploads the golden set (`data/golden/golden-set.yaml`, hand-written rulings
with the Core Rules ids a correct answer must cite) to the Langfuse dataset `hexcoach-golden`
— item ids are stable, so re-uploads upsert — then runs every `answer` item through `search`
and records a `rule_hit_rate` score per item (the share of expected rule ids among the top
`-k` hits, default 10). It needs `DATABASE_URL`, ingested rules and the `LANGFUSE_*` keys.
`abstain` items (where the coach should ask for clarification instead of answering) are
uploaded for later answer-level evals but skipped at the retrieval level.

## Tests

```bash
uv run pytest                  # unit tests only; no database needed
uv run pytest -m integration   # repository tests against the database in DATABASE_URL
```

Integration tests are deselected by default so a plain `pytest` can never touch a real
database. They apply the migrations, then run each test inside a rolled-back transaction.
Point `DATABASE_URL` at a dev project, never at production.

CI (lint, types, unit tests) runs on every push and stays DB-free.
