"""The corrective-RAG-lite agent graph (issue #8).

prepare (English query, card names resolved) -> retrieve -> grade -> answer with
citations, or one corrective retry with the grader's rewritten query, then answer or
abstain. The LLM and the retriever are injected, so the routing is unit-testable with
fakes; the CLI wires in the real provider chain and hybrid search.

Message history is part of the input state, so the API can later run the graph fresh
per request with the conversation so far.
"""

import json
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypedDict, cast, runtime_checkable

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.runnables.config import merge_configs
from langchain_core.tools import BaseTool
from langgraph.config import get_stream_writer  # pyright: ignore[reportMissingTypeStubs]
from langgraph.graph import END, START, StateGraph  # pyright: ignore[reportMissingTypeStubs]

from backend.agent.prompts import (
    ABSTAIN_PROMPT,
    ANSWER_PROMPT,
    GRADE_PROMPT,
    GRADE_TOOLS_NOTE,
    MENTIONS_NOTE,
    PREPARE_PROMPT,
    TOOLS_NOTE,
)
from backend.retrieval.precedence import order_by_precedence
from backend.retrieval.repository import SearchHit
from backend.turns import Mentioned, MentionedCard, MentionedDeck, Turn

ChatModel = Runnable[LanguageModelInput, BaseMessage]
Retriever = Callable[[str], Sequence[SearchHit]]
"""Takes an English search query, returns relevant chunks, best first."""


@runtime_checkable
class SupportsBindTools(Protocol):
    """What an LLM must offer before build_agent can hand it tools (ProviderChain does)."""

    def bind_tools(self, tools: Sequence[BaseTool]) -> ChatModel: ...


MAX_RETRIEVALS = 2  # the first attempt plus exactly one corrective retry
MAX_TOOL_ROUNDS = 3  # lookup rounds per answer; after this the model answers with what it has

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

Outcome = Literal["answered", "abstained"]
"""How a run ended: a judge-style answer, or a clarifying question / honest decline."""

StepName = Literal["prepare", "retrieve", "grade", "answer", "abstain"]
"""The graph's nodes; a corrective retry shows up as a second `retrieve` and `grade`."""

_SPOKEN_STEPS: frozenset[str] = frozenset({"answer", "abstain"})
"""The steps whose model output is the reply itself; the others' replies are JSON."""


@dataclass(frozen=True, slots=True)
class Started:
    """The run is under way; the trace id (None untraced) is known before any step."""

    trace_id: str | None


@dataclass(frozen=True, slots=True)
class Step:
    """A graph step has begun."""

    name: StepName


@dataclass(frozen=True, slots=True)
class Token:
    """A piece of the reply as the model streams it. The streamed pieces are a preview
    (a `Reset` discards them), so only the final state's answer is authoritative."""

    text: str


@dataclass(frozen=True, slots=True)
class Reset:
    """The reply streamed so far was discarded: a provider failed mid-reply (the next one
    starts over), or the model wrote text and then called a tool instead of answering.
    Tokens after it start the reply afresh. Only sent once some text was streamed."""


AgentEvent = Started | Step | Token | Reset
OnEvent = Callable[[AgentEvent], None]


class AgentState(TypedDict):
    """The full state. Keys are filled in graph order; LangGraph merges partial updates,
    so nodes return plain dicts and the graph's structure guarantees every read below
    happens after the producing node has run."""

    question: str
    history: list[Turn]
    mentions: list[Mentioned]  # what the player @-mentioned in `question`
    language: str
    query: str
    hits: list[SearchHit]
    retrievals: int
    grade: Literal["strong", "weak"]
    rewritten: bool  # did the grader supply a different query for the retry?
    answer: str
    outcome: Outcome


_Update = dict[str, Any]


def _parse_json(message: BaseMessage) -> dict[str, Any]:
    """The JSON object in an LLM reply, tolerating code fences and prose around it."""
    match = _JSON_BLOCK.search(message.text)
    if match is None:
        raise ValueError(f"Expected a JSON reply, got: {message.text!r}")
    return cast(dict[str, Any], json.loads(match.group()))


def _json_call(llm: ChatModel, system: str, user: str) -> dict[str, Any]:
    """Ask for JSON; on a malformed reply, re-ask once before giving up.

    One flaky completion should not kill the whole run, but silently looping on a model
    that can't produce JSON would; two strikes and the error propagates.
    """
    first = llm.invoke([("system", system), ("user", user)])
    try:
        return _parse_json(first)
    except ValueError:
        retry = llm.invoke(
            [
                ("system", system),
                (
                    "user",
                    f"{user}\n\nYour previous reply was not valid JSON. Reply with"
                    " the JSON object only, no prose.",
                ),
            ]
        )
        return _parse_json(retry)


