"""What a chat turn is made of, as plain data: the conversation's earlier turns and the
Cards and Decks the player @-mentioned.

The conversation store, the API, mention resolution and the agent graph all speak these
types, so they live here rather than in any one of them: the store and the mention
resolver never depend on the LangGraph module, and the agent never depends on the store.
"""

import uuid
from dataclasses import dataclass
from typing import Literal

Role = Literal["user", "assistant"]
Turn = tuple[Role, str]
"""One conversation turn, oldest first in a history."""

MentionKind = Literal["card", "deck"]


@dataclass(frozen=True, slots=True)
class Mention:
    """An @ mention as the player sent it: a Card by oracle id, or one of their Decks."""

    kind: MentionKind
    id: uuid.UUID


@dataclass(frozen=True, slots=True)
class MentionedCard:
    """A Card the player @-mentioned, with its full text."""

    name: str
    text: str  # name, type line and cleaned text, as lookup_card returns them


@dataclass(frozen=True, slots=True)
class MentionedDeck:
    """A Deck the player @-mentioned, as card names only: no counts and no card text."""

    name: str
    sections: tuple[tuple[str, tuple[str, ...]], ...]  # (section, oracle names), in order


Mentioned = MentionedCard | MentionedDeck
"""What one @ mention puts into the turn's context (resolved by backend.mentions)."""
