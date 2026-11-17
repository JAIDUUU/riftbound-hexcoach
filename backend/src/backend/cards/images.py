"""The hover-preview image for a Card: Rifthunt's "normal" (480 wide) WebP, hotlinked (ADR 0002).

UNVERIFIED on two counts:
- Hotlinking: Rifthunt's terms cover images.rifthunt.com but don't say hotlinking is
  allowed. Previews fall back to the card's cleaned text when an image fails.
- The URL shape: Rifthunt documents `images.normal` only on its per-card API objects, and
  the bulk snapshot we ingest doesn't carry it, so the URL is rebuilt from the
  representative printing's set, collector number and name. Checked on 2026-11-17 against
  the API's URL for every one of the 1110 Cards in the 2026-11-06 snapshot. The bulk
  `img` path ADR 0002 planned to prefix is legacy and 404s on this host.

The API's URLs end in `?v=<imgHash>`; the hash is internal to Rifthunt and not stored, and
the host serves the image without it.
"""

import re

from backend.cards.collapse import Card

_HOST = "https://images.rifthunt.com"
_NOT_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(name: str) -> str:
    return _NOT_SLUG.sub("-", name.lower().replace("'", "")).strip("-")


def preview_image_url(card: Card) -> str:
    return (
        f"{_HOST}/cards/normal/front/{card.set_code.lower()}/{card.collector_number}/"
        f"{_slug(card.oracle_name)}.webp"
    )
