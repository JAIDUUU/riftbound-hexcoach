"""Conversations and their messages, always scoped to the user who owns them.

Every operation takes the owner's user id, and a conversation that belongs to someone
else is indistinguishable from one that does not exist (None / False), so callers can't
leak whether another user's conversation id is real. The message cap and the history
window (conversations/limits.py) are enforced here, at the one boundary every write and
every LLM-bound history read goes through.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, cast

from sqlalchemy import (
    ColumnElement,
    Connection,
    RowMapping,
    delete,
    exists,
    func,
    insert,
    select,
    update,
)

from backend.conversations.limits import Limits
from backend.conversations.schema import conversations_table, messages_table
from backend.turns import Role, Turn


@dataclass(frozen=True, slots=True)
class Conversation:
    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


Rating = Literal["up", "down"]


class NotAnAnswerError(ValueError):
    """Feedback rates an answer, so the player's own messages can't receive it."""

    def __init__(self) -> None:
        super().__init__("Only answers can receive feedback.")


@dataclass(frozen=True, slots=True)
class Feedback:
    """The player's thumbs up/down on an answer."""

    rating: Rating
    given_at: datetime  # when feedback was first given; changing the rating keeps it


@dataclass(frozen=True, slots=True)
class Message:
    id: uuid.UUID
    role: Role
    content: str
    trace_id: str | None
    created_at: datetime
    feedback: Feedback | None = None


@dataclass(frozen=True, slots=True)
class ConversationDetail:
    conversation: Conversation
    messages: tuple[Message, ...]  # oldest first


class ConversationStore(Protocol):
    def create(self, user_id: uuid.UUID, title: str | None) -> Conversation: ...

    def list_for_user(self, user_id: uuid.UUID) -> list[Conversation]:
        """The user's conversations, most recently active first."""
        ...

    def get(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> ConversationDetail | None: ...

    def delete(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> bool:
        """Delete the conversation and (by cascade) its messages; False if not the user's."""
        ...

    def add_message(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        role: Role,
        content: str,
        trace_id: str | None = None,
        message_id: uuid.UUID | None = None,
    ) -> Message | None:
        """Append a message (player messages must fit the length cap); None if not the
        user's conversation. Raises MessageTooLongError over the cap. `message_id` lets
        the caller fix the id before the content exists; by default a new one is made."""
        ...

    def history(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> list[Turn] | None:
        """The most recent turns for the LLM, oldest first, capped at the history limit."""
        ...

    def give_feedback(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
        rating: Rating,
    ) -> Message | None:
        """Set (or change) the player's rating on an answer; None if the message is not in
        one of the user's conversations. Raises NotAnAnswerError unless the message is an
        assistant message (traced or not)."""
        ...


_CONVERSATION_COLUMNS = (
    conversations_table.c.id,
    conversations_table.c.title,
    conversations_table.c.created_at,
    conversations_table.c.updated_at,
)
_MESSAGE_COLUMNS = (
    messages_table.c.id,
    messages_table.c.role,
    messages_table.c.content,
    messages_table.c.trace_id,
    messages_table.c.created_at,
    messages_table.c.feedback,
    messages_table.c.feedback_given_at,
)


def _conversation(row: RowMapping) -> Conversation:
    return Conversation(
        id=row["id"], title=row["title"], created_at=row["created_at"], updated_at=row["updated_at"]
    )


def _message(row: RowMapping) -> Message:
    feedback = None
    if row["feedback"] is not None:
        # ck_messages_feedback guarantees the rating, and that given_at is set with it
        feedback = Feedback(rating=cast(Rating, row["feedback"]), given_at=row["feedback_given_at"])
    return Message(
        id=row["id"],
        role=cast(Role, row["role"]),  # the ck_messages_role constraint guarantees it
        content=row["content"],
        trace_id=row["trace_id"],
        created_at=row["created_at"],
        feedback=feedback,
    )


def _owned(user_id: uuid.UUID, conversation_id: uuid.UUID) -> ColumnElement[bool]:
    return (conversations_table.c.id == conversation_id) & (
        conversations_table.c.user_id == user_id
    )


class SqlConversationStore:
    """ConversationStore over Postgres; runs inside the caller's connection/transaction."""

    def __init__(self, connection: Connection, limits: Limits) -> None:
        self.connection = connection
        self.limits = limits

    def create(self, user_id: uuid.UUID, title: str | None) -> Conversation:
        statement = (
            insert(conversations_table)
            .values(user_id=user_id, title=title)
            .returning(*_CONVERSATION_COLUMNS)
        )
        return _conversation(self.connection.execute(statement).mappings().one())

    def list_for_user(self, user_id: uuid.UUID) -> list[Conversation]:
        statement = (
            select(*_CONVERSATION_COLUMNS)
            .where(conversations_table.c.user_id == user_id)
            .order_by(conversations_table.c.updated_at.desc(), conversations_table.c.id)
        )
        return [_conversation(row) for row in self.connection.execute(statement).mappings()]

    def get(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> ConversationDetail | None:
        statement = select(*_CONVERSATION_COLUMNS).where(_owned(user_id, conversation_id))
        row = self.connection.execute(statement).mappings().first()
        if row is None:
            return None
        messages = (
            select(*_MESSAGE_COLUMNS)
            .where(messages_table.c.conversation_id == conversation_id)
            .order_by(messages_table.c.seq)
        )
        return ConversationDetail(
            conversation=_conversation(row),
            messages=tuple(_message(m) for m in self.connection.execute(messages).mappings()),
        )

    def delete(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> bool:
        statement = delete(conversations_table).where(_owned(user_id, conversation_id))
        return self.connection.execute(statement).rowcount > 0

    def add_message(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        role: Role,
        content: str,
        trace_id: str | None = None,
        message_id: uuid.UUID | None = None,
    ) -> Message | None:
        if role == "user":
            self.limits.check_message(content)
        touched = self.connection.execute(
            update(conversations_table)
            .where(_owned(user_id, conversation_id))
            .values(updated_at=func.clock_timestamp())
        )
        if touched.rowcount == 0:
            return None
        values = {
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "trace_id": trace_id,
        }
        if message_id is not None:
            values["id"] = message_id
        statement = insert(messages_table).values(values).returning(*_MESSAGE_COLUMNS)
        return _message(self.connection.execute(statement).mappings().one())

    def history(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> list[Turn] | None:
        owned = select(conversations_table.c.id).where(_owned(user_id, conversation_id))
        if self.connection.execute(owned).first() is None:
            return None
        recent = (
            select(messages_table.c.role, messages_table.c.content)
            .where(messages_table.c.conversation_id == conversation_id)
            .order_by(messages_table.c.seq.desc())
            .limit(self.limits.max_history_messages)
        )
        rows = list(self.connection.execute(recent).mappings())
        return [(cast(Role, row["role"]), str(row["content"])) for row in reversed(rows)]

    def give_feedback(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
        rating: Rating,
    ) -> Message | None:
        target = (
            (messages_table.c.id == message_id)
            & (messages_table.c.conversation_id == conversation_id)
            & exists().where(_owned(user_id, conversation_id))
        )
        statement = (
            update(messages_table)
            .where(target, messages_table.c.role == "assistant")
            .values(
                feedback=rating,
                feedback_given_at=func.coalesce(
                    messages_table.c.feedback_given_at, func.clock_timestamp()
                ),
            )
            .returning(*_MESSAGE_COLUMNS)
        )
        row = self.connection.execute(statement).mappings().first()
        if row is not None:
            return _message(row)
        if self.connection.execute(select(messages_table.c.id).where(target)).first() is not None:
            raise NotAnAnswerError
        return None
