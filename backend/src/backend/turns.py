"""What a chat turn is made of, as plain data: the conversation's earlier turns and the
Cards and Decks the player @-mentioned.

The conversation store, the API, mention resolution and the agent graph all speak these
types, so they live here rather than in any one of them: the store and the mention
resolver never depend on the LangGraph module, and the agent never depends on the store.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from backend.cards.chunk_text import card_text_chunk
from backend.cards.collapse import Card

Role = Literal["user", "assistant"]
Turn = tuple[Role, str]
"""One conversation turn, oldest first in a history."""


class _HasRole(Protocol):
    @property
    def role(self) -> Role: ...


def answered[T: _HasRole](history: Sequence[T]) -> list[T]:
    """The history without the questions that got no answer.

    A run that fails keeps the player's question (they saw it sent) but stores no answer,
    so a stored conversation can hold two user turns in a row. The model is only shown
    questions together with the answer that followed them.
    """
    return [
        message
        for i, message in enumerate(history)
        if message.role == "assistant"
        or (i + 1 < len(history) and history[i + 1].role == "assistant")
    ]


MentionKind = Literal["card", "deck"]


@dataclass(frozen=True, slots=True)
class Mention:
    """An @ mention as the player sent it: a Card by oracle id, or one of their Decks."""

    kind: MentionKind
    id: uuid.UUID


@dataclass(frozen=True, slots=True)
class MentionedCard:
    """A Card the player @-mentioned."""

    card: Card

    @property
    def name(self) -> str:
        return self.card.oracle_name

    @property
    def text(self) -> str:
        """Name, type line and cleaned text, as lookup_card returns them."""
        return card_text_chunk(self.card)


@dataclass(frozen=True, slots=True)
class DeckSection:
    name: str
    cards: tuple[str, ...]  # oracle names, each once, in first-seen order
    unrecognised: tuple[str, ...] = ()  # names that match no Card, as written


@dataclass(frozen=True, slots=True)
class MentionedDeck:
    """A Deck the player @-mentioned, as card names only: no counts and no card text."""

    name: str
    sections: tuple[DeckSection, ...]  # in decklist order


Mentioned = MentionedCard | MentionedDeck
"""What one @ mention puts into the turn's context (resolved by backend.mentions)."""
