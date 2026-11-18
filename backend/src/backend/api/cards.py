"""The Cards an answer tags, as the API sends them: in a turn's `final` event and again
on every stored answer the player reloads (ADR 0005).

Tags are checked against the card catalog whenever an answer is sent, so a reloaded answer
shows the same previews `final` did, against the catalog as it is now.
"""

import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager

from pydantic import BaseModel

from backend.cards.catalog import CardCatalog
from backend.cards.images import preview_image_url
from backend.cards.tags import ValidatedCard, validate_card_tags

_log = logging.getLogger(__name__)

OpenCards = Callable[[], AbstractContextManager[CardCatalog]]
"""Opens the card catalog that answers' Card tags are checked against."""


class CardOut(BaseModel):
    """A Card the answer tags: what a hover preview shows, and its text fallback.

    `tags` is every distinct way the answer wrote the card (trimmed), so the client can
    match each `[[...]]` in `text` to its card; a tag listed nowhere is plain text.
    """

    oracle_id: str
    oracle_name: str
    tags: list[str]
    image_url: str
    cleaned_text: str

    @classmethod
    def of(cls, validated: ValidatedCard) -> "CardOut":
        card = validated.card
        return cls(
            oracle_id=card.oracle_id,
            oracle_name=card.oracle_name,
            tags=list(validated.tags),
            image_url=preview_image_url(card),
            cleaned_text=card.cleaned_text,
        )


def validated_cards_each(
    answers: Sequence[str], open_cards: OpenCards | None
) -> list[list[CardOut]]:
    """The Cards each answer tags, in order, checked through one open catalog.

    The answers are already delivered or stored, so a failure here leaves every tag as
    plain text rather than failing the response.
    """
    if open_cards is None or not answers:
        return [[] for _ in answers]
    try:
        with open_cards() as cards:
            return [
                [CardOut.of(validated) for validated in validate_card_tags(answer, cards)]
                for answer in answers
            ]
    except Exception:
        _log.exception("Card tags could not be validated; sending them as plain text")
        return [[] for _ in answers]


def validated_cards(answer: str, open_cards: OpenCards | None) -> list[CardOut]:
    [cards] = validated_cards_each([answer], open_cards)
    return cards
