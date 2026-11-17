"""@ mentions (issue #18): the Cards and Decks a player picked in the composer, resolved
into what the agent sees for that turn.

A mention names its kind and an id, so a Card and a Deck with the same name never clash.
Card ids are oracle ids, the `id` of the client card index the `@` menu searches
(cards/client_index.py). Deck ids are the player's own saved decks; someone else's deck is
indistinguishable from a missing one. A mention that doesn't resolve refuses the whole
message, before anything is stored or run.

Cards are injected with their full text. Decks are injected as card names only: each
Card once, by oracle name, under its section, without counts or text; lines that don't
resolve to a Card are left out (the agent can still `lookup_card` any name it needs).
"""

import uuid
from collections.abc import Sequence

from backend.cards.catalog import CardCatalog
from backend.cards.chunk_text import card_text_chunk
from backend.decks.importing import import_decklist
from backend.decks.store import DeckStore
from backend.turns import Mention, Mentioned, MentionedCard, MentionedDeck


class UnknownMentionError(LookupError):
    """A mention whose Card doesn't exist, or whose Deck isn't the player's."""

    def __init__(self, mention: Mention) -> None:
        self.mention = mention
        super().__init__(f"No {mention.kind} with id {mention.id}.")


def _card(mention: Mention, cards: CardCatalog) -> MentionedCard:
    card = cards.find_by_id(mention.id)
    if card is None:
        raise UnknownMentionError(mention)
    return MentionedCard(name=card.oracle_name, text=card_text_chunk(card))


def _deck(
    mention: Mention, user_id: uuid.UUID, decks: DeckStore, cards: CardCatalog
) -> MentionedDeck:
    deck = decks.get(user_id, mention.id)
    if deck is None:
        raise UnknownMentionError(mention)
    names: dict[str, dict[str, None]] = {}  # section -> oracle names, both in first-seen order
    for resolved in import_decklist(deck.decklist, cards, max_chars=None).lines:
        if resolved.card is not None:
            names.setdefault(resolved.line.section, {})[resolved.card.oracle_name] = None
    return MentionedDeck(
        name=deck.name,
        sections=tuple((section, tuple(cards_in)) for section, cards_in in names.items()),
    )


def resolve_mentions(
    mentions: Sequence[Mention], user_id: uuid.UUID, decks: DeckStore, cards: CardCatalog
) -> tuple[Mentioned, ...]:
    """The mentions in request order, a repeated one once; raises UnknownMentionError."""
    return tuple(
        _card(mention, cards) if mention.kind == "card" else _deck(mention, user_id, decks, cards)
        for mention in dict.fromkeys(mentions)
    )
