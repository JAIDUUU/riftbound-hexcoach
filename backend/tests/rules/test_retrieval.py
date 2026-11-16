from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Connection, func, select

from backend.retrieval.embedding import EMBEDDING_DIMENSIONS
from backend.retrieval.repository import (
    ChunkRecord,
    hybrid_search_chunks,
    replace_chunks,
    replace_rules,
    search_chunks,
    vector_search_chunks,
)
from backend.retrieval.schema import chunks_table
from backend.rules.parse import RuleChunk, parse_rules

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).parent.parent / "fixtures" / "core_rules_sample.txt"
RULES_DATE = date(2026, 10, 9)


def fake_embeddings(chunks: list[RuleChunk]) -> list[list[float]]:
    """Deterministic stand-ins so these tests never download the real model.

    Each chunk gets a one-hot-ish vector in its own dimension, so cosine distance
    ranks a query vector closest to the chunk whose dimension it points at.
    """
    vectors: list[list[float]] = []
    for index in range(len(chunks)):
        vector = [0.0] * EMBEDDING_DIMENSIONS
        vector[index % EMBEDDING_DIMENSIONS] = 1.0
        vectors.append(vector)
    return vectors


def pointing_at(index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[index] = 1.0
    return vector


@pytest.fixture
def chunks() -> list[RuleChunk]:
    return parse_rules(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def ingested(db_connection: Connection, chunks: list[RuleChunk]) -> Connection:
    replace_rules(db_connection, chunks, RULES_DATE, fake_embeddings(chunks))
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


def test_vector_search_ranks_by_cosine_distance(
    ingested: Connection, chunks: list[RuleChunk]
) -> None:
    hits = vector_search_chunks(ingested, pointing_at(3), limit=1)

    assert [hit.rule_id for hit in hits] == [chunks[3].rule_id]


def test_hybrid_surfaces_a_vector_hit_with_no_keyword_overlap(
    ingested: Connection, chunks: list[RuleChunk]
) -> None:
    # A query with no words from the corpus: FTS finds nothing, the vector side must.
    hits = hybrid_search_chunks(ingested, "xyzzy plugh", pointing_at(5), limit=3)

    assert hits
    assert hits[0].rule_id == chunks[5].rule_id


def test_hybrid_merges_both_rankings(ingested: Connection, chunks: list[RuleChunk]) -> None:
    keyword_top = search_chunks(ingested, "forbid actions", limit=1)[0]
    vector_index = next(
        i for i, chunk in enumerate(chunks) if chunk.rule_id not in (keyword_top.rule_id,)
    )

    hits = hybrid_search_chunks(ingested, "forbid actions", pointing_at(vector_index), limit=5)
    rule_ids = [hit.rule_id for hit in hits]

    assert keyword_top.rule_id in rule_ids
    assert chunks[vector_index].rule_id in rule_ids


def test_reingesting_keeps_a_single_rules_version(
    ingested: Connection, chunks: list[RuleChunk]
) -> None:
    before = _count(ingested)

    replace_rules(ingested, chunks, RULES_DATE, fake_embeddings(chunks))

    assert _count(ingested) == before


def test_search_without_matches_returns_nothing(ingested: Connection) -> None:
    assert search_chunks(ingested, "xyzzy plugh") == []


def test_search_returns_chunks_from_all_three_sources(ingested: Connection) -> None:
    faq = ChunkRecord(
        text="Q: Does the zorblax rule apply?\nA: Yes, the zorblax rule always applies.",
        embedding=pointing_at(100),
        source_version="OGN",
        source_date=date(2025, 10, 16),
        section="Scoring",
        title="Riftbound Origins FAQ",
        source_url="https://example.com/origins-faq/",
    )
    card = ChunkRecord(
        text="Snackbeast (Unit)\nWhen you play me, zorblax a unit.",
        embedding=pointing_at(101),
        source_version="2026-11-06",
        source_date=date(2026, 11, 6),
        title="Snackbeast",
    )
    replace_chunks(ingested, "faq", [faq])
    replace_chunks(ingested, "card_text", [card])

    hits = search_chunks(ingested, "zorblax")

    assert {hit.source_type for hit in hits} == {"faq", "card_text"}
    faq_hit = next(hit for hit in hits if hit.source_type == "faq")
    assert faq_hit.title == "Riftbound Origins FAQ"
    assert faq_hit.source_url == "https://example.com/origins-faq/"
    assert faq_hit.source_date == date(2025, 10, 16)
    # Re-replacing one source leaves the others alone.
    replace_chunks(ingested, "faq", [faq])
    assert {hit.source_type for hit in search_chunks(ingested, "zorblax")} == {
        "faq",
        "card_text",
    }


def test_ingesting_an_empty_document_is_refused(db_connection: Connection) -> None:
    with pytest.raises(ValueError, match="empty"):
        replace_rules(db_connection, [], RULES_DATE, [])


def test_misaligned_embeddings_are_refused(
    db_connection: Connection, chunks: list[RuleChunk]
) -> None:
    with pytest.raises(ValueError, match="embeddings"):
        replace_rules(db_connection, chunks, RULES_DATE, fake_embeddings(chunks)[:-1])
