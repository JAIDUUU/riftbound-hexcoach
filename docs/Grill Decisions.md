# HexCoach: Grill Decisions

**Status: COMPLETE.** The grilling session reached a shared understanding. Nothing has been implemented yet.
Source plan: [The Plan.md](The%20Plan.md). Glossary: [CONTEXT.md](CONTEXT.md). Architecture decisions: [adr/](adr/).

## Settled decisions

### Product
- **Hosting:** public demo on free tiers. README with screenshots and Langfuse trace links.
- **v1 core:** rules and card-text Q&A with cited sources (judge-style). The other use cases (sequence of plays, deckbuilding/strategy, best play) come later.
- **Grounding:** always cite rule numbers or sources. If evidence is weak, say so or ask a clarifying question (abstain), never guess confidently.
- **Accounts:** real accounts (login), not anonymous sessions. Supabase Auth with **OAuth only**: Google, GitHub and Discord. No passwords.
- **Language:** answer in the user's language, but keep card names and rule quotes in English. The query is translated to English for retrieval.
- **Disclaimers:** the "not an official judge" disclaimer is shown in the chat footer, the README and the empty state (not on every answer). Riot's fan-content wording is added to the same footer once verified.
- **Privacy and retention:**
  - Traces use a hashed user id and the conversation id as the Langfuse `session_id`.
  - Traces contain message text, so the UI and README carry a short privacy note.
  - Users can delete conversations and their account (cascades to messages and decks).
  - Langfuse's own trace retention is stated in the privacy note once verified.

### Source precedence
- Source types are **FAQs**, **card text** and **rules**.
- **FAQs** are Riot's official post-set FAQs. They are the only blog-type source. No other blog posts are used.
- Precedence when sources disagree: **FAQs > card text > rules**. If two FAQs conflict, the newer one wins.
- Every chunk carries its source type and date. The precedence is stated in the prompt. Answers do not need to label when an FAQ is the only support, but citations always name the source.
- **Rules versioning:** only the current rules version is kept, stored with its version and date. A rules update means a re-ingest and a golden-set re-run.
- Community rulings (for example those served by Rifthunt from the unofficial Riftbound FAQ, CC BY-SA 4.0) are **not** used at runtime. They may inspire golden-set items.

### Evaluation and observability
- **Evals:** hand-curated golden set (about 30-50 rulings with expected rule numbers), run as a Langfuse dataset and experiment, scores shown in the README. The user writes all items by hand.
- **User feedback:** thumbs up/down sent as a Langfuse score on the message's trace. Requirement: every chat response returns its trace id to the frontend.
- **No LLM-as-judge** for now.
- **Prompts:** kept in the repo only. Langfuse is used for traces, datasets, experiments and feedback scores, not for prompt management.

### Cards
- **Data source:** snapshot of Rifthunt's `/bulk/cards` (`https://api.rifthunt.com`), committed to the repo with its fetched date and refreshed by a manual script. No runtime API calls. Rifthunt needs no key, and says its data is free for any use and unofficial Riot Fan Content.
- **Card identity:** one card is one `oracle_id` (the id Rifthunt shares across all printings). Mentions, `@` search and decklists match on `oracle_name`. Printings (Metal, alternate, overnumbered) collapse into the plain one, since card text is identical.
- **Card text:** raw and cleaned text are both stored. Cleaning is a deterministic step at ingestion: `:rb_*:` icon shortcodes become words (for example `:rb_energy_1:` becomes "1 Energy") and keyword brackets are stripped. Retrieval and prompts use the cleaned text.
- **Images:** hotlinked from `images.rifthunt.com`, "normal" (480w) size for hover previews, with a text fallback when the image fails. Not stored. Hotlinking is **not verified** as allowed.
- **Card mentions in answers:** the model wraps cards as `[[Card Name]]`. The backend validates each against the card database, and the frontend only renders hover previews for validated ones. Unvalidated `[[X]]` is shown as plain text.
- **Card context for the LLM:** `@`-mentioned cards are injected with full text. A decklist is injected as card names only. The LLM gets a `lookup_card` tool for any other card (reading from our database), and each call is traced in Langfuse.
- **`@` mentions:** one `@` menu for cards and decks, grouped into "Decks" and "Cards" with a type icon. A chip shows which kind was picked, so a card and a deck with the same name never clash. Cards are searched with a client-side index built from static JSON generated at ingestion.

### Decklists
- **Format:** sectioned plain text, parsed deterministically in code (not by the LLM). Card names can contain commas.

  ```
  Legend:
  1 Viktor, Herald of the Arcane

  Champion:
  1 Viktor, Innovator

  MainDeck:
  3 Consult the Past
  <...>

  Battlefields:
  1 Ravenbloom Conservatory
  <...>

  Runes:
  6 Mind Rune
  6 Order Rune

  Sideboard:
  3 Salvage
  <...>
  ```
