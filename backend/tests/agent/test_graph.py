import json
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import replace
from datetime import date
from typing import Any

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolCall
from langchain_core.messages.tool import tool_call_chunk
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.tools import BaseTool
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field

from backend.agent.citations import cited_evidence
from backend.agent.graph import (
    AgentEvent,
    Reset,
    Step,
    Token,
    evidence,
    format_evidence,
    run_agent,
)
from backend.agent.tools import make_lookup_card
from backend.cards.collapse import Card
from backend.llm.providers import AllProvidersFailedError, ProviderChain
from backend.retrieval.repository import SearchHit
from backend.turns import MentionedCard, MentionedDeck, Turn
from tests.cards.memory_catalog import InMemoryCardCatalog


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


SONA_RAMP = MentionedDeck(
    name="Sona ramp",
    sections=(("Champion", ("Sona, Harmonious",)), ("MainDeck", ("Blazing Scorcher", "Recruit"))),
)


def test_mentioned_cards_and_decks_reach_prepare_grade_and_answer_as_player_referenced(
    cards_by_name: dict[str, Card],
) -> None:
    retriever = RecordingRetriever({})
    llm = ScriptedLLM([PREPARE, STRONG, "Yes: Sona readies up to 4 friendly runes."])
    sona = MentionedCard(cards_by_name["Sona, Harmonious"])

    run_agent(llm, retriever, "Does she ready runes?", mentions=[sona, SONA_RAMP])

    for prompt in llm.prompts:  # prepare, grade, answer
        assert "explicitly referenced" in prompt
        assert "ready up to 4 friendly runes" in prompt
        assert "[Deck: Sona ramp]" in prompt
        assert "MainDeck: Blazing Scorcher; Recruit" in prompt


def test_the_answer_prompt_states_source_precedence() -> None:
    retriever = RecordingRetriever({"score battlefield twice per turn": [rule_hit("472", "x")]})
    llm = ScriptedLLM([PREPARE, STRONG, "answer"])

    run_agent(llm, retriever, "Can I?")

    assert "FAQ entries override card text" in llm.prompts[-1]
    assert "the newer one (by date) wins" in llm.prompts[-1]


def test_the_answer_and_the_abstention_both_ask_for_cards_as_card_tags() -> None:
    retriever = RecordingRetriever({"score battlefield twice per turn": [rule_hit("472", "x")]})
    answering = ScriptedLLM([PREPARE, STRONG, "answer"])
    abstaining = ScriptedLLM([PREPARE, '{"grade": "weak", "rewritten_query": null}', "Which?"])

    answered = run_agent(answering, retriever, "Can I?")
    abstained = run_agent(abstaining, retriever, "Can I?")

    assert (answered["outcome"], abstained["outcome"]) == ("answered", "abstained")
    assert "[[Card Name]]" in answering.prompts[-1]
    assert "[[Card Name]]" in abstaining.prompts[-1]


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


class RecordingCatalog(InMemoryCardCatalog):
    """A catalog that records every name looked up in it."""

    def __init__(self, cards: Iterable[Card]) -> None:
        super().__init__(cards)
        self.lookups: list[str] = []

    def find(self, name: str) -> Card | None:
        self.lookups.append(name)
        return super().find(name)


@pytest.fixture
def zhonyas(cards_by_name: dict[str, Card]) -> RecordingCatalog:
    """A catalog holding one Gear, Zhonya's Hourglass."""
    hourglass = replace(
        cards_by_name["Pouty Poro"],
        oracle_id="0e5a8a8c-5b7c-4a4e-9b56-2d3c4b5a6f70",
        oracle_name="Zhonya's Hourglass",
        card_type="Gear",
        supertype=None,
        cleaned_text="Exhaust: a unit you control gains Deflect.",
    )
    return RecordingCatalog([hourglass])


