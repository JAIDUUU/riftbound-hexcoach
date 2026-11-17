import uuid

import pytest

from backend.cards.collapse import Card
from backend.decks.access import DeckAccess
from backend.decks.importing import DEFAULT_MAX_DECKLIST_CHARS
from backend.mentions import UnknownMentionError, resolve_mentions
from backend.turns import Mention, MentionedCard, MentionedDeck
from tests.cards.memory_catalog import InMemoryCardCatalog
from tests.decks.memory_store import InMemoryDeckStore

ALICE = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")
BOB = uuid.UUID("bbbbbbbb-0000-4000-8000-000000000002")


@pytest.fixture
def cards(cards_by_name: dict[str, Card]) -> InMemoryCardCatalog:
    return InMemoryCardCatalog(cards_by_name.values())


def test_a_mentioned_card_brings_its_type_line_and_full_cleaned_text(
    cards: InMemoryCardCatalog, cards_by_name: dict[str, Card]
) -> None:
    sona = cards_by_name["Sona, Harmonious"]

    [mentioned] = resolve_mentions(
        [Mention("card", uuid.UUID(sona.oracle_id))], ALICE, DeckAccess(InMemoryDeckStore(), cards)
    )

    assert mentioned == MentionedCard(
        name="Sona, Harmonious",
        text=(
            "Sona, Harmonious (Champion Unit)\n"
            "At the end of your turn, if I'm at a battlefield, ready up to 4 friendly runes."
        ),
    )


SONA_DECK = """\
Legend:
1 Annie, Dark Child
Champion:
1 Sona, Harmonious
MainDeck:
3 Blazing Scorcher
2 recruit (nx)
1 Recruit
2 Not A Real Card
Runes:
12 Fury Rune
"""


def test_a_mentioned_deck_brings_each_card_name_once_per_section_without_counts(
    cards: InMemoryCardCatalog,
) -> None:
    decks = InMemoryDeckStore()
    deck = decks.create(ALICE, "Sona ramp", SONA_DECK)

    [mentioned] = resolve_mentions([Mention("deck", deck.id)], ALICE, DeckAccess(decks, cards))

    assert mentioned == MentionedDeck(
        name="Sona ramp",
        sections=(
            ("Legend", ("Annie, Dark Child",)),
            ("Champion", ("Sona, Harmonious",)),
            ("MainDeck", ("Blazing Scorcher", "Recruit")),
            ("Runes", ("Fury Rune",)),
        ),
    )


def test_someone_elses_deck_is_refused_like_a_missing_one(cards: InMemoryCardCatalog) -> None:
    decks = InMemoryDeckStore()
    bobs = decks.create(BOB, "Bob's deck", SONA_DECK)
    missing = uuid.uuid4()

    for deck_id in (bobs.id, missing):
        with pytest.raises(UnknownMentionError) as caught:
            resolve_mentions([Mention("deck", deck_id)], ALICE, DeckAccess(decks, cards))
        assert caught.value.mention == Mention("deck", deck_id)


def test_an_unknown_card_id_is_refused(cards: InMemoryCardCatalog) -> None:
    unknown = Mention("card", uuid.UUID("00000000-0000-4000-8000-000000000000"))

    with pytest.raises(UnknownMentionError, match="No card with id"):
        resolve_mentions([unknown], ALICE, DeckAccess(InMemoryDeckStore(), cards))


def test_mentions_keep_request_order_and_a_repeated_one_comes_through_once(
    cards: InMemoryCardCatalog, cards_by_name: dict[str, Card]
) -> None:
    sona, annie = (
        Mention("card", uuid.UUID(cards_by_name[name].oracle_id))
        for name in ("Sona, Harmonious", "Annie, Dark Child")
    )

    resolved = resolve_mentions([sona, annie, sona], ALICE, DeckAccess(InMemoryDeckStore(), cards))

    assert [m.name for m in resolved] == ["Sona, Harmonious", "Annie, Dark Child"]


def test_a_deck_saved_before_the_size_cap_was_lowered_can_still_be_mentioned(
    cards: InMemoryCardCatalog,
) -> None:
    decks = InMemoryDeckStore()
    long_ago = SONA_DECK + "\n" * DEFAULT_MAX_DECKLIST_CHARS
    deck = decks.create(ALICE, "Sona ramp", long_ago)

    [mentioned] = resolve_mentions([Mention("deck", deck.id)], ALICE, DeckAccess(decks, cards))

    assert isinstance(mentioned, MentionedDeck)
    assert mentioned.name == "Sona ramp"
