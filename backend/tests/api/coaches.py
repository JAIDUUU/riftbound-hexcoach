"""Coaches for API tests: a scripted stand-in for the agent, and one that must never run."""

from collections.abc import Callable, Sequence

from backend.agent.coach import Question, Reply
from backend.agent.graph import AgentEvent, OnEvent


class FakeCoach:
    """Stands in for the agent graph: replays scripted events, then replies or fails.

    `during` runs mid-answer, for things that happen while the model is still writing.
    """

    def __init__(
        self,
        events: Sequence[AgentEvent] = (),
        reply: Reply | None = None,
        error: Exception | None = None,
        during: Callable[[], object] | None = None,
    ) -> None:
        self.events = list(events)
        self.reply = reply
        self.error = error
        self.during = during
        self.questions: list[Question] = []

    def __call__(self, question: Question, on_event: OnEvent) -> Reply:
        self.questions.append(question)
        for event in self.events:
            on_event(event)
        if self.during is not None:
            self.during()
        if self.error is not None:
            raise self.error
        assert self.reply is not None, "a FakeCoach needs a reply or an error"
        return self.reply


def unused_coach(question: Question, on_event: OnEvent) -> Reply:
    raise AssertionError("this test never sends a message")