def _tool_call(name: str, args: dict[str, Any], call_id: str = "call-1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def test_the_answerer_can_look_a_card_up_and_use_its_text(zhonyas: RecordingCatalog) -> None:
    retriever = RecordingRetriever(
        {"score battlefield twice per turn": [rule_hit("472", "Once per turn.")]}
    )
    tool = make_lookup_card(zhonyas)
    llm = ScriptedLLM(
        [
            PREPARE,
            STRONG,
            _tool_call("lookup_card", {"name": "Zhonya's Hourglass"}),
            "No - Zhonya's Hourglass only grants Deflect (rule 472).",
        ]
    )

    state = run_agent(llm, retriever, "Does Zhonya's stop the score?", tools=[tool])

    assert zhonyas.lookups == ["Zhonya's Hourglass"]  # the tool hit the store, not memory
    assert llm.bound_tools == [tool]
    assert state["outcome"] == "answered"
    assert "Deflect" in state["answer"]
    # The follow-up call saw the tool's result in the conversation.
    assert "Exhaust: a unit you control gains Deflect" in llm.prompts[-1]
    # And the system prompt told the model the tool exists.
    assert "lookup_card" in llm.prompts[-2]


def test_a_model_stuck_in_lookups_is_forced_to_answer_at_the_cap(
    zhonyas: RecordingCatalog,
) -> None:
    retriever = RecordingRetriever({"score battlefield twice per turn": [rule_hit("472", "x")]})
    tool = make_lookup_card(zhonyas)
    stuck = [_tool_call("lookup_card", {"name": "Zhonya's Hourglass"}, f"call-{n}") for n in "123"]
    llm = ScriptedLLM([PREPARE, STRONG, *stuck, "Fine: no, it only grants Deflect."])

    state = run_agent(llm, retriever, "Does Zhonya's stop it?", tools=[tool])

    assert len(zhonyas.lookups) == 3  # one per round, then the cap
    assert state["answer"] == "Fine: no, it only grants Deflect."
    assert "information you already have" in llm.prompts[-1]  # the forced-answer nudge


def test_a_hallucinated_tool_name_gets_a_corrective_tool_message(
    zhonyas: RecordingCatalog,
) -> None:
    retriever = RecordingRetriever({"score battlefield twice per turn": [rule_hit("472", "x")]})
    tool = make_lookup_card(zhonyas)
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


class _RecordingCallbacks(BaseCallbackHandler):
    """Records which tools ran, standing in for the Langfuse handler."""

    def __init__(self) -> None:
        self.tool_starts: list[str] = []

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, **kwargs: Any) -> None:
        self.tool_starts.append(serialized.get("name", "?"))


def test_tool_calls_reach_the_callbacks_passed_to_run_agent(zhonyas: RecordingCatalog) -> None:
    # End to end: the handler given to run_agent (Langfuse, in production) sees the
    # tool run. This alone can't tell explicit config passing from langchain-core's
    # contextvar fallback; the next test pins the explicit hand-off.
    retriever = RecordingRetriever(
        {"score battlefield twice per turn": [rule_hit("472", "Once per turn.")]}
    )
    tool = make_lookup_card(zhonyas)
    llm = ScriptedLLM(
        [PREPARE, STRONG, _tool_call("lookup_card", {"name": "Zhonya's Hourglass"}), "No."]
    )
    callbacks = _RecordingCallbacks()

    run_agent(llm, retriever, "Can I?", config={"callbacks": [callbacks]}, tools=[tool])

    assert callbacks.tool_starts == ["lookup_card"]


class _LookupArgs(BaseModel):
    name: str


