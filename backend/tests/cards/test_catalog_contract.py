"""Matching rules every CardCatalog must honour.

Each test runs against the in-memory fake (always) and the cards table (only with
`pytest -m integration`), which keeps the fake behind the decklist tests honest.
"""

import uuid
from collections.abc import Callable
from typing import cast

import pytest
from sqlalchemy import Connection

from backend.cards.catalog import CardCatalog, SqlCardCatalog
from backend.cards.collapse import Card
from backend.cards.repository import sync_cards
from tests.cards.memory_catalog import InMemoryCardCatalog

CatalogOf = Callable[[list[Card]], CardCatalog]


@pytest.fixture(params=["memory", pytest.param("sql", marks=pytest.mark.integration)])
def catalog_of(request: pytest.FixtureRequest) -> CatalogOf:
    def build(cards: list[Card]) -> CardCatalog:
        if cast(str, request.param) == "memory":
            return InMemoryCardCatalog(cards)
        connection = cast(Connection, request.getfixturevalue("db_connection"))
        sync_cards(connection, cards)
        return SqlCardCatalog(connection)

    return build


def test_cards_are_found_by_oracle_name_or_alias_ignoring_case_and_spacing(
    catalog_of: CatalogOf, cards_by_name: dict[str, Card]
) -> None:
    catalog = catalog_of(list(cards_by_name.values()))

    sona = catalog.find("  sona, HARMONIOUS ")
    recruit = catalog.find("RECRUIT (nx)")

    assert sona is not None and sona.oracle_name == "Sona, Harmonious"
    assert recruit is not None and recruit.oracle_name == "Recruit"
    assert catalog.find("Not A Real Card") is None


def test_an_oracle_name_beats_another_cards_alias(
    catalog_of: CatalogOf, cards_by_name: dict[str, Card], poro_claiming_sonas_name: Card
) -> None:
    others = [card for name, card in cards_by_name.items() if name != "Pouty Poro"]
    catalog = catalog_of([*others, poro_claiming_sonas_name])

    found = catalog.find("Sona, Harmonious")

    assert found is not None and found.oracle_name == "Sona, Harmonious"


def test_cards_are_found_by_oracle_id(
    catalog_of: CatalogOf, cards_by_name: dict[str, Card]
) -> None:
    catalog = catalog_of(list(cards_by_name.values()))
    sona = cards_by_name["Sona, Harmonious"]

    found = catalog.find_by_id(uuid.UUID(sona.oracle_id))

    assert found is not None and found.oracle_name == "Sona, Harmonious"
    assert catalog.find_by_id(uuid.UUID("00000000-0000-4000-8000-000000000000")) is None


def test_all_names_carries_oracle_names_and_aliases(
    catalog_of: CatalogOf, cards_by_name: dict[str, Card]
) -> None:
    catalog = catalog_of(list(cards_by_name.values()))

    names = set(catalog.all_names())

    assert {"Recruit", "Recruit (NX)", "Sona, Harmonious"} <= names
