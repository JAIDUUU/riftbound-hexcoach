"""The in-process embedding model (ADR: no external embedding API).

bge-small-en-v1.5 runs via fastembed's ONNX runtime. Documents are embedded once at
ingestion; queries are embedded at request time with the same model, using the BGE query
instruction (fastembed adds it in `query_embed`). The ~130 MB model is downloaded to the
local HuggingFace cache on first use and loading it takes a few seconds, hence the lazy
module-level singleton.
"""

from collections.abc import Sequence
from functools import cache

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIMENSIONS = 384

# fastembed's default batch of 256 long passages peaked at ~7 GB RSS during ingestion;
# 32 keeps the ONNX activation memory modest and bulk embedding is a manual, offline step.
_PASSAGE_BATCH_SIZE = 32


class Embedder:
    """Embeds passages and queries with the same model, as vectors ready for pgvector."""

    def __init__(self) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=EMBEDDING_MODEL)

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._model.passage_embed(list(texts), batch_size=_PASSAGE_BATCH_SIZE)
        return [vector.tolist() for vector in vectors]

    def embed_query(self, query: str) -> list[float]:
        return next(iter(self._model.query_embed(query))).tolist()


@cache
def embedder() -> Embedder:
    """The process-wide embedder; loading the ONNX model is expensive, do it once."""
    return Embedder()
