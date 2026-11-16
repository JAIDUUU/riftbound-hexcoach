from backend.retrieval.fusion import fuse_rankings


def test_an_item_in_both_lists_beats_single_list_items() -> None:
    fused = fuse_rankings([["a", "b"], ["b", "c"]])

    assert fused[0] == "b"  # ranked in both lists
    assert set(fused) == {"a", "b", "c"}


def test_ranks_matter_within_a_list() -> None:
    assert fuse_rankings([["a", "b", "c"]]) == ["a", "b", "c"]


def test_a_top_vector_hit_survives_zero_keyword_hits() -> None:
    # The conversational-question case: FTS finds nothing, the vector side carries it.
    assert fuse_rankings([[], ["x", "y"]]) == ["x", "y"]


def test_ties_break_toward_the_earlier_list() -> None:
    # "a" and "b" each appear once at rank 1, so their scores tie exactly.
    assert fuse_rankings([["a"], ["b"]]) == ["a", "b"]


def test_fusing_nothing_is_empty() -> None:
    assert fuse_rankings([]) == []
    assert fuse_rankings([[], []]) == []


def test_scores_accumulate_across_many_lists() -> None:
    # "c" is mediocre everywhere but present everywhere; "a" and "b" top one list each.
    fused = fuse_rankings([["a", "c"], ["b", "c"], ["c"]])

    assert fused[0] == "c"
