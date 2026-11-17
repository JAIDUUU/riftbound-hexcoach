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
from collections.abc import Callable, Sequence
from typing import Any, Literal, TypedDict, cast

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langgraph.graph import END, START, StateGraph  # pyright: ignore[reportMissingTypeStubs]

from backend.agent.prompts import ABSTAIN_PROMPT, ANSWER_PROMPT, GRADE_PROMPT, PREPARE_PROMPT
from backend.retrieval.precedence import order_by_precedence
from backend.retrieval.repository import SearchHit

ChatModel = Runnable[LanguageModelInput, BaseMessage]
Retriever = Callable[[str], Sequence[SearchHit]]
"""Takes an English search query, returns relevant chunks, best first."""

MAX_RETRIEVALS = 2  # the first attempt plus exactly one corrective retry

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

Role = Literal["user", "assistant"]
Turn = tuple[Role, str]
"""One conversation turn, oldest first in a history."""

Outcome = Literal["answered", "abstained"]
"""How a run ended: a judge-style answer, or a clarifying question / honest decline."""


class AgentState(TypedDict):
    """The full state. Keys are filled in graph order; LangGraph merges partial updates,
    so nodes return plain dicts and the graph's structure guarantees every read below
    happens after the producing node has run."""

    question: str
    history: list[Turn]
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


def _conversation(state: AgentState) -> str:
    turns = [*state.get("history", []), ("user", state["question"])]
    return "\n".join(f"{role}: {content}" for role, content in turns)


def build_agent(llm: ChatModel, retrieve: Retriever) -> Any:
    """The compiled graph. Invoke with {"question": ..., "history": [...]}."""

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
        reply = _json_call(llm, GRADE_PROMPT, prompt)
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

    def respond(state: AgentState, system_template: str, evidence_label: str) -> str:
        prompt = (
            f"Message history and question:\n{_conversation(state)}\n\n"
            f"{evidence_label}:\n{format_evidence(state['hits'])}"
        )
        system = system_template.format(language=state["language"])
        return llm.invoke([("system", system), ("user", prompt)]).text

    def answer(state: AgentState) -> _Update:
        return {"answer": respond(state, ANSWER_PROMPT, "Evidence"), "outcome": "answered"}

    def abstain(state: AgentState) -> _Update:
        text = respond(state, ABSTAIN_PROMPT, "Evidence that was found (insufficient)")
        return {"answer": text, "outcome": "abstained"}

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


def run_agent(
    llm: ChatModel,
    retrieve: Retriever,
    question: str,
    history: Sequence[Turn] = (),
    config: RunnableConfig | None = None,
) -> AgentState:
    """One full graph run. `config` carries LangChain callbacks (e.g. Langfuse tracing)."""
    agent = build_agent(llm, retrieve)
    initial = {"question": question, "history": list(history)}
    return cast(AgentState, agent.invoke(initial, config))
