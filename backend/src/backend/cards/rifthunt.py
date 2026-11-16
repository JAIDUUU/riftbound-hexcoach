"""The shape of Rifthunt's `/bulk/cards` payload, limited to the fields the pipeline reads.

The payload carries more fields (artist, prices, hashes); they are preserved untouched on
write and simply not declared here. The snapshot validation in `backend.cards.snapshot`,
the single boundary where the payload enters, enforces the presence of every field below
and the vocabulary unions at runtime; primitive field types are trusted.
"""

from typing import TypedDict

from backend.cards.vocabulary import CardType, Domain, Rarity, Supertype


class RifthuntPrinting(TypedDict):
    """One printing of one card, as Rifthunt ships it."""

    # Identity. `id` is legacy: only its `tcg:` / `dotgg:` prefix is read (see ADR 0002).
    id: str
    oracle_id: str
    printing_id: str
    riftboundId: str
    set: str
    name: str
    cleanName: str
    # Variant markers: alternate art, signature, overnumbered.
    alt: bool
    sig: bool
    over: bool
    # The card face.
    type: CardType
    supertype: Supertype | None
    domains: list[Domain]
    energy: int | None
    might: int | None
    power: int | None
    rarity: Rarity
    tags: list[str]
    text: str | None
    img: str | None
    imgUrl: str


class RifthuntSet(TypedDict):
    id: str
    name: str
    count: int
    released: str


class RifthuntSnapshot(TypedDict):
    fetched: str
    sets: list[RifthuntSet]
    cards: list[RifthuntPrinting]
