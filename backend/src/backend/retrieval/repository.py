"""Persistence for chunks: replace a source's chunks and search across all sources.

Two retrieval primitives (Postgres FTS and pgvector cosine distance) plus the hybrid
search that fuses their rankings with reciprocal rank fusion. Hybrid is what callers
should use; the primitives stay public for the keyword-only CLI path and for tests.

Each source type (rules, faq, card_text) is replaced wholesale by its ingest command, so
re-ingesting never duplicates and never leaves stale chunks behind (ADR 0008 for rules).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from sqlalchemy import Connection, delete, insert, text

from backend.retrieval.fusion import fuse_rankings
from backend.retrieval.schema import chunks_table
from backend.rules.parse import RuleChunk

SourceType = Literal["rules", "faq", "card_text"]

_COLUMNS = "id, source_type, rule_id, section, text, source_version, source_date, title, source_url"

_KEYWORD_SEARCH = text(
    f"""
    SELECT {_COLUMNS}
    FROM chunks
    WHERE search @@ websearch_to_tsquery('english', :query)
    ORDER BY ts_rank(search, websearch_to_tsquery('english', :query)) DESC, id
    LIMIT :limit
    """
)

_VECTOR_SEARCH = text(
    f"""
    SELECT {_COLUMNS}
    FROM chunks
    ORDER BY embedding <=> CAST(:embedding AS vector), id
    LIMIT :limit
    """
)


@dataclass(frozen=True, slots=True)
class ChunkRecord:
    """One chunk ready to insert: text, embedding and all source metadata."""

    text: str
    embedding: Sequence[float]
    source_version: str
    source_date: date
    rule_id: str | None = None
    section: str | None = None
    parent_rule_id: str | None = None
    is_heading: bool = False
    title: str | None = None
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk_id: int
    source_type: str
    rule_id: str | None
    section: str | None
    text: str
    source_version: str
    source_date: date
    title: str | None
    source_url: str | None


def replace_chunks(
    connection: Connection, source_type: SourceType, records: Sequence[ChunkRecord]
) -> int:
    """Make `source_type`'s chunks match `records`; other source types are untouched."""
    if not records:
        raise ValueError(f"Refusing to replace {source_type!r} chunks with nothing.")
    connection.execute(delete(chunks_table).where(chunks_table.c.source_type == source_type))
    connection.execute(
        insert(chunks_table),
        [
            {
                "source_type": source_type,
                "rule_id": record.rule_id,
                "section": record.section,
                "parent_rule_id": record.parent_rule_id,
                "is_heading": record.is_heading,
                "text": record.text,
                "source_version": record.source_version,
                "source_date": record.source_date,
                "title": record.title,
                "source_url": record.source_url,
                "embedding": list(record.embedding),
            }
            for record in records
        ],
    )
    return len(records)


def replace_rules(
    connection: Connection,
    chunks: Sequence[RuleChunk],
    source_date: date,
    embeddings: Sequence[Sequence[float]],
) -> int:
    """Replace the rules chunks. `embeddings` must align with `chunks` one to one."""
    if not chunks:
        raise ValueError("Refusing to ingest an empty rules document.")
    if len(embeddings) != len(chunks):
        raise ValueError(f"{len(chunks)} chunks but {len(embeddings)} embeddings.")
    records = [
        ChunkRecord(
            text=chunk.text,
            embedding=embedding,
            source_version=source_date.isoformat(),
            source_date=source_date,
            rule_id=chunk.rule_id,
            section=chunk.section,
            parent_rule_id=chunk.parent_id,
            is_heading=chunk.is_heading,
        )
        for chunk, embedding in zip(chunks, embeddings, strict=True)
    ]
    return replace_chunks(connection, "rules", records)


def _hits(connection: Connection, statement: Any, params: dict[str, object]) -> list[SearchHit]:
    rows = connection.execute(statement, params).mappings()
    return [
        SearchHit(
            chunk_id=row["id"],
            source_type=row["source_type"],
            rule_id=row["rule_id"],
            section=row["section"],
            text=row["text"],
            source_version=row["source_version"],
            source_date=row["source_date"],
            title=row["title"],
            source_url=row["source_url"],
        )
        for row in rows
    ]


def search_chunks(connection: Connection, query: str, limit: int = 10) -> list[SearchHit]:
    """Keyword (FTS) search, best match first. Empty when no term matches."""
    return _hits(connection, _KEYWORD_SEARCH, {"query": query, "limit": limit})


def vector_search_chunks(
    connection: Connection, embedding: Sequence[float], limit: int = 10
) -> list[SearchHit]:
    """Nearest chunks by cosine distance, best match first."""
    embedding_literal = "[" + ",".join(str(value) for value in embedding) + "]"
    return _hits(connection, _VECTOR_SEARCH, {"embedding": embedding_literal, "limit": limit})


def hybrid_search_chunks(
    connection: Connection, query: str, query_embedding: Sequence[float], limit: int = 10
) -> list[SearchHit]:
    """Fuse the keyword and vector rankings (RRF) into one list, best first.

    Each primitive contributes its own top `limit` candidates, so a chunk that only one
    side finds can still make the fused top `limit`.
    """
    keyword = search_chunks(connection, query, limit)
    vector = vector_search_chunks(connection, query_embedding, limit)
    by_id = {hit.chunk_id: hit for hit in [*keyword, *vector]}
    fused = fuse_rankings([[hit.chunk_id for hit in keyword], [hit.chunk_id for hit in vector]])
    return [by_id[chunk_id] for chunk_id in fused[:limit]]
