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
precedence. The graph takes message history as input, so the message endpoint runs it
fresh per request.

While writing the answer the model can call the `lookup_card` tool (up to three rounds)
to read any card's current text from the cards table by name or alias — real card text,
never model memory. Unknown names come back with close-name suggestions, or an explicit
"nothing similar, don't invent it". Each call shows up as a tool span in the Langfuse
trace. The tool's data access is injected (`backend/agent/tools.py`), so it is tested
against a fake card store, and `ProviderChain.bind_tools` keeps the provider failover
working with tools attached.

### Embeddings and hybrid search

Chunks and queries are embedded in-process with bge-small-en-v1.5 via fastembed's ONNX
runtime — no external embedding API. The model downloads to fastembed's cache on first
use (`FASTEMBED_CACHE_PATH`, default `<tmp>/fastembed_cache`); the container image bakes it
in. `search` runs keyword (FTS) and vector (pgvector cosine) retrieval and
merges the two rankings with reciprocal rank fusion; `--keyword-only` skips the model.

Memory footprint (matters for hosting): embedding a query costs about **270 MB RSS** for
the whole Python process with the model loaded. Bulk ingestion peaks around **1.2 GB RSS**
(batches of 32 passages; fastembed's default batch of 256 peaked near 7 GB) and takes
roughly two minutes for the ~2,500 rule chunks on CPU. The API process with the model
loaded measured about **370 MB RSS** (see `docs/deployment.md`).

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

`serve` runs a FastAPI app (`backend/api/app.py`). It needs `DATABASE_URL`,
`SUPABASE_URL` and at least one chat provider key at startup. Every endpoint except
`GET /health` needs the signed-in user's Supabase access token as
`Authorization: Bearer <jwt>`. Tokens are verified
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
- `GET /health` is public and reads one row from the database: `{"status": "ok"}`, or a
  503 when the database doesn't answer. The scheduled keep-alive workflow pings it so the
  free Supabase project doesn't pause.
- Browsers may call the API only from the origins in `CORS_ALLOWED_ORIGINS`
  (comma-separated, none by default; the Vite dev server is `http://localhost:5173`).

The API also ships as a container (`backend/Dockerfile`, same environment variables);
`docs/deployment.md` covers the image, the measured memory and the hosting options.

#### Sending a message (SSE)

`POST /conversations/{id}/messages` with `{"content": "..."}` stores the player's
message, runs the agent fresh on the conversation so far (the most recent
`MAX_HISTORY_MESSAGES` messages), and streams the answer as server-sent events
([ADR 0005](../docs/adr/0005-sse-streaming-and-final-event.md)). Refusals happen before
the stream opens, so they are plain HTTP errors: 401 (token), 404 (not your
conversation), 422 (empty or over the length cap). Once the response is a 200, the events are:

| Event    | Data                                                  | When                                    |
| -------- | ----------------------------------------------------- | --------------------------------------- |
| `start`  | `message_id`, `trace_id` (null when untraced)         | always first                            |
| `status` | `step`: `prepare`, `retrieve`, `grade`, `answer` or `abstain` | as each graph step begins; a corrective retry repeats `retrieve` and `grade` |
| `token`  | `text`                                                | while the answer is written             |
| `final`  | `text`, `outcome` (`answered`/`abstained`), `citations`, `cards` | last, on success                 |
| `error`  | `code`, `message` (safe to show the player)           | last, on failure                        |

`message_id` is the assistant message's id, and the answer is stored under it together with the
trace id just before `final` is sent, so the feedback endpoint above accepts a vote on it once
`final` has arrived (earlier it is a 404). Streamed tokens are a
preview: if a provider fails halfway through a reply, the next provider starts over, so the client
should replace the streamed text with `final.text`. `citations` are the retrieved chunks the
answer actually cites (by rule number, FAQ title or card name), most authoritative source first,
each with `source_type`, `rule_id`, `title`, `section`, `source_date`, `source_url` and `text`.
`cards` is always empty for now (validated card tags arrive with issue #15). Error codes:
`providers_unavailable` (every provider in the chain failed), `conversation_deleted` (deleted
while the answer was being written) and `internal`. On an error the player's message stays
stored and no answer is.

```bash
curl -N -X POST "http://127.0.0.1:8000/conversations/$CONVERSATION_ID/messages" \
  -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "Can I score the same battlefield twice in one turn?"}'
```

```text
event: start
data: {"message_id":"51bcf7bb-8a7d-4e67-9be6-b0f99ffd9b0f","trace_id":"3f1c..."}

event: status
data: {"step":"prepare"}

event: status
data: {"step":"retrieve"}

event: status
data: {"step":"grade"}

event: status
data: {"step":"answer"}

event: token
data: {"text":"No"}

event: token
data: {"text":" - a battlefield scores once per turn (rule 472)."}

event: final
data: {"text":"No - a battlefield scores once per turn (rule 472).","outcome":"answered","citations":[{"source_type":"rules","rule_id":"472","title":null,"section":"Scoring","source_date":"2026-10-09","source_url":null,"text":"..."}],"cards":[]}
```

`-N` turns off curl's buffering so events print as they arrive. Idle stretches longer than 15
seconds (a slow provider) get a `: ping` comment line, which SSE parsers ignore. Browsers can't
use `EventSource` for a POST, so the frontend reads the stream with `fetch`.

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

Tests never call Supabase, Langfuse or an LLM: tokens are signed with locally generated
keys, the API runs against an in-memory store that
`tests/conversations/test_store_contract.py` holds to the same ownership and feedback
rules as the Postgres store, feedback scores go to a fake Langfuse client, and the message
endpoint gets a scripted coach in place of the agent (`backend.agent.coach.Coach`). The
agent's own streaming is tested with a fake chat model that streams word by word.

### Tracing

When the `LANGFUSE_*` keys are set, every `ask`, every chat message and every `eval-agent`
item produces a Langfuse trace covering the graph steps and LLM calls; the CLI prints the
trace id, and the message endpoint sends it in `start` and stores it with the answer.
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
