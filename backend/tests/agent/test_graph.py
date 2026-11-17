from collections.abc import Sequence
from datetime import date
from typing import Any

import pytest
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig

from backend.agent.graph import Turn, format_evidence, run_agent
from backend.agent.tools import make_lookup_card
from backend.retrieval.repository import SearchHit


class ScriptedLLM(Runnable[LanguageModelInput, BaseMessage]):
    """Returns canned replies in order and records every prompt it was sent.

    A reply can be a full message (e.g. an AIMessage carrying tool calls); plain
    strings become plain AIMessages. bind_tools returns the same script, recording
    what was bound, mirroring how ProviderChain exposes tools.
    """

    def __init__(self, replies: Sequence[str | BaseMessage]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.bound_tools: list[Any] = []

    def invoke(
        self, input: LanguageModelInput, config: RunnableConfig | None = None, **kwargs: Any
    ) -> BaseMessage:
        self.prompts.append(str(input))
        reply = self.replies.pop(0)
        return AIMessage(content=reply) if isinstance(reply, str) else reply

    def bind_tools(self, tools: Sequence[Any]) -> "ScriptedLLM":
        self.bound_tools.extend(tools)
        return self


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


def _zhonyas_lookup(lookups: list[str]):
    def find_card(name: str) -> str | None:
        lookups.append(name)
        if name.lower() == "zhonya's hourglass":
            return "Zhonya's Hourglass (Gear)\nExhaust: a unit you control gains Deflect."
        return None

    return make_lookup_card(find_card, lambda: ["Zhonya's Hourglass"])


def _tool_call(name: str, args: dict[str, Any], call_id: str = "call-1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def test_the_answerer_can_look_a_card_up_and_use_its_text() -> None:
    retriever = RecordingRetriever(
        {"score battlefield twice per turn": [rule_hit("472", "Once per turn.")]}
    )
    lookups: list[str] = []
    tool = _zhonyas_lookup(lookups)
    llm = ScriptedLLM(
        [
            PREPARE,
            STRONG,
            _tool_call("lookup_card", {"name": "Zhonya's Hourglass"}),
            "No - Zhonya's Hourglass only grants Deflect (rule 472).",
        ]
    )

    state = run_agent(llm, retriever, "Does Zhonya's stop the score?", tools=[tool])

    assert lookups == ["Zhonya's Hourglass"]  # the tool hit the store, not model memory
    assert llm.bound_tools == [tool]
    assert state["outcome"] == "answered"
    assert "Deflect" in state["answer"]
    # The follow-up call saw the tool's result in the conversation.
    assert "Exhaust: a unit you control gains Deflect" in llm.prompts[-1]
    # And the system prompt told the model the tool exists.
    assert "lookup_card" in llm.prompts[-2]


def test_a_model_stuck_in_lookups_is_forced_to_answer_at_the_cap() -> None:
    retriever = RecordingRetriever({"score battlefield twice per turn": [rule_hit("472", "x")]})
    lookups: list[str] = []
    tool = _zhonyas_lookup(lookups)
    stuck = [_tool_call("lookup_card", {"name": "Zhonya's Hourglass"}, f"call-{n}") for n in "123"]
    llm = ScriptedLLM([PREPARE, STRONG, *stuck, "Fine: no, it only grants Deflect."])

    state = run_agent(llm, retriever, "Does Zhonya's stop it?", tools=[tool])

    assert len(lookups) == 3  # one per round, then the cap
    assert state["answer"] == "Fine: no, it only grants Deflect."
    assert "information you already have" in llm.prompts[-1]  # the forced-answer nudge


def test_a_hallucinated_tool_name_gets_a_corrective_tool_message() -> None:
    retriever = RecordingRetriever({"score battlefield twice per turn": [rule_hit("472", "x")]})
    tool = _zhonyas_lookup([])
    llm = ScriptedLLM(
        [
            PREPARE,
            STRONG,
            _tool_call("summon_judge", {"name": "whatever"}),
            "Answering without that tool.",
        ]
    )

    state = run_agent(llm, retriever, "Can I?", tools=[tool])

    assert state["answer"] == "Answering without that tool."
    assert "Unknown tool 'summon_judge'" in llm.prompts[-1]
    assert "lookup_card" in llm.prompts[-1]  # the reply names the tools that do exist


def test_without_tools_the_answer_prompt_does_not_mention_lookup_card() -> None:
    retriever = RecordingRetriever({"score battlefield twice per turn": [rule_hit("472", "x")]})
    llm = ScriptedLLM([PREPARE, STRONG, "answer"])

    run_agent(llm, retriever, "Can I?")

    assert "lookup_card" not in llm.prompts[-1]


def test_with_tools_the_grader_is_told_card_text_is_fixable() -> None:
    # Otherwise the grader marks card-text gaps weak and the run abstains before the
    # answer step - the only place the tool exists - ever gets a chance to use it.
    retriever = RecordingRetriever({"score battlefield twice per turn": [rule_hit("472", "x")]})
    with_tools = ScriptedLLM([PREPARE, STRONG, "answer"])
    without_tools = ScriptedLLM([PREPARE, STRONG, "answer"])

    run_agent(with_tools, retriever, "Can I?", tools=[_zhonyas_lookup([])])
    run_agent(without_tools, retriever, "Can I?")

    assert "NOT a reason to grade weak" in with_tools.prompts[1]  # the grade call
    assert "NOT a reason to grade weak" not in without_tools.prompts[1]
