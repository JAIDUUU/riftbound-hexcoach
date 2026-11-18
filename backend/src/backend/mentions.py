"""@ mentions (issue #18): the Cards and Decks a player picked in the composer, resolved
into what the agent sees for that turn.

A mention names its kind and an id, so a Card and a Deck with the same name never clash.
Card ids are oracle ids, the `id` of the client card index the `@` menu searches
(cards/client_index.py). Deck ids are the player's own saved decks; someone else's deck is
indistinguishable from a missing one. A mention that doesn't resolve refuses the whole
message, before anything is stored or run.

Cards are injected with their full text. Decks are injected as card names only: each
Card once, by oracle name, under its section, without counts or text. Lines that don't
resolve to a Card are kept apart, as written, so the agent knows the deck holds cards it
can't identify rather than taking the rest for the whole deck.
"""

import uuid
from collections.abc import Sequence

from backend.cards.catalog import CardCatalog
from backend.decks.access import DeckAccess
from backend.turns import DeckSection, Mention, Mentioned, MentionedCard, MentionedDeck


class UnknownMentionError(LookupError):
    """A mention whose Card doesn't exist, or whose Deck isn't the player's."""

    def __init__(self, mention: Mention) -> None:
        self.mention = mention
        super().__init__(f"No {mention.kind} with id {mention.id}.")


def _card(mention: Mention, cards: CardCatalog) -> MentionedCard:
    card = cards.find_by_id(str(mention.id))
    if card is None:
        raise UnknownMentionError(mention)
    return MentionedCard(card)


def _deck(mention: Mention, user_id: uuid.UUID, access: DeckAccess) -> MentionedDeck:
    deck = access.decks.get(user_id, mention.id)
    if deck is None:
        raise UnknownMentionError(mention)
    # Dicts with None values serve as ordered sets: each name once, in first-seen order.
    cards: dict[str, dict[str, None]] = {}  # section -> oracle names
    unrecognised: dict[str, dict[str, None]] = {}  # section -> names as written
    for resolved in access.import_saved(deck).lines:
        section = resolved.line.section
        cards.setdefault(section, {})
        unrecognised.setdefault(section, {})
        if resolved.card is not None:
            cards[section][resolved.card.oracle_name] = None
        else:
            unrecognised[section][resolved.line.name] = None
    return MentionedDeck(
        name=deck.name,
        sections=tuple(
            DeckSection(section, tuple(cards[section]), tuple(unrecognised[section]))
            for section in cards
        ),
    )


def resolve_mentions(
    mentions: Sequence[Mention], user_id: uuid.UUID, access: DeckAccess
) -> tuple[Mentioned, ...]:
    """The mentions in request order, a repeated one once; raises UnknownMentionError."""
    return tuple(
        _card(mention, access.cards) if mention.kind == "card" else _deck(mention, user_id, access)
        for mention in dict.fromkeys(mentions)
    )