def format_evidence(hits: Sequence[SearchHit]) -> str:
    """Evidence excerpts for the prompts, ordered by source precedence, cited by name."""
    lines: list[str] = []
    for hit in order_by_precedence(hits):
        if hit.source_type == "rules":
            label = f"Core Rules, rule {hit.rule_id} ({hit.source_date})"
        elif hit.source_type == "faq":
            label = f"{hit.title} ({hit.source_date})"
        else:
            label = f"Card text: {hit.title} ({hit.source_date})"
        lines.append(f"[{label}]\n{hit.text}")
    return "\n\n".join(lines) if lines else "(no evidence retrieved)"


def format_mentions(mentions: Sequence[Mentioned]) -> str:
    blocks = [MENTIONS_NOTE]
    for mention in mentions:
        match mention:
            case MentionedCard(name=name, text=text):
                blocks.append(f"[Card: {name}]\n{text}")
            case MentionedDeck(name=name, sections=sections):
                # Card names contain commas ("Sona, Harmonious"), so they're joined with "; ".
                lines = [f"{section}: {'; '.join(names)}" for section, names in sections]
                blocks.append("\n".join([f"[Deck: {name}]", *lines]))
    return "\n\n".join(blocks)


def _conversation(state: AgentState) -> str:
    """The conversation so far, then whatever the latest question @-mentions."""
    turns = [*state.get("history", []), ("user", state["question"])]
    conversation = "\n".join(f"{role}: {content}" for role, content in turns)
    mentions = state.get("mentions", [])
    return f"{conversation}\n\n{format_mentions(mentions)}" if mentions else conversation


def build_agent(llm: ChatModel, retrieve: Retriever, tools: Sequence[BaseTool] = ()) -> Any:
    """The compiled graph. Invoke with {"question": ..., "history": [...]}.

    `tools` are offered to the model only while it writes the final answer; the rest of
    the pipeline (prepare, grade) stays deterministic JSON calls.
    """
    tool_by_name = {tool.name: tool for tool in tools}
    if tools:
        if not isinstance(llm, SupportsBindTools):
            raise TypeError(f"{type(llm).__name__} cannot bind tools; pass tools=().")
        answer_model: ChatModel = llm.bind_tools(tools)
    else:
        answer_model = llm

    def run_tool(call: ToolCall, config: RunnableConfig) -> BaseMessage:
        tool = tool_by_name.get(call["name"])
        if tool is None:
            known = ", ".join(sorted(tool_by_name))
            return ToolMessage(
                content=f"Unknown tool {call['name']!r}; the only tools are: {known}.",
                tool_call_id=call["id"] or "",
            )
        # Invoking a tool with the ToolCall itself yields the matching ToolMessage. The
        # config is passed explicitly so every call is traced (a documented guarantee),
        # not left to langchain-core's implicit contextvar propagation.
        return cast(BaseMessage, tool.invoke(call, config))

    def prepare(state: AgentState) -> _Update:
        reply = _json_call(llm, PREPARE_PROMPT, _conversation(state))
        return {
            "query": str(reply["query"]),
            "language": str(reply.get("language") or "en"),
            "retrievals": 0,
        }

    def retrieve_node(state: AgentState) -> _Update:
        return {
            "hits": list(retrieve(state["query"])),
            "retrievals": state["retrievals"] + 1,
        }

    def grade(state: AgentState) -> _Update:
        prompt = f"Question:\n{_conversation(state)}\n\nEvidence:\n{format_evidence(state['hits'])}"
        # With lookup_card available, missing card text is fixable at answer time and
        # must not push the grade to weak (and the abstain path that follows it).
        system = f"{GRADE_PROMPT}\n\n{GRADE_TOOLS_NOTE}" if tools else GRADE_PROMPT
        reply = _json_call(llm, system, prompt)
        update: _Update = {
            "grade": "strong" if reply.get("grade") == "strong" else "weak",
            "rewritten": False,
        }
        rewritten = reply.get("rewritten_query")
        if update["grade"] == "weak" and rewritten and str(rewritten) != state["query"]:
            update["query"] = str(rewritten)
            update["rewritten"] = True
        return update

    def route(state: AgentState) -> str:
        if state["grade"] == "strong":
            return "answer"
        if state["retrievals"] < MAX_RETRIEVALS and state["rewritten"]:
            return "retrieve"  # the one corrective retry, and only with a rewritten query
        return "abstain"

    def respond_messages(
        state: AgentState, system_template: str, evidence_label: str, extra_system: str = ""
    ) -> list[BaseMessage]:
        prompt = (
            f"Message history and question:\n{_conversation(state)}\n\n"
            f"{evidence_label}:\n{format_evidence(state['hits'])}"
        )
        system = system_template.format(language=state["language"]) + extra_system
        return [SystemMessage(system), HumanMessage(prompt)]

    def answer(state: AgentState, config: RunnableConfig) -> _Update:
        extra = f"\n\n{TOOLS_NOTE}" if tools else ""
        messages = respond_messages(state, ANSWER_PROMPT, "Evidence", extra)
        for _ in range(MAX_TOOL_ROUNDS):
            reply = answer_model.invoke(messages, config)
            if not isinstance(reply, AIMessage) or not reply.tool_calls:
                return {"answer": reply.text, "outcome": "answered"}
            messages.append(reply)
            messages.extend(run_tool(call, config) for call in reply.tool_calls)
        # Still asking for lookups at the cap: force an answer from what it has.
        final = llm.invoke(
            [*messages, HumanMessage("Answer now using only the information you already have.")],
            config,
        )
        return {"answer": final.text, "outcome": "answered"}

    def abstain(state: AgentState) -> _Update:
        messages = respond_messages(state, ABSTAIN_PROMPT, "Evidence that was found (insufficient)")
        return {"answer": llm.invoke(messages).text, "outcome": "abstained"}

    # langgraph ships no complete type stubs; add_node/compile are partially unknown.
    builder = StateGraph(AgentState)
    builder.add_node("prepare", prepare)  # pyright: ignore[reportUnknownMemberType]
    builder.add_node("retrieve", retrieve_node)  # pyright: ignore[reportUnknownMemberType]
    builder.add_node("grade", grade)  # pyright: ignore[reportUnknownMemberType]
    builder.add_node("answer", answer)  # pyright: ignore[reportUnknownMemberType]
    builder.add_node("abstain", abstain)  # pyright: ignore[reportUnknownMemberType]
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "retrieve")
    builder.add_edge("retrieve", "grade")
    builder.add_conditional_edges(
        "grade", route, {"answer": "answer", "retrieve": "retrieve", "abstain": "abstain"}
    )
    builder.add_edge("answer", END)
    builder.add_edge("abstain", END)
    return builder.compile()  # pyright: ignore[reportUnknownMemberType]


