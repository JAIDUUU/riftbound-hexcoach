"""Static card index for the frontend `@` menu (a plain JSON-serialisable structure)."""

from collections.abc import Sequence
from typing import Any

from backend.cards.collapse import Card


def build_client_index(cards: Sequence[Card]) -> dict[str, Any]:
    return {
        "fetched": cards[0].snapshot_fetched.isoformat() if cards else None,
        "cards": [
            {
                "id": card.oracle_id,
                "name": card.oracle_name,
                "aliases": list(card.aliases),
                "type": card.card_type,
                "domains": list(card.domains),
                "image": card.image_path,
            }
            for card in cards
        ],
    }