class _ConfigRecordingTool(BaseTool):
    """A lookup_card that records the config argument it is handed, as given."""

    name: str = "lookup_card"
    description: str = "Look a card up by name."
    args_schema: ArgsSchema | None = _LookupArgs
    configs: list[RunnableConfig | None] = Field(default_factory=list[RunnableConfig | None])

    def _run(self, name: str) -> str:
        return f"{name} (Gear)\nExhaust: a unit you control gains Deflect."

    def invoke(
        self,
        input: str | dict[str, Any] | ToolCall,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> Any:
        self.configs.append(config)
        return super().invoke(input, config, **kwargs)


def test_the_node_config_is_handed_to_tool_invoke_explicitly() -> None:
    # "Each lookup_card call is traced" (CONTEXT.md) must not rest on contextvar
    # propagation: with tool.invoke(call) and no config, this records None.
    retriever = RecordingRetriever(
        {"score battlefield twice per turn": [rule_hit("472", "Once per turn.")]}
    )
    tool = _ConfigRecordingTool()
    llm = ScriptedLLM(
        [PREPARE, STRONG, _tool_call("lookup_card", {"name": "Zhonya's Hourglass"}), "No."]
    )

    run_agent(llm, retriever, "Can I?", config={"callbacks": [_RecordingCallbacks()]}, tools=[tool])

    assert len(tool.configs) == 1
    handed = tool.configs[0]
    assert handed is not None
    assert handed.get("callbacks") is not None


def _streaming_chain(replies: Sequence[str]) -> ProviderChain:
    """A provider chain over a real (fake) chat model that streams word by word, which
    is what the token events are built from; ScriptedLLM above never streams."""
    return ProviderChain([("fake", GenericFakeChatModel(messages=iter(replies)))])


def test_a_streamed_run_reports_each_step_as_it_starts_and_streams_only_the_answer() -> None:
    retriever = RecordingRetriever({"score battlefield twice per turn": [rule_hit("472", "x")]})
    llm = _streaming_chain([PREPARE, STRONG, "No - only once per turn (rule 472)."])
    events: list[AgentEvent] = []

    state = run_agent(llm, retriever, "Can I score twice?", on_event=events.append)

    steps = [event.name for event in events if isinstance(event, Step)]
    tokens = [event.text for event in events if isinstance(event, Token)]
    assert steps == ["prepare", "retrieve", "grade", "answer"]
    assert "".join(tokens) == "No - only once per turn (rule 472)."
    assert len(tokens) > 1  # streamed, not delivered in one piece
    assert events.index(Step("answer")) < events.index(Token(tokens[0]))
    assert state["answer"] == "No - only once per turn (rule 472)."
    assert state["outcome"] == "answered"


def test_a_streamed_abstention_streams_the_clarifying_question() -> None:
    weak_no_rewrite = '{"grade": "weak", "rewritten_query": null}'
    llm = _streaming_chain([PREPARE, weak_no_rewrite, "Which Diana do you mean?"])
    events: list[AgentEvent] = []

    state = run_agent(llm, RecordingRetriever({}), "Diana?", on_event=events.append)

    assert [e.name for e in events if isinstance(e, Step)] == [
        "prepare",
        "retrieve",
        "grade",
        "abstain",
    ]
    assert "".join(e.text for e in events if isinstance(e, Token)) == "Which Diana do you mean?"
    assert state["outcome"] == "abstained"


def test_provider_exhaustion_surfaces_from_a_streamed_run_as_is() -> None:
    class Down(GenericFakeChatModel):
        def _generate(self, *args: Any, **kwargs: Any) -> ChatResult:
            raise ConnectionError("quota exceeded")

        def _stream(self, *args: Any, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
            raise ConnectionError("quota exceeded")

    chain = ProviderChain([("a", Down(messages=iter([]))), ("b", Down(messages=iter([])))])

    with pytest.raises(AllProvidersFailedError):
        run_agent(chain, RecordingRetriever({}), "Can I?", on_event=lambda event: None)


def test_with_tools_the_grader_is_told_card_text_is_fixable(zhonyas: RecordingCatalog) -> None:
    # Otherwise the grader marks card-text gaps weak and the run abstains before the
    # answer step - the only place the tool exists - ever gets a chance to use it.
    retriever = RecordingRetriever({"score battlefield twice per turn": [rule_hit("472", "x")]})
    with_tools = ScriptedLLM([PREPARE, STRONG, "answer"])
    without_tools = ScriptedLLM([PREPARE, STRONG, "answer"])

    run_agent(with_tools, retriever, "Can I?", tools=[make_lookup_card(zhonyas)])
    run_agent(without_tools, retriever, "Can I?")

    assert "NOT a reason to grade weak" in with_tools.prompts[1]  # the grade call
    assert "NOT a reason to grade weak" not in without_tools.prompts[1]


def _spans(events: Sequence[AgentEvent]) -> list[str]:
    """The streamed text between resets: what the client shows, then discards."""
    spans = [""]
    for event in events:
        if isinstance(event, Reset):
            spans.append("")
        elif isinstance(event, Token):
            spans[-1] += event.text
    return spans


def test_a_reply_cut_off_by_a_provider_failure_is_reset_before_the_next_provider_streams() -> None:
    class DropsMidAnswer(GenericFakeChatModel):
        streams: int = 0

        def _stream(self, *args: Any, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
            self.streams += 1
            for i, chunk in enumerate(super()._stream(*args, **kwargs)):
                if self.streams == 3 and i == 2:  # the answer, two words in
                    raise ConnectionError("connection dropped")
                yield chunk

    retriever = RecordingRetriever({"score battlefield twice per turn": [rule_hit("472", "x")]})
    dropped = "Yes, you can score twice."
    chain = ProviderChain(
        [
            ("a", DropsMidAnswer(messages=iter([PREPARE, STRONG, dropped]))),
            ("b", GenericFakeChatModel(messages=iter(["No - only once per turn."]))),
        ]
    )
    events: list[AgentEvent] = []

    state = run_agent(chain, retriever, "Can I score twice?", on_event=events.append)

    cut_off, answer = _spans(events)
    assert cut_off and dropped.startswith(cut_off)
    assert answer == state["answer"] == "No - only once per turn."


class _StreamingToolModel(GenericFakeChatModel):
    """Streams its replies word by word, tool calls included, and can be bound to tools."""

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Any:
        return self

    def _stream(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> Iterator[ChatGenerationChunk]:
        reply = next(self.messages)
        message = AIMessage(reply) if isinstance(reply, str) else reply
        for word in re.split(r"(\s)", message.text):
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=word))
            if run_manager is not None:
                run_manager.on_llm_new_token(word, chunk=chunk)
            yield chunk
        if message.tool_calls:
            calls = [
                tool_call_chunk(name=c["name"], args=json.dumps(c["args"]), id=c["id"], index=i)
                for i, c in enumerate(message.tool_calls)
            ]
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=calls))


