# HexCoach

A judge-style rules coach for Riftbound, the League of Legends trading card game. Ask how a
card works or how an interaction resolves, and HexCoach answers from the official Core Rules,
Riot's post-set FAQs and the card database, citing the rule numbers and sources it used. When
the evidence is weak, it asks a clarifying question instead of guessing.

> HexCoach is **not an official judge**, and its answers are not official rulings. Riftbound is
> a Riot Games game; this is an unofficial fan project.

Built with LangGraph (a corrective-RAG-lite agent), LangChain, Langfuse (tracing and evals),
FastAPI, and Supabase Postgres with pgvector for hybrid keyword and vector retrieval. The web
frontend is not built yet; until then, the CLI is the way to use it.

## Using the CLI

You need [uv](https://docs.astral.sh/uv/), Python 3.13, a Supabase project (the free tier is
enough), and an API key for at least one chat model provider. Ingesting the rules also needs
Poppler's `pdftotext` (`sudo apt install poppler-utils`).

### 1. Install and configure

```bash
cd backend
uv sync
cp .env.example .env
```

Fill in `.env`:

| Variable | Needed for |
| --- | --- |
| `DATABASE_URL` | Everything. The Supabase Postgres connection string (use the session pooler string if the direct one fails: the direct host is IPv6-only). |
| `GOOGLE_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` | `ask` and the agent evals. At least one is required. They form a fallback chain (Gemini, then Groq, then OpenRouter), and providers without a key are skipped. |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | Optional for `ask` (runs are traced when set). Required for the evals. |
| `SUPABASE_URL` | Only for `serve`, the HTTP API. |
| `CORS_ALLOWED_ORIGINS` | Only when a browser frontend calls the API: its origins, comma-separated (e.g. `http://localhost:5173`). Empty allows none. |

### 2. Build the knowledge base (once)

The rules PDF, the FAQs and the card snapshot are already committed under `data/`. These
commands load them into your database:

```bash
uv run backend migrate        # create the tables (safe to re-run)
uv run backend load-cards     # cards, plus their text as searchable chunks
uv run backend ingest-rules   # the Core Rules, one chunk per rule number
uv run backend ingest-faqs    # the official post-set FAQs
```

Embeddings are computed in-process with bge-small, which downloads about 130 MB on first use.
`ingest-rules` takes a couple of minutes on a CPU. Re-running any ingest command replaces
that source rather than duplicating it.

### 3. Ask questions

```bash
uv run backend ask "Does Sona, Harmonious trigger when a unit moves to a battlefield?"
uv run backend ask "Se dois efeitos acontecem ao mesmo tempo, quem escolhe a ordem?"
```

`ask` answers in the language of your question, but keeps card names and rule quotes in
English. Every answer ends with a status line saying whether it answered or abstained, the
search query it used, how many chunks it retrieved, and the Langfuse trace id when tracing
is on.

Other useful commands:

```bash
uv run backend card Sona, Harmonious   # a card's cleaned text, looked up by name or alias
uv run backend search combat damage    # the raw retrieval hits behind an answer (-k for more)
uv run backend ping "hello"            # smoke-test the LLM provider chain
uv run backend eval-agent --run-name my-run   # run the golden set through the agent in Langfuse
uv run backend --help                  # every command
```

The full command reference, and how ingestion, retrieval, the agent and the evals work, is
in [`backend/README.md`](backend/README.md).

## The HTTP API

`uv run backend serve` starts the API on `http://127.0.0.1:8000`, with interactive docs at
`/docs`. Every endpoint except `GET /health` requires the signed-in user's Supabase access
token as `Authorization: Bearer <jwt>`. Users only ever see their own data: someone else's
conversation or deck returns 404, exactly like one that doesn't exist.

`GET /health` is public. It returns `{"status": "ok"}` after a cheap database read, or 503
when the database doesn't answer. A scheduled GitHub Actions workflow pings it so the free
Supabase project doesn't pause. To run the API as a container and see the hosting options,
read [`docs/deployment.md`](docs/deployment.md).

### Conversations

| Method and path | What it does |
| --- | --- |
| `POST /conversations` | Create a conversation (optional `title`, up to 200 characters). |
| `GET /conversations` | List your conversations, most recently active first. |
| `GET /conversations/{id}` | One conversation with its messages, oldest first, each with its trace id and your feedback. |
| `DELETE /conversations/{id}` | Delete a conversation and its messages. |
| `PUT /conversations/{id}/messages/{message_id}/feedback` | Give or change your thumbs up or down (`{"rating": "up"}` or `"down"`) on an answer. It is saved with the message and recorded as a Langfuse score on the answer's trace. |

### Decks

A decklist is sectioned plain text: `Legend:`, `Champion:`, `MainDeck:`, `Battlefields:`,
`Runes:` and `Sideboard:` headers, each followed by lines like `3 Consult the Past`. It is
parsed in code, never by the LLM. Import validation resolves every line to a card,
suggests fixes for unknown names, and warns about section sizes and copy limits. Warnings
never stop a deck from being saved. The deck-construction numbers are unverified
placeholders until they are checked against the official rules.

| Method and path | What it does |
| --- | --- |
| `POST /decks/preview` | Validate a `decklist` without saving it. |
| `POST /decks` | Save a deck (`name`, up to 100 characters, and `decklist`); returns it with its validation. |
| `GET /decks` | List your decks (id, name, timestamps), most recently updated first. |
| `GET /decks/{id}` | One deck with its text and its validation against the current card data. |
| `PUT /decks/{id}` | Replace a deck's name and text. |
| `DELETE /decks/{id}` | Delete a deck. |

### In progress

These endpoints are still being built, so their exact shapes may change:

- `POST /conversations/{id}/messages` sends a message and streams the answer back as
  server-sent events. The events are `start` (the message id and trace id), `status` (the
  current graph step), `token`, `final` (the full text, citations and validated `[[Card]]`
  tags) and `error`. See [ADR 0005](docs/adr/0005-sse-streaming-and-final-event.md) and
  [#12](https://github.com/leofarias-cpu/riftbound-hexcoach/issues/12).
- Account deletion, which removes your conversations, messages and decks
  ([#21](https://github.com/leofarias-cpu/riftbound-hexcoach/issues/21)).

## Privacy

When tracing is on, Langfuse traces contain the text of your messages. User ids are stored
there only as a hashed pseudonym, and you can delete your conversations at any time.

## More

- [`docs/Grill Decisions.md`](docs/Grill%20Decisions.md) holds the product and architecture
  decisions, and [`docs/adr/`](docs/adr/) the individual decision records.
- [`docs/CONTEXT.md`](docs/CONTEXT.md) is the glossary.
