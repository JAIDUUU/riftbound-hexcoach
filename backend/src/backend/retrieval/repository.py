"""Persistence for chunks: replace the rules chunks and search them with Postgres FTS."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Connection, delete, insert, text

from backend.retrieval.schema import chunks_table
from backend.rules.parse import RuleChunk

_SEARCH = text(
    """
    SELECT source_type, rule_id, section, text, source_version, source_date,
           ts_rank(search, websearch_to_tsquery('english', :query)) AS rank
    FROM chunks
    WHERE search @@ websearch_to_tsquery('english', :query)
    ORDER BY rank DESC, rule_id
    LIMIT :limit
    """
)


@dataclass(frozen=True, slots=True)
class SearchHit:
    source_type: str
    rule_id: str | None
    section: str | None
    text: str
    source_version: str
    source_date: date
    rank: float


def replace_rules(connection: Connection, chunks: Sequence[RuleChunk], source_date: date) -> int:
    """Make the rules chunks match `chunks` (ADR 0008: only the current version is kept).

    Other source types are untouched. Returns the number of chunks written.
    """
    if not chunks:
        raise ValueError("Refusing to ingest an empty rules document.")
    connection.execute(delete(chunks_table).where(chunks_table.c.source_type == "rules"))
    connection.execute(
        insert(chunks_table),
        [
            {
                "source_type": "rules",
                "rule_id": chunk.rule_id,
                "section": chunk.section,
                "parent_rule_id": chunk.parent_id,
                "is_heading": chunk.is_heading,
                "text": chunk.text,
                "source_version": source_date.isoformat(),
                "source_date": source_date,
            }
            for chunk in chunks
        ],
    )
    return len(chunks)


def search_chunks(connection: Connection, query: str, limit: int = 10) -> list[SearchHit]:
    """Full-text search across all chunks, best match first."""
    rows = connection.execute(_SEARCH, {"query": query, "limit": limit}).mappings()
    return [SearchHit(**row) for row in rows]
