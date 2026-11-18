"""A manual check, against the real Langfuse project, that a changed vote replaces the
answer's feedback score instead of adding a second one (review-1 #17).

The API tests only show that the backend resends the same score id, name and timestamp;
that Langfuse then overwrites the score is Langfuse's merge rule, which only the real
service can confirm. This writes to the project behind the LANGFUSE_* keys: one span
named `vote-replacement-check` and its `feedback` score, nothing else.

Run it from `backend/`, with the keys in the environment or `backend/.env`:

    uv run pytest -m langfuse_live -s

It is deselected by default (pyproject.toml) and skips without keys. Ingestion is
asynchronous, so it polls for up to `_WAIT_SECONDS` before failing.
"""

import time
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.agent.tracing import langfuse_scores, score_feedback, tracing_enabled
from backend.conversations.store import Feedback

pytestmark = pytest.mark.langfuse_live

_WAIT_SECONDS = 120
_POLL_SECONDS = 5


def _feedback_scores(langfuse: Any, trace_id: str) -> list[Any]:
    return list(langfuse.api.scores.get_many(trace_id=trace_id, name="feedback").data)


def _wait_for(langfuse: Any, trace_id: str, value: bool) -> list[Any]:
    """The trace's feedback scores once one of them holds `value` (or the last seen)."""
    deadline = time.monotonic() + _WAIT_SECONDS
    scores = _feedback_scores(langfuse, trace_id)
    while not any(bool(score.value) is value for score in scores):
        if time.monotonic() > deadline:
            break
        time.sleep(_POLL_SECONDS)
        scores = _feedback_scores(langfuse, trace_id)
    return scores


def test_a_changed_vote_replaces_the_feedback_score_in_langfuse() -> None:
    if not tracing_enabled():
        pytest.skip("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are not set")
    from langfuse import get_client

    langfuse = get_client()
    scores = langfuse_scores()
    assert scores is not None
    with langfuse.start_as_current_observation(name="vote-replacement-check", as_type="span"):
        trace_id = langfuse.get_current_trace_id()
    assert trace_id is not None
    message_id = uuid.uuid4()
    first_given = datetime.now(UTC)

    score_feedback(scores, message_id, trace_id, Feedback(rating="up", given_at=first_given))
    langfuse.flush()
    after_first = _wait_for(langfuse, trace_id, value=True)
    score_feedback(scores, message_id, trace_id, Feedback(rating="down", given_at=first_given))
    langfuse.flush()
    after_second = _wait_for(langfuse, trace_id, value=False)

    print(f"\ntrace {trace_id}: after the first vote {[s.value for s in after_first]},")
    print(f"after the second {[s.value for s in after_second]}")
    assert [bool(score.value) for score in after_first] == [True]
    assert [bool(score.value) for score in after_second] == [False]
    assert after_second[0].id == f"feedback-{message_id}"
