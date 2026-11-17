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
uv run backend serve           # run the HTTP API on 127.0.0.1:8000 (--host/--port/--reload)
uv run backend check-golden    # validate data/golden/golden-set.yaml
uv run backend eval-retrieval --run-name <name>  # score retrieval on the golden set via Langfuse
uv run backend eval-agent --run-name <name>      # run the full agent on the golden set via Langfuse
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

While writing the answer the model can call the `lookup_card` tool (up to three rounds)
to read any card's current text from the cards table by name or alias — real card text,
never model memory. Unknown names come back with close-name suggestions, or an explicit
"nothing similar, don't invent it". Each call shows up as a tool span in the Langfuse
trace. The tool's data access is injected (`backend/agent/tools.py`), so it is tested
against a fake card store, and `ProviderChain.bind_tools` keeps the provider failover
working with tools attached.

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

`eval-agent` is the answer-level eval: it runs the full agent on every golden item and
records two scores per item in the Langfuse run — `behaviour_correct` (did it answer when
it should answer and abstain when it should abstain) and, for `answer` items,
`citation_score` (the share of expected rule ids actually cited in the answer). Scoring
lives in `backend/evals/agent_eval.py` and is unit-tested without any network.

### The HTTP API

`serve` runs a FastAPI app (`backend/api/app.py`). Every endpoint needs the signed-in
user's Supabase access token as `Authorization: Bearer <jwt>`. Tokens are verified
against the project's public JWKS (`SUPABASE_URL`; asymmetric ES256/RS256 only, audience
`authenticated`), so the backend holds no Supabase secret. Missing or bad tokens get a
401, and so do anonymous-session tokens (real accounts only); a JWKS outage gets a 503.

- `POST /conversations` (optional `title`, at most 200 characters), `GET /conversations`
  (most recently active first), `GET /conversations/{id}` (with messages, oldest first,
  each carrying its trace id), `DELETE /conversations/{id}`.
- Someone else's conversation is a plain 404, the same as one that doesn't exist.
- Deleting a conversation cascades to its messages; deleting the Supabase account
  cascades to its conversations.
- Input caps (`MAX_MESSAGE_CHARS`, `MAX_HISTORY_MESSAGES`) are enforced in the
  conversation store, the boundary every message write and every LLM-bound history read
  goes through; an over-long player message is a 422 on any endpoint. The defaults (4000
  characters, 20 messages) are placeholders until the free-tier limits are verified.
- `PUT /conversations/{id}/messages/{message_id}/feedback` with `{"rating": "up" | "down"}`
  records Feedback on an answer. Only answers with a trace id can be rated (409 otherwise).
  The rating is stored on the message (migration 0009), so `GET /conversations/{id}`
  shows it after a reload, and is sent to Langfuse as a `feedback` BOOLEAN score on the
  answer's trace once the vote has committed. Langfuse replaces a score only when its id,
  name and timestamp date all match, so each message has one score id and the backend
  resends the time feedback was first given: changing the vote replaces the score.
  Without Langfuse keys the vote is only stored.

Decks are per account, with the same ownership rules (someone else's deck is a 404):

- `POST /decks/preview` (`decklist`) runs import validation without saving.
- `POST /decks` (`name`, at most 100 characters, and `decklist`), `GET /decks` (summaries,
  most recently updated first), `GET /decks/{id}`, `PUT /decks/{id}` (replaces name and
  text), `DELETE /decks/{id}`. Deleting the Supabase account cascades to its decks.
- Create, read, update and preview return the validation: every section with its lines,
  each resolved to a card (`oracle_id`, `oracle_name`) or `null` with close-name
  suggestions, plus a list of typed warnings (`malformed_line`, `outside_section`,
  `unknown_section`, `unknown_card`, `section_size`, `copy_limit`). Warnings never block
  saving.

Decklists are parsed in code (`backend/decks/parse.py`), never by the LLM: one header per
section (Legend, Champion, MainDeck, Battlefields, Runes, Sideboard) and `<count> <name>`
lines, where names can contain commas and colons. Only the text is stored. Validation is
recomputed from it on every read, so a card snapshot refresh is picked up. Cards resolve
through the same oracle-name/alias matcher and alias-aware suggestions as `lookup_card`
(`backend/cards/catalog.py`). `import_decklist` (`backend/decks/importing.py`) is the one
entry point for every decklist, so checks on the decklist itself, such as a size cap, go
there. The structural numbers (`backend/decks/construction.py`) are **unverified**
placeholders read from the Core and Tournament Rules for constructed play: 1 Legend,
1 Champion, a 40-card Main Deck counting the Champion, 3 unique Battlefields, 12 Runes, a
Sideboard of at most 10, and at most 3 copies of a card across Champion, Main Deck and
Sideboard.

### Supabase's Data API is closed

Supabase serves the `public` schema to anyone holding the anon key, which the frontend
ships. None of our data goes through it, so it is locked out (migrations 0007 and 0008):
every table has row level security on with no policies, the `anon` and `authenticated`
roles hold no privileges on our tables or sequences, and new tables and sequences start
that way too. The backend connects as the table owner, which bypasses RLS. When writing
a migration:

- A new table needs `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`.
- A new function in `public` needs `REVOKE EXECUTE ON FUNCTION ... FROM PUBLIC`: Postgres
  grants execute to everyone by default, and the Data API would expose it as an RPC.

`tests/test_data_api_lockdown.py` (integration) checks the whole schema, so run
`pytest -m integration` before merging a migration.

Tests never call Supabase: tokens are signed with locally generated keys, and the API
runs against in-memory stores and a fake Langfuse client. Contract suites hold each fake
to the same rules as its Postgres counterpart: `tests/conversations/test_store_contract.py`
(ownership and feedback), `tests/decks/test_deck_store_contract.py` (ownership) and
`tests/cards/test_catalog_contract.py` (card-name matching).

### Tracing

When the `LANGFUSE_*` keys are set, every `ask` (and every `eval-agent` item) produces a
Langfuse trace covering the graph steps and LLM calls, and the CLI prints the trace id.
User ids are never sent raw — `backend.agent.tracing.hash_user_id` stores a SHA-256
pseudonym — and the conversation id becomes the Langfuse session id. Without the keys,
`ask` runs untraced and says so; nothing else changes.

## Tests

```bash
uv run pytest                  # unit tests only; no database needed
uv run pytest -m integration   # repository tests against the database in DATABASE_URL
```

Integration tests are deselected by default so a plain `pytest` can never touch a real
database. They apply the migrations, then run each test inside a rolled-back transaction.
Point `DATABASE_URL` at a dev project, never at production.

CI (lint, types, unit tests) runs on every push and stays DB-free.
