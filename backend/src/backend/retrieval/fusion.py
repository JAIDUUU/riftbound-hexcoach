"""Reciprocal rank fusion: merge several ranked lists into one.

Each item's fused score is the sum over lists of 1 / (k + rank), rank starting at 1 for
the best item in a list. Items near the top of any list score well; items present in
several lists score better; absolute scores from the sources (ts_rank, cosine distance)
never need to be comparable. k=60 is the standard damping constant from the original RRF
paper and flattens the difference between, say, ranks 1 and 3.
"""

from collections.abc import Hashable, Sequence

RRF_K = 60


def fuse_rankings[Key: Hashable](rankings: Sequence[Sequence[Key]], k: int = RRF_K) -> list[Key]:
    """Merge ranked lists of keys (best first) into one list, best fused score first.

    Ties break toward the earlier list, then toward the better rank in it, so fusing
    (keyword, vector) rankings is deterministic.
    """
    scores: dict[Key, float] = {}
    first_seen: dict[Key, tuple[int, int]] = {}
    for list_index, ranking in enumerate(rankings):
        for rank, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            first_seen.setdefault(key, (list_index, rank))
    return sorted(scores, key=lambda key: (-scores[key], first_seen[key]))
