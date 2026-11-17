from datetime import date
from typing import Any

import pytest
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig

from backend.agent.graph import Turn, format_evidence, run_agent
from backend.retrieval.repository import SearchHit


class ScriptedLLM(Runnable[LanguageModelInput, BaseMessage]):
    """Returns canned replies in order and records every prompt it was sent."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def invoke(
        self, input: LanguageModelInput, config: RunnableConfig | None = None, **kwargs: Any
    ) -> BaseMessage:
        self.prompts.append(str(input))
        return AIMessage(content=self.replies.pop(0))


def rule_hit(rule_id: str, text: str) -> SearchHit:
    return SearchHit(
        chunk_id=hash(rule_id) % 1000,
        source_type="rules",
        rule_id=rule_id,
        section="Scoring",
        text=text,
        source_version="2026-10-09",
        source_date=date(2026, 10, 9),
        title=None,
        source_url=None,
    )


def faq_hit(title: str, text: str, when: date) -> SearchHit:
    return SearchHit(
        chunk_id=hash(title) % 1000,
        source_type="faq",
        rule_id=None,
        section=None,
        text=text,
        source_version="OGN",
        source_date=when,
        title=title,
        source_url="https://example.com/faq/",
    )


class RecordingRetriever:
    def __init__(self, results: dict[str, list[SearchHit]]) -> None:
        self.results = results
        self.queries: list[str] = []

    def __call__(self, query: str) -> list[SearchHit]:
        self.queries.append(query)
        return self.results.get(query, [])


PREPARE = '{"query": "score battlefield twice per turn", "language": "en"}'
STRONG = '{"grade": "strong", "rewritten_query": null}'
WEAK = '{"grade": "weak", "rewritten_query": "conquer battlefield scoring limit"}'


def test_strong_evidence_answers_without_a_retry() -> None:
    retriever = RecordingRetriever(
        {"score battlefield twice per turn": [rule_hit("472", "Once per battlefield per turn.")]}
    )
    llm = ScriptedLLM([PREPARE, STRONG, "No - only once per battlefield per turn (rule 472)."])

    state = run_agent(llm, retriever, "Can I score the same battlefield twice?")

    assert state["outcome"] == "answered"
    assert "rule 472" in state["answer"]
    assert retriever.queries == ["score battlefield twice per turn"]
    assert not llm.replies  # every scripted reply was consumed: prepare, grade, answer


def test_weak_evidence_retries_once_with_the_rewritten_query_then_answers() -> None:
    retriever = RecordingRetriever(
        {
            "score battlefield twice per turn": [],
            "conquer battlefield scoring limit": [rule_hit("472", "Once per turn.")],
        }
    )
    llm = ScriptedLLM([PREPARE, WEAK, STRONG, "Only once (rule 472)."])

    state = run_agent(llm, retriever, "Can I score twice?")

    assert state["outcome"] == "answered"
    assert retriever.queries == [
        "score battlefield twice per turn",
        "conquer battlefield scoring limit",
    ]


def test_weak_evidence_twice_abstains_after_exactly_one_retry() -> None:
    retriever = RecordingRetriever({})
    llm = ScriptedLLM([PREPARE, WEAK, WEAK, "Which Diana do you mean?"])

    state = run_agent(llm, retriever, "Can I use diana's effect?")

    assert state["outcome"] == "abstained"
    assert state["answer"] == "Which Diana do you mean?"
    assert len(retriever.queries) == 2  # the first attempt plus exactly one retry


def test_weak_evidence_without_a_rewritten_query_abstains_instead_of_retrying() -> None:
    # The spec says the retry happens "with a rewritten query"; if the grader cannot
    # propose one, re-running the same query would just fetch the same evidence.
    retriever = RecordingRetriever({})
    weak_no_rewrite = '{"grade": "weak", "rewritten_query": null}'
    llm = ScriptedLLM([PREPARE, weak_no_rewrite, "I cannot answer this confidently."])

    state = run_agent(llm, retriever, "Can I?")

    assert state["outcome"] == "abstained"
    assert len(retriever.queries) == 1


def test_a_grader_echoing_the_current_query_counts_as_no_rewrite() -> None:
    # Graders sometimes "rewrite" by repeating the query verbatim; retrying with it
    # would fetch the same evidence, so it is treated like a missing rewrite.
    retriever = RecordingRetriever({})
    weak_echo = '{"grade": "weak", "rewritten_query": "score battlefield twice per turn"}'
    llm = ScriptedLLM([PREPARE, weak_echo, "I cannot answer this confidently."])

    state = run_agent(llm, retriever, "Can I?")

    assert state["outcome"] == "abstained"
    assert len(retriever.queries) == 1


def test_non_english_questions_retrieve_in_english_and_answer_in_the_users_language() -> None:
    prepare_pt = '{"query": "Imperial Decree damage assignment", "language": "pt"}'
    retriever = RecordingRetriever(
        {"Imperial Decree damage assignment": [rule_hit("467.2.c.3", "Damage assignment.")]}
    )
    llm = ScriptedLLM([prepare_pt, STRONG, "N\u00e3o - o dano \u00e9 atribu\u00eddo..."])

    state = run_agent(llm, retriever, "eu uso Imperial Decree e ataco, ele mata todas?")

    assert retriever.queries == ["Imperial Decree damage assignment"]  # English retrieval
    assert state["language"] == "pt"
    assert "(pt)" in llm.prompts[-1]  # the answer prompt pins the reply language


def test_message_history_reaches_the_prompts() -> None:
    retriever = RecordingRetriever(
        {"score battlefield twice per turn": [rule_hit("472", "Once per turn.")]}
    )
    llm = ScriptedLLM([PREPARE, STRONG, "As said, rule 472."])
    history: list[Turn] = [("user", "I play a Rengar banish deck."), ("assistant", "Noted.")]

    run_agent(llm, retriever, "So can I re-score it?", history=history)

    assert "Rengar banish deck" in llm.prompts[0]  # prepare sees the conversation
    assert "Rengar banish deck" in llm.prompts[-1]  # and so does the answerer


def test_the_answer_prompt_states_source_precedence() -> None:
    retriever = RecordingRetriever({"score battlefield twice per turn": [rule_hit("472", "x")]})
    llm = ScriptedLLM([PREPARE, STRONG, "answer"])

    run_agent(llm, retriever, "Can I?")

    assert "FAQ entries override card text" in llm.prompts[-1]
    assert "the newer one (by date) wins" in llm.prompts[-1]


def test_evidence_is_formatted_by_precedence_and_cited_by_name() -> None:
    rules = rule_hit("472", "A player may only Score once per Battlefield per turn.")
    faq = faq_hit("Riftbound Origins FAQ", "Q: How do I score?\nA: ...", date(2025, 10, 16))

    evidence = format_evidence([rules, faq])

    assert evidence.index("Riftbound Origins FAQ") < evidence.index("Core Rules, rule 472")
    assert "[Riftbound Origins FAQ (2025-10-16)]" in evidence
    assert "[Core Rules, rule 472 (2026-10-09)]" in evidence
    assert format_evidence([]) == "(no evidence retrieved)"


def test_a_malformed_json_reply_is_reasked_once() -> None:
    retriever = RecordingRetriever(
        {"score battlefield twice per turn": [rule_hit("472", "Once per turn.")]}
    )
    llm = ScriptedLLM(["Let me ponder this at length.", PREPARE, STRONG, "No (rule 472)."])

    state = run_agent(llm, retriever, "Can I?")

    assert state["outcome"] == "answered"
    assert "not valid JSON" in llm.prompts[1]  # the re-ask names the problem


def test_two_non_json_replies_are_a_clear_error() -> None:
    retriever = RecordingRetriever({})
    llm = ScriptedLLM(["I shall now ponder.", "Still pondering, no JSON in sight."])

    with pytest.raises(ValueError, match="Expected a JSON reply"):
        run_agent(llm, retriever, "Can I?")
