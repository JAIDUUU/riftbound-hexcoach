# 0002: Card data is a committed Rifthunt snapshot

Status: accepted

## Context
We need card data without budget and without applying for Riot's API key. Options considered: Rifthunt (`api.rifthunt.com`), Riftcodex, and a scraper of Riot's undocumented site endpoint. Rifthunt needs no key, offers one bulk download of the whole catalogue (about 1.2 MB), has stable ids and image URLs, and states that its data is free for any use as unofficial Riot Fan Content. Riftcodex's docs were unavailable when checked. The scraper depends on a build id that can break.

## Decision
- Commit a snapshot of Rifthunt `/bulk/cards` to `data/`, stamped with the date we downloaded it (not any date upstream claims), refreshed by the manual `backend refresh-cards` CLI command. The app makes no runtime calls to Rifthunt. `backend load-cards` makes the database match the snapshot: every card is upserted and cards no longer in the snapshot are deleted.
- A Card is one `oracle_id`. Printings collapse into one representative printing, matched on `oracle_name` (Rifthunt's `cleanName`; there is no `oracle_name` field).
- Printing text is **not** always identical (checked against the live bulk data: 104 cards differ). Newer sets drop reminder text and some cards are reworded. The representative printing is chosen by: plain (not alternate, signature, overnumbered or name-suffixed) over variant, then official over third-party (`tcg:` / `dotgg:`), then the latest set release (current wording, at the cost of reminder text), then lowest `riftboundId`.
- Other names sharing an `oracle_id` (for example `Recruit (DE)`, `Recruit (NX)`, `Recruit (ZN)`) are stored as aliases and match lookups.
- Store raw and cleaned text. Cleaning rewrites `:rb_*:` icon shortcodes as words (`:rb_energy_2:` becomes "2 Energy", `:rb_rune_fury:` becomes "Fury Rune"), strips keyword brackets, drops `[NO TEXT]`, turns the cost arrows `[>]` and `[>>]` into "→" and "⇒" (the meaning of `[>>]` is unverified), and removes blank lines. Unknown shortcodes are left visible and reported by `refresh-cards` and `load-cards`, which also warn when a name or alias would look up more than one card.
- The database is Supabase Postgres from the start (no local database). The direct connection is IPv6-only, so development uses the session pooler.
- Images are hotlinked from `images.rifthunt.com` and not stored. The snapshot's `img` field is a path relative to that host (for example `cards/ogn-001-298.png`); it is kept as `image_path` in the database and as `image` in the client index, and the frontend builds the URL by prefixing `https://images.rifthunt.com/`. Printings without `img` fall back to the stored `image_url` (Rifthunt's `imgUrl`), then to text.
  - Amended for issue #15 (2026-11-17): Rifthunt's docs now call `img` a legacy file name, not a URL, and the prefixed path returns 404. The host serves sized WebP copies at `cards/<size>/front/<set>/<collector number>/<name slug>.webp`, documented only on the per-card API objects. Card-tag previews build the "normal" (480 wide) URL from stored fields (`backend/cards/images.py`). This shape is unverified, but it matched every Card in the 2026-11-06 snapshot. `image_path` and the client index's `image` still hold the legacy path.

## Consequences
- Card data is only as fresh as the last refresh. New sets need a manual re-run and a golden-set re-run.
- Per Rifthunt's request, the bulk file is fetched at most daily and not crawled.
- Whether hotlinking images is allowed is unverified. The fallback is to mirror images or use Riot's CDN URLs from the bulk file.
- Card types, supertypes, rarities and domains are closed unions (`backend/cards/vocabulary.py`). Whenever a snapshot is fetched or read, these vocabularies and the presence of every field the pipeline reads are validated; primitive field types are trusted. A new set that introduces a value fails the refresh until the union is extended, which is deliberate: downstream code can then trust the vocabulary.
- The app depends on Rifthunt's bulk format. Deprecated fields (`id`, `oracleId` in the bulk file) must not be used for identity; use `printing_id`, `riftboundId` and `oracle_id`. The only read of the legacy `id` is the `tcg:` / `dotgg:` prefix that marks third-party printings, since nothing else carries that signal.
