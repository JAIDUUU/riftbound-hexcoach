import pytest
from sqlalchemy import Connection, func, select

from backend.cards.collapse import collapse_printings
from backend.cards.repository import find_by_oracle_name, sync_cards
from backend.cards.rifthunt import RifthuntSnapshot
from backend.cards.schema import cards_table

pytestmark = pytest.mark.integration


def _count(connection: Connection) -> int:
    return connection.execute(select(func.count()).select_from(cards_table)).scalar_one()


def test_a_synced_card_is_found_by_oracle_name_ignoring_case(
    db_connection: Connection, rifthunt_sample: RifthuntSnapshot
) -> None:
    sync_cards(db_connection, collapse_printings(rifthunt_sample))

    sona = find_by_oracle_name(db_connection, "  sona, HARMONIOUS ")

    assert sona is not None
    assert sona.oracle_name == "Sona, Harmonious"
    assert sona.cleaned_text == (
        "At the end of your turn, if I'm at a battlefield, ready up to 4 friendly runes."
    )
    assert sona.representative_id == "ven-sp2-006"


def test_an_alias_finds_the_same_card(
    db_connection: Connection, rifthunt_sample: RifthuntSnapshot
) -> None:
    sync_cards(db_connection, collapse_printings(rifthunt_sample))

    recruit = find_by_oracle_name(db_connection, "recruit (nx)")

    assert recruit is not None
    assert recruit.oracle_name == "Recruit"
    assert recruit.aliases == ("Recruit (DE)", "Recruit (NX)", "Recruit (ZN)")


def test_an_unknown_name_finds_nothing(
    db_connection: Connection, rifthunt_sample: RifthuntSnapshot
) -> None:
    sync_cards(db_connection, collapse_printings(rifthunt_sample))

    assert find_by_oracle_name(db_connection, "Not A Real Card") is None


def test_syncing_twice_is_idempotent_and_keeps_every_field(
    db_connection: Connection, rifthunt_sample: RifthuntSnapshot
) -> None:
    cards = collapse_printings(rifthunt_sample)

    sync_cards(db_connection, cards)
    sync_cards(db_connection, cards)

    assert _count(db_connection) == 8
    stored = find_by_oracle_name(db_connection, "Blazing Scorcher")
    assert stored == next(card for card in cards if card.oracle_name == "Blazing Scorcher")


def test_syncing_a_smaller_snapshot_removes_cards_that_are_gone(
    db_connection: Connection, rifthunt_sample: RifthuntSnapshot
) -> None:
    cards = collapse_printings(rifthunt_sample)
    sync_cards(db_connection, cards)

    sync_cards(db_connection, cards[:3])

    assert _count(db_connection) == 3
    assert find_by_oracle_name(db_connection, "Sona, Harmonious") is None


def test_syncing_an_empty_snapshot_is_refused(db_connection: Connection) -> None:
    with pytest.raises(ValueError, match="empty"):
        sync_cards(db_connection, [])
