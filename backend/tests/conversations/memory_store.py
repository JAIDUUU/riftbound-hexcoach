"""An in-memory ConversationStore for DB-free API tests.

test_store_contract.py runs the same ownership and cap rules against this and the real
SqlConversationStore, so API tests built on this fake can't drift from production.
"""

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from backend.conversations.limits import Limits
from backend.conversations.store import (
    Conversation,
    ConversationDetail,
    Feedback,
    Message,
    NotAnAnswerError,
    Rating,
)
from backend.turns import Role, Turn

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass
class _Row:
    owner: uuid.UUID
    conversation: Conversation
    messages: list[Message] = field(default_factory=list[Message])


class InMemoryConversationStore:
    def __init__(self, limits: Limits) -> None:
        self.limits = limits
        self.rows: dict[uuid.UUID, _Row] = {}
        self._ticks = 0

    def _now(self) -> datetime:
        self._ticks += 1  # strictly increasing, so ordering never ties
        return _EPOCH + timedelta(microseconds=self._ticks)

    def _owned(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> _Row | None:
        row = self.rows.get(conversation_id)
        return row if row is not None and row.owner == user_id else None

    def create(self, user_id: uuid.UUID, title: str | None) -> Conversation:
        now = self._now()
        conversation = Conversation(id=uuid.uuid4(), title=title, created_at=now, updated_at=now)
        self.rows[conversation.id] = _Row(owner=user_id, conversation=conversation)
        return conversation

    def list_for_user(self, user_id: uuid.UUID) -> list[Conversation]:
        mine = [row.conversation for row in self.rows.values() if row.owner == user_id]
        return sorted(mine, key=lambda c: c.updated_at, reverse=True)

    def get(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> ConversationDetail | None:
        row = self._owned(user_id, conversation_id)
        if row is None:
            return None
        return ConversationDetail(conversation=row.conversation, messages=tuple(row.messages))

    def delete(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> bool:
        if self._owned(user_id, conversation_id) is None:
            return False
        del self.rows[conversation_id]
        return True

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
        row = self._owned(user_id, conversation_id)
        if row is None:
            return None
        now = self._now()
        message = Message(
            id=message_id or uuid.uuid4(),
            role=role,
            content=content,
            trace_id=trace_id,
            created_at=now,
        )
        row.messages.append(message)
        row.conversation = replace(row.conversation, updated_at=now)
        return message

    def history(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> list[Turn] | None:
        row = self._owned(user_id, conversation_id)
        if row is None:
            return None
        recent = row.messages[-self.limits.max_history_messages :]
        return [(message.role, message.content) for message in recent]

    def give_feedback(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
        rating: Rating,
    ) -> Message | None:
        row = self._owned(user_id, conversation_id)
        if row is None:
            return None
        for index, message in enumerate(row.messages):
            if message.id == message_id:
                if message.role != "assistant":
                    raise NotAnAnswerError
                given_at = self._now() if message.feedback is None else message.feedback.given_at
                rated = replace(message, feedback=Feedback(rating=rating, given_at=given_at))
                row.messages[index] = rated
                return rated
        return None