_DISCARDED = "reply_discarded"
"""What `_DiscardWatcher` writes to the run's custom stream."""


class _DiscardWatcher(BaseCallbackHandler):
    """Spots a spoken reply being thrown away: its model call failed (the provider chain
    moves on to the next provider), or it ended in tool calls (the answer comes from a
    later call). Each model call is its own run, so runs are told apart by id.

    It signals through the graph's stream writer rather than calling back directly, so the
    signal reaches `run_agent` in order with the tokens already streamed.
    """

    run_inline = True  # in the node's thread and context, where the stream writer lives

    def __init__(self) -> None:
        self.spoken: set[uuid.UUID] = set()

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: uuid.UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if (metadata or {}).get("langgraph_node") in _SPOKEN_STEPS:
            self.spoken.add(run_id)

    def on_llm_end(self, response: LLMResult, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        if run_id in self.spoken and any(
            isinstance(generation, ChatGeneration)
            and isinstance(generation.message, AIMessage)
            and generation.message.tool_calls
            for generations in response.generations
            for generation in generations
        ):
            self._discarded(run_id)

    def on_llm_error(self, error: BaseException, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        if run_id in self.spoken:
            self._discarded(run_id)

    def _discarded(self, run_id: uuid.UUID) -> None:
        self.spoken.discard(run_id)
        get_stream_writer()(_DISCARDED)


def _watching_discards(config: RunnableConfig | None) -> RunnableConfig:
    """`config` with a `_DiscardWatcher` added to its callbacks."""
    return merge_configs(config, {"callbacks": [_DiscardWatcher()]})


def run_agent(
    llm: ChatModel,
    retrieve: Retriever,
    question: str,
    history: Sequence[Turn] = (),
    config: RunnableConfig | None = None,
    tools: Sequence[BaseTool] = (),
    on_event: OnEvent | None = None,
    mentions: Sequence[Mentioned] = (),
) -> AgentState:
    """One full graph run. `config` carries LangChain callbacks (e.g. Langfuse tracing).

    With `on_event`, the run is streamed: a `Step` as each node begins and `Token`s as
    the answer (or the clarifying question) is written, with a `Reset` whenever the text
    streamed so far is thrown away (see `_DiscardWatcher`). Tokens only flow from models
    that stream, which real chat models do whenever someone is listening.
    """
    agent = build_agent(llm, retrieve, tools)
    initial = {"question": question, "history": list(history), "mentions": list(mentions)}
    if on_event is None:
        return cast(AgentState, agent.invoke(initial, config))

    final: Any = None
    streamed = False  # since the last reset
    # langgraph ships no complete type stubs; the stream's items are untyped tuples.
    for mode, payload in agent.stream(  # pyright: ignore[reportUnknownVariableType]
        initial, _watching_discards(config), stream_mode=["tasks", "messages", "custom", "values"]
    ):
        if mode == "tasks" and "input" in payload:  # a task start; its end carries "result"
            on_event(Step(payload["name"]))
        elif mode == "messages":
            chunk, metadata = payload
            if (
                metadata.get("langgraph_node") in _SPOKEN_STEPS
                and isinstance(chunk, AIMessage)
                and chunk.text
            ):
                streamed = True
                on_event(Token(chunk.text))
        elif mode == "custom" and payload == _DISCARDED and streamed:
            streamed = False
            on_event(Reset())
        elif mode == "values":
            final = payload
    return cast(AgentState, final)
