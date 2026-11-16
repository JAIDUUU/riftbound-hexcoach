from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Connection, func, select

from backend.retrieval.repository import replace_rules, search_chunks
from backend.retrieval.schema import chunks_table
from backend.rules.parse import parse_rules

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).parent.parent / "fixtures" / "core_rules_sample.txt"
RULES_DATE = date(2026, 10, 9)


@pytest.fixture
def ingested(db_connection: Connection) -> Connection:
    replace_rules(db_connection, parse_rules(FIXTURE.read_text(encoding="utf-8")), RULES_DATE)
    return db_connection


def _count(connection: Connection) -> int:
    return connection.execute(select(func.count()).select_from(chunks_table)).scalar_one()


def test_search_finds_a_rule_by_keywords(ingested: Connection) -> None:
    hits = search_chunks(ingested, "forbid actions")

    assert hits
    assert hits[0].rule_id == "054.1"
    assert hits[0].section == "\u201cCan\u2019t beats Can\u201d"
    assert hits[0].source_type == "rules"
    assert hits[0].source_version == "2026-10-09"
    assert hits[0].source_date == RULES_DATE


def test_reingesting_keeps_a_single_rules_version(ingested: Connection) -> None:
    before = _count(ingested)

    replace_rules(ingested, parse_rules(FIXTURE.read_text(encoding="utf-8")), RULES_DATE)

    assert _count(ingested) == before


def test_search_without_matches_returns_nothing(ingested: Connection) -> None:
    assert search_chunks(ingested, "xyzzy plugh") == []


def test_ingesting_an_empty_document_is_refused(db_connection: Connection) -> None:
    with pytest.raises(ValueError, match="empty"):
        replace_rules(db_connection, [], RULES_DATE)