def test_text_written_before_a_tool_call_is_reset_once_the_call_is_made(
    zhonyas: RecordingCatalog,
) -> None:
    retriever = RecordingRetriever({"score battlefield twice per turn": [rule_hit("472", "x")]})
    looking = AIMessage(
        "Let me check Zhonya's Hourglass.",
        tool_calls=[{"name": "lookup_card", "args": {"name": "Zhonya's Hourglass"}, "id": "c1"}],
    )
    silent = _tool_call("lookup_card", {"name": "Zhonya's Hourglass"}, "c2")
    model = _StreamingToolModel(
        messages=iter([PREPARE, STRONG, looking, silent, "No, it only grants Deflect."])
    )
    events: list[AgentEvent] = []

    state = run_agent(
        ProviderChain([("fake", model)]),
        retriever,
        "Does Zhonya's stop the score?",
        tools=[make_lookup_card(zhonyas)],
        on_event=events.append,
    )

    assert zhonyas.lookups == ["Zhonya's Hourglass", "Zhonya's Hourglass"]
    # The silent second round streamed nothing, so it has nothing to reset.
    assert _spans(events) == ["Let me check Zhonya's Hourglass.", state["answer"]]
    assert state["answer"] == "No, it only grants Deflect."


def card_hit(title: str, text: str) -> SearchHit:
    return SearchHit(
        chunk_id=11,
        source_type="card_text",
        rule_id=None,
        section=None,
        text=text,
        source_version="2026-11-06",
        source_date=date(2026, 11, 6),
        title=title,
        source_url=None,
    )


def test_a_looked_up_card_is_evidence_the_answer_can_cite(zhonyas: RecordingCatalog) -> None:
    llm = ScriptedLLM(
        [
            PREPARE,
            STRONG,
            _tool_call("lookup_card", {"name": "Zhonya's Hourglass"}),
            _tool_call("lookup_card", {"name": "Zhonyas Hourglas"}, "call-2"),  # not found
            "No: [[Zhonya's Hourglass]] only grants Deflect.",
        ]
    )

    state = run_agent(
        llm, RecordingRetriever({}), "Does it stop it?", tools=[make_lookup_card(zhonyas)]
    )

    [cited] = cited_evidence(state["answer"], evidence(state))
    assert (cited.source_type, cited.title) == ("card_text", "Zhonya's Hourglass")
    assert cited.text == "Zhonya's Hourglass (Gear)\nExhaust: a unit you control gains Deflect."
    assert cited.source_date == date(2026, 11, 6)  # the card snapshot's date


def test_a_mentioned_card_is_evidence_the_answer_can_cite(cards_by_name: dict[str, Card]) -> None:
    sona = MentionedCard(cards_by_name["Sona, Harmonious"])
    llm = ScriptedLLM([PREPARE, STRONG, "Yes: [[Sona, Harmonious]] readies up to 4 runes."])

    state = run_agent(llm, RecordingRetriever({}), "Does she ready runes?", mentions=[sona])

    [cited] = cited_evidence(state["answer"], evidence(state))
    assert (cited.source_type, cited.title, cited.text) == ("card_text", sona.name, sona.text)


def test_a_card_retrieved_and_also_looked_up_is_one_piece_of_evidence(
    zhonyas: RecordingCatalog,
) -> None:
    retrieved = card_hit("Zhonya's Hourglass", "Zhonya's Hourglass (Gear)\n...")
    retriever = RecordingRetriever({"score battlefield twice per turn": [retrieved]})
    llm = ScriptedLLM(
        [PREPARE, STRONG, _tool_call("lookup_card", {"name": "Zhonya's Hourglass"}), "No."]
    )

    state = run_agent(llm, retriever, "Does it stop it?", tools=[make_lookup_card(zhonyas)])

    assert evidence(state) == (retrieved,)
