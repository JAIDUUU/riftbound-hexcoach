import hashlib
from datetime import date
from typing import Any

import pytest
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig

from backend.agent.graph import AgentEvent, Started, Step
from backend.agent.tracing import hash_user_id, traced_run, tracing_enabled
from backend.retrieval.repository import SearchHit


class ScriptedLLM(Runnable[LanguageModelInput, BaseMessage]):
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)

    def invoke(
        self, input: LanguageModelInput, config: RunnableConfig | None = None, **kwargs: Any
    ) -> BaseMessage:
        return AIMessage(content=self.replies.pop(0))


def test_user_ids_are_hashed_stably_and_one_way() -> None:
    hashed = hash_user_id("discord:ordis#123")

    assert hashed == hashlib.sha256(b"discord:ordis#123").hexdigest()
    assert hashed == hash_user_id("discord:ordis#123")  # stable
    assert "ordis" not in hashed
    assert hash_user_id("someone-else") != hashed


@pytest.fixture
def no_langfuse_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    # Blank, not deleted: optional_env treats blank as unset, and load_dotenv would
    # re-populate a deleted variable from backend/.env on a developer machine.
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")


def test_tracing_is_disabled_without_langfuse_keys(no_langfuse_keys: None) -> None:
    assert not tracing_enabled()


def test_an_untraced_run_still_works_and_returns_no_trace_id(no_langfuse_keys: None) -> None:
    hit = SearchHit(
        chunk_id=1,
        source_type="rules",
        rule_id="472",
        section="Scoring",
        text="Once per battlefield per turn.",
        source_version="2026-10-09",
        source_date=date(2026, 10, 9),
        title=None,
        source_url=None,
    )
    llm = ScriptedLLM(
        [
            '{"query": "score twice", "language": "en"}',
            '{"grade": "strong", "rewritten_query": null}',
            "No (rule 472).",
        ]
    )

    state, trace_id = traced_run(llm, lambda query: [hit], "Can I score twice?")

    assert trace_id is None
    assert state["outcome"] == "answered"
    assert state["answer"] == "No (rule 472)."


def test_an_untraced_streamed_run_announces_its_missing_trace_id_first(
    no_langfuse_keys: None,
) -> None:
    llm = ScriptedLLM(
        [
            '{"query": "score twice", "language": "en"}',
            '{"grade": "weak", "rewritten_query": null}',
            "Which battlefield?",
        ]
    )
    events: list[AgentEvent] = []

    state, _ = traced_run(llm, lambda query: [], "Can I?", on_event=events.append)

    assert events[0] == Started(trace_id=None)
    assert Step("prepare") in events[1:]
    assert state["outcome"] == "abstained"