- **Validation at import:** resolve each line to a real card (suggest fixes for unknown names) plus basic structural checks (section counts, copy limits) shown as warnings, not blocking. The numbers must be configurable constants filled in from the official rules. They are **not verified yet**.
- **Management:** decks are created, edited and saved on a separate Decks page (paste text or upload a `.txt`), stored per account, and referenced by name with `@` in chat.

### Agent and retrieval
- **Backend stack:** FastAPI with LangChain and LangGraph. Database access via SQLAlchemy with Alembic migrations.
- **Providers:** Gemini free tier as primary, Groq second, OpenRouter third, as a configurable fallback chain.
- **LangGraph v1 (corrective-RAG-lite):** resolve card references (including query translation to English) -> retrieve rules -> grade evidence -> answer with citations, or abstain/ask a clarifying question. One retry with a rewritten query if evidence is weak. No router yet (added when other use cases arrive).
- **Retrieval:** chunk by rule number and section (keep rule id and parent section as metadata), hybrid search (keyword + vector) in Postgres/pgvector. FAQs are chunked separately and tagged by source type and date.
- **Embeddings:** small embedding model (e.g. bge-small via an ONNX runtime) running inside the backend. Documents embedded once at ingestion, queries embedded at runtime with the same model. This is not the chat LLM.

### Data and storage
- **Database and auth:** Supabase (Auth plus Postgres with pgvector). Note: free projects pause after inactivity, so plan a keep-alive ping.
- **Conversations:** own `conversations` and `messages` tables only. No LangGraph checkpointer in v1. Each request loads message history and runs the graph fresh.
- **Source content:** the rules text, FAQs and card snapshot are committed to the repo. Must add Riot's required fan-content disclaimer to the README and record an ADR. The exact policy wording is **not verified**.

### API and frontend
- **Frontend stack:** Vite + React + TypeScript, TanStack Query, and assistant-ui **primitives** (unstyled). No Tailwind and no shadcn. Our own CSS tokens and the aesthetics are defined later.
- **Transport:** SSE over `POST /conversations/{id}/messages`, consumed with `fetch`. The frontend sends the Supabase JWT and the backend verifies it.
- **Events:** `start` (message id and trace id), `status` (graph step), `token`, `final` (full text, validated cards, citations) and `error`.
- **assistant-ui integration:** a custom runtime adapter over our SSE endpoint. The trace id, validated cards and citations are carried in message metadata.
- **Card validation:** done once at the end of generation. During streaming the UI hides the `[[ ]]` markup, then upgrades validated cards to previews on `final`.

### Abuse protection
- Per-user limits: a Postgres daily counter plus a small in-memory per-minute throttle.
- Input caps on message length, decklist size and history length sent to the LLM.
- Email confirmation is required where the provider supports it. No CAPTCHA for now.
- A clear "demo quota reached" message when the quota is exhausted.
- The exact numbers are set once the real free-tier limits are verified.

### Repo, tooling and CI
- **Layout:** monorepo with `backend/`, `frontend/`, `data/` (rules, FAQs, card snapshot) and `docs/`.
- **Python:** `uv`, `ruff`, `pytest` and a type checker (pyright or mypy).
- **Frontend:** `pnpm`, Vitest, ESLint and Prettier.
- **CI (GitHub Actions):** lint, types and unit tests on every push. Unit tests cover the decklist parser, `[[Card]]` validation, chunking and graph routing with a fake LLM.
- **Golden-set eval:** a manual or `workflow_dispatch` run, not on every push, to save quota. Scores go to Langfuse and the README.

### Milestones
1. Ingestion, hybrid retrieval and the golden-set eval via CLI.
2. LangGraph agent and Langfuse tracing.
3. FastAPI, Supabase auth and SSE.
4. Frontend chat with assistant-ui.
5. Cards (`@`, `[[ ]]`, hover) and decks.
6. Feedback, rate limits, deploy and README.

### Deferred
- **Backend hosting:** decide at deployment time. The code must be container-based and portable. Memory matters because of the embedding model. Frontend goes on a free static host.

## Remaining before building
- Verify Riot's fan-content policy and what it allows, then write the exact disclaimer wording.
- Fill in the deck-construction numbers from the official rules.
- Verify the free-tier limits (Gemini, Groq, OpenRouter, Supabase, hosting) and set the rate-limit numbers.
- Confirm that hotlinking Rifthunt images is acceptable.
- Confirm Langfuse trace retention for the privacy note.
- Obtain the rules document and the official FAQs for `data/`.
- Pick the backend host at deployment time.
- Find and install a `domain-modeling` skill (not installed at the time of grilling).

## Unverified facts (do not rely on them)
- Riot's fan-content / Riftbound digital-tools policy and what it allows.
- Deck-construction numbers (section sizes, copy limits).
- Exact free-tier limits of Gemini, Groq, OpenRouter, Supabase and the hosting options.
- Whether hotlinking `images.rifthunt.com` is allowed (its docs offer the images but do not explicitly say so).
- Langfuse trace retention on the free plan.
