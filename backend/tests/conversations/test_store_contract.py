"""Ownership, cap and feedback rules every ConversationStore must honour.

Each test runs against the in-memory fake (always) and the Postgres store (only with
`pytest -m integration`), which keeps the fake behind the API tests honest.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

import pytest
from sqlalchemy import Connection

from backend.conversations.limits import Limits, MessageTooLongError
from backend.conversations.store import (
    ConversationStore,
    SqlConversationStore,
    UnscorableMessageError,
)
from tests.conversations.memory_store import InMemoryConversationStore

LIMITS = Limits(max_message_chars=50, max_history_messages=3)


@dataclass
class Harness:
    store: ConversationStore
    new_user: Callable[[], uuid.UUID]


@pytest.fixture(params=["memory", pytest.param("sql", marks=pytest.mark.integration)])
def harness(request: pytest.FixtureRequest) -> Harness:
    if cast(str, request.param) == "memory":
        return Harness(InMemoryConversationStore(LIMITS), uuid.uuid4)
    connection = cast(Connection, request.getfixturevalue("db_connection"))
    new_user = cast(Callable[[], uuid.UUID], request.getfixturevalue("new_auth_user"))
    return Harness(SqlConversationStore(connection, LIMITS), new_user)


def test_a_created_conversation_is_listed_for_its_owner_only(harness: Harness) -> None:
    alice, bob = harness.new_user(), harness.new_user()

    created = harness.store.create(alice, "Scoring question")

    assert [c.id for c in harness.store.list_for_user(alice)] == [created.id]
    assert created.title == "Scoring question"
    assert harness.store.list_for_user(bob) == []


def test_reading_returns_messages_oldest_first_and_hides_others_conversations(
    harness: Harness,
) -> None:
    alice, bob = harness.new_user(), harness.new_user()
    conversation = harness.store.create(alice, None)
    harness.store.add_message(alice, conversation.id, "user", "Can I score twice?")
    harness.store.add_message(alice, conversation.id, "assistant", "No (rule 472).", "trace-1")

    detail = harness.store.get(alice, conversation.id)

    assert detail is not None
    assert [(m.role, m.content, m.trace_id) for m in detail.messages] == [
        ("user", "Can I score twice?", None),
        ("assistant", "No (rule 472).", "trace-1"),
    ]
    assert harness.store.get(bob, conversation.id) is None  # someone else's: not found
    assert harness.store.get(alice, uuid.uuid4()) is None  # and so is a made-up id


def test_only_the_owner_can_delete_and_deleting_removes_the_messages(harness: Harness) -> None:
    alice, bob = harness.new_user(), harness.new_user()
    conversation = harness.store.create(alice, None)
    harness.store.add_message(alice, conversation.id, "user", "hello")

    assert harness.store.delete(bob, conversation.id) is False
    assert harness.store.get(alice, conversation.id) is not None  # untouched

    assert harness.store.delete(alice, conversation.id) is True
    assert harness.store.get(alice, conversation.id) is None
    assert harness.store.history(alice, conversation.id) is None
    assert harness.store.delete(alice, conversation.id) is False  # already gone


def test_nobody_can_write_into_someone_elses_conversation(harness: Harness) -> None:
    alice, bob = harness.new_user(), harness.new_user()
    conversation = harness.store.create(alice, None)

    assert harness.store.add_message(bob, conversation.id, "user", "sneaky") is None
    detail = harness.store.get(alice, conversation.id)
    assert detail is not None
    assert detail.messages == ()


def test_a_message_can_be_stored_under_an_id_chosen_up_front(harness: Harness) -> None:
    # The message endpoint announces the answer's id before the answer exists.
    alice = harness.new_user()
    conversation = harness.store.create(alice, None)
    chosen = uuid.uuid4()

    saved = harness.store.add_message(
        alice, conversation.id, "assistant", "No.", "trace-1", message_id=chosen
    )

    assert saved is not None
    assert saved.id == chosen
    detail = harness.store.get(alice, conversation.id)
    assert detail is not None
    assert [m.id for m in detail.messages] == [chosen]


def test_player_messages_over_the_cap_are_refused_but_answers_are_not(harness: Harness) -> None:
    alice = harness.new_user()
    conversation = harness.store.create(alice, None)

    with pytest.raises(MessageTooLongError, match="limit is 50"):
        harness.store.add_message(alice, conversation.id, "user", "x" * 51)
    long_answer = harness.store.add_message(alice, conversation.id, "assistant", "y" * 500)

    assert long_answer is not None
    detail = harness.store.get(alice, conversation.id)
    assert detail is not None
    assert [m.role for m in detail.messages] == ["assistant"]  # the refused one never landed


def test_history_is_the_most_recent_turns_oldest_first_capped(harness: Harness) -> None:
    alice, bob = harness.new_user(), harness.new_user()
    conversation = harness.store.create(alice, None)
    for n in range(5):
        harness.store.add_message(alice, conversation.id, "user", f"q{n}")

    assert harness.store.history(alice, conversation.id) == [
        ("user", "q2"),
        ("user", "q3"),
        ("user", "q4"),
    ]
    assert harness.store.history(bob, conversation.id) is None


def test_feedback_is_stored_on_the_answer_and_a_change_keeps_when_it_was_first_given(
    harness: Harness,
) -> None:
    alice = harness.new_user()
    conversation = harness.store.create(alice, None)
    answer = harness.store.add_message(alice, conversation.id, "assistant", "No.", "trace-1")
    assert answer is not None

    first = harness.store.give_feedback(alice, conversation.id, answer.id, "up")
    changed = harness.store.give_feedback(alice, conversation.id, answer.id, "down")

    assert first is not None and first.feedback is not None
    assert changed is not None and changed.feedback is not None
    assert changed.feedback.rating == "down"
    assert changed.feedback.given_at == first.feedback.given_at
    detail = harness.store.get(alice, conversation.id)
    assert detail is not None
    assert [m.feedback for m in detail.messages] == [changed.feedback]


def test_feedback_only_lands_on_the_users_own_message_in_that_conversation(
    harness: Harness,
) -> None:
    alice, bob = harness.new_user(), harness.new_user()
    conversation = harness.store.create(alice, None)
    other = harness.store.create(alice, None)
    answer = harness.store.add_message(alice, conversation.id, "assistant", "No.", "trace-1")
    assert answer is not None

    assert harness.store.give_feedback(bob, conversation.id, answer.id, "up") is None
    assert harness.store.give_feedback(alice, other.id, answer.id, "up") is None
    assert harness.store.give_feedback(alice, conversation.id, uuid.uuid4(), "up") is None
    detail = harness.store.get(alice, conversation.id)
    assert detail is not None
    assert [m.feedback for m in detail.messages] == [None]


def test_only_answers_with_a_trace_can_receive_feedback(harness: Harness) -> None:
    alice = harness.new_user()
    conversation = harness.store.create(alice, None)
    question = harness.store.add_message(alice, conversation.id, "user", "Can I score twice?")
    untraced = harness.store.add_message(alice, conversation.id, "assistant", "No.")
    assert question is not None and untraced is not None

    for message in (question, untraced):
        with pytest.raises(UnscorableMessageError):
            harness.store.give_feedback(alice, conversation.id, message.id, "up")
    detail = harness.store.get(alice, conversation.id)
    assert detail is not None
    assert [m.feedback for m in detail.messages] == [None, None]


def test_feedback_does_not_move_its_conversation_to_the_top(harness: Harness) -> None:
    alice = harness.new_user()
    older = harness.store.create(alice, "older")
    answer = harness.store.add_message(alice, older.id, "assistant", "No.", "trace-1")
    newer = harness.store.create(alice, "newer")
    assert answer is not None

    harness.store.give_feedback(alice, older.id, answer.id, "up")

    assert [c.id for c in harness.store.list_for_user(alice)] == [newer.id, older.id]


def test_a_new_message_moves_its_conversation_to_the_top(harness: Harness) -> None:
    alice = harness.new_user()
    older = harness.store.create(alice, "older")
    newer = harness.store.create(alice, "newer")
    assert [c.id for c in harness.store.list_for_user(alice)] == [newer.id, older.id]

    harness.store.add_message(alice, older.id, "user", "bump")

    assert [c.id for c in harness.store.list_for_user(alice)] == [older.id, newer.id]
