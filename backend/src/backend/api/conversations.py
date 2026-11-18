"""Conversations (issue #11): create, list, read with messages, delete; always the
signed-in user's own, and someone else's is a plain 404. A read gives each answer its
validated Card tags, as its `final` event did (api/cards.py)."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from backend.api.cards import CardOut, OpenCards, validated_cards_each
from backend.api.dependencies import CardOpener, Store, User
from backend.conversations.limits import MAX_TITLE_CHARS
from backend.conversations.store import Conversation, ConversationDetail, Message, Rating
from backend.turns import MentionKind, Role


class ConversationIn(BaseModel):
    title: str | None = Field(default=None, max_length=MAX_TITLE_CHARS)


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, conversation: Conversation) -> "ConversationOut":
        return cls(
            id=conversation.id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )


class MentionOut(BaseModel):
    kind: MentionKind
    id: uuid.UUID


class MessageOut(BaseModel):
    id: uuid.UUID
    role: Role
    content: str
    trace_id: str | None
    created_at: datetime
    feedback: Rating | None
    mentions: list[MentionOut]  # what a player message @-mentioned, as sent
    cards: list[CardOut]  # the Cards an answer tags; a player message's tags are not checked

    @classmethod
    def of(cls, message: Message, cards: list[CardOut]) -> "MessageOut":
        return cls(
            id=message.id,
            role=message.role,
            content=message.content,
            trace_id=message.trace_id,
            created_at=message.created_at,
            feedback=None if message.feedback is None else message.feedback.rating,
            mentions=[MentionOut(kind=m.kind, id=m.id) for m in message.mentions],
            cards=cards,
        )

    @classmethod
    def answer(cls, message: Message, open_cards: OpenCards | None) -> "MessageOut":
        [out] = cls.all_of([message], open_cards)
        return out

    @classmethod
    def all_of(
        cls, messages: Sequence[Message], open_cards: OpenCards | None
    ) -> list["MessageOut"]:
        answers = [m for m in messages if m.role == "assistant"]
        validated = dict(
            zip(
                (m.id for m in answers),
                validated_cards_each([m.content for m in answers], open_cards),
                strict=True,
            )
        )
        return [cls.of(m, validated.get(m.id, [])) for m in messages]


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut]

    @classmethod
    def of_detail(
        cls, detail: ConversationDetail, open_cards: OpenCards | None
    ) -> "ConversationDetailOut":
        return cls(
            **ConversationOut.of(detail.conversation).model_dump(),
            messages=MessageOut.all_of(detail.messages, open_cards),
        )


def conversation_not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")


router = APIRouter(prefix="/conversations")


@router.post("", status_code=status.HTTP_201_CREATED)
def create_conversation(body: ConversationIn, user: User, store: Store) -> ConversationOut:
    return ConversationOut.of(store.create(user.id, body.title))


@router.get("")
def list_conversations(user: User, store: Store) -> list[ConversationOut]:
    return [ConversationOut.of(c) for c in store.list_for_user(user.id)]


@router.get("/{conversation_id}")
def read_conversation(
    conversation_id: uuid.UUID, user: User, store: Store, open_cards: CardOpener
) -> ConversationDetailOut:
    detail = store.get(user.id, conversation_id)
    if detail is None:
        raise conversation_not_found()
    return ConversationDetailOut.of_detail(detail, open_cards)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: uuid.UUID, user: User, store: Store) -> Response:
    if not store.delete(user.id, conversation_id):
        raise conversation_not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
