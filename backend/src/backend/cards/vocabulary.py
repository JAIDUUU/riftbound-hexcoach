"""Closed vocabularies of Riftbound card attributes.

Snapshot validation (`backend.cards.snapshot`) rejects values outside these unions, so a
new set that introduces a value fails the manual refresh until the union here is extended.
Open-ended attributes (set codes, tags) stay plain strings.
"""

from typing import Literal, get_args

CardType = Literal["Battlefield", "Gear", "Legend", "Rune", "Spell", "Unit"]
Supertype = Literal["Basic", "Champion", "Signature", "Token"]
Domain = Literal["Body", "Calm", "Chaos", "Colorless", "Fury", "Mind", "Order"]
Rarity = Literal["Common", "Epic", "Promo", "Rare", "Showcase", "Uncommon"]

CARD_TYPES: frozenset[str] = frozenset(get_args(CardType))
SUPERTYPES: frozenset[str] = frozenset(get_args(Supertype))
DOMAINS: frozenset[str] = frozenset(get_args(Domain))
RARITIES: frozenset[str] = frozenset(get_args(Rarity))
