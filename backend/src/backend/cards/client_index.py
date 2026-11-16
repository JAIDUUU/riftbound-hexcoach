"""Static card index for the frontend `@` menu (a plain JSON-serialisable structure)."""

from collections.abc import Sequence
from typing import TypedDict

from backend.cards.collapse import Card
from backend.cards.vocabulary import CardType, Domain


class ClientIndexEntry(TypedDict):
    id: str
    name: str
    aliases: list[str]
    type: CardType
    domains: list[Domain]
    image: str | None


class ClientIndex(TypedDict):
    fetched: str | None
    cards: list[ClientIndexEntry]


def build_client_index(cards: Sequence[Card]) -> ClientIndex:
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
