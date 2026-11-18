"""Persistence for Cards: sync a collapsed snapshot into Postgres and look cards up by name."""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any

from sqlalchemy import Connection, delete, select, text
from sqlalchemy.dialects.postgresql import insert

from backend.cards.collapse import Card
from backend.cards.schema import cards_table

_LIST_FIELDS = ("aliases", "domains", "tags")

_FIND_BY_NAME = text(
    """
    SELECT * FROM cards
    WHERE lower(oracle_name) = :name
       OR EXISTS (SELECT 1 FROM unnest(aliases) AS alias WHERE lower(alias) = :name)
    ORDER BY (lower(oracle_name) = :name) DESC
    LIMIT 1
    """
)


def _to_row(card: Card) -> dict[str, Any]:
    row = asdict(card)
    row["oracle_id"] = uuid.UUID(card.oracle_id)
    for field in _LIST_FIELDS:
        row[field] = list(row[field])
    return row


def _card_from_row(row: Mapping[str, Any]) -> Card:
    fields = dict(row)
    fields["oracle_id"] = str(fields["oracle_id"])
    for field in _LIST_FIELDS:
        fields[field] = tuple(fields[field])
    return Card(**fields)


def sync_cards(connection: Connection, cards: Sequence[Card]) -> int:
    """Make the cards table match `cards`: upsert every card, delete the ones no longer present.

    Safe to run repeatedly. Returns the number of cards written.
    """
    if not cards:
        raise ValueError("Refusing to sync an empty card list (it would delete every card).")
    statement = insert(cards_table).values([_to_row(card) for card in cards])
    updates = {
        column.name: statement.excluded[column.name]
        for column in cards_table.columns
        if column.name != "oracle_id"
    }
    connection.execute(statement.on_conflict_do_update(index_elements=["oracle_id"], set_=updates))
    keep = [uuid.UUID(card.oracle_id) for card in cards]
    connection.execute(delete(cards_table).where(cards_table.c.oracle_id.not_in(keep)))
    return len(cards)


def find_by_oracle_name(connection: Connection, name: str) -> Card | None:
    """Find a card by oracle name or alias, ignoring case. Printings never matter."""
    row = connection.execute(_FIND_BY_NAME, {"name": name.strip().lower()}).mappings().first()
    return _card_from_row(dict(row)) if row else None


def find_by_oracle_id(connection: Connection, oracle_id: str) -> Card | None:
    """The card with this oracle id, or None (also for text that isn't a uuid)."""
    try:
        key = uuid.UUID(oracle_id)
    except ValueError:
        return None
    statement = select(cards_table).where(cards_table.c.oracle_id == key)
    row = connection.execute(statement).mappings().first()
    return _card_from_row(dict(row)) if row else None


_ALL_NAMES = text(
    """
    SELECT oracle_name AS name FROM cards
    UNION
    SELECT unnest(aliases) FROM cards
    """
)


def all_card_names(connection: Connection) -> list[str]:
    """Every name a lookup would match - oracle names and aliases - so close-match
    suggestions can point at whichever spelling the player was reaching for."""
    return [str(name) for name in connection.execute(_ALL_NAMES).scalars()]
