"""The HTTP API (issues #11, #12): Supabase-authenticated conversations and chat.

`create_app` takes its collaborators (the token verifier, a way to open a conversation
store for one request, and the coach that answers messages), so tests build the app with
fake keys, an in-memory store and a scripted coach; `production_app` wires Supabase's
JWKS, Postgres and the real agent. Serve it with `uv run backend serve`.
"""

import uuid
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field

from backend.agent.coach import Coach, Question
from backend.agent.graph import Role
from backend.api.auth import (
    AuthenticatedUser,
    AuthError,
    AuthUnavailableError,
    TokenVerifier,
    supabase_verifier,
)
from backend.api.turn import OpenStore, PreparedTurn, stream_turn
from backend.config import supabase_url
from backend.conversations.limits import MAX_TITLE_CHARS, MessageTooLongError, limits_from_env
from backend.conversations.store import (
    Conversation,
    ConversationDetail,
    ConversationStore,
    SqlConversationStore,
)


@dataclass(frozen=True, slots=True)
class _Collaborators:
    verifier: TokenVerifier
    open_store: OpenStore
    coach: Coach


def _collaborators(request: Request) -> _Collaborators:
    # Set by create_app; Starlette's app.state is untyped, so this is the one cast.
    return cast(_Collaborators, request.app.state.collaborators)


_bearer = HTTPBearer(auto_error=False)
_CHALLENGE = {"WWW-Authenticate": "Bearer"}


def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthenticatedUser:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token", _CHALLENGE)
    try:
        return _collaborators(request).verifier.verify(credentials.credentials)
    except AuthError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", _CHALLENGE
        ) from None
    except AuthUnavailableError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Sign-in is temporarily unavailable"
        ) from None


def conversation_store(request: Request) -> Generator[ConversationStore]:
    with _collaborators(request).open_store() as store:
        yield store


User = Annotated[AuthenticatedUser, Depends(current_user)]
# scope="function": the transaction commits before the response is sent, so a failed
# commit can never hide behind a 2xx the client already received.
Store = Annotated[ConversationStore, Depends(conversation_store, scope="function")]


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


class MessageOut(BaseModel):
    id: uuid.UUID
    role: Role
    content: str
    trace_id: str | None
    created_at: datetime


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut]

    @classmethod
    def of_detail(cls, detail: ConversationDetail) -> "ConversationDetailOut":
        return cls(
            **ConversationOut.of(detail.conversation).model_dump(),
            messages=[
                MessageOut(
                    id=message.id,
                    role=message.role,
                    content=message.content,
                    trace_id=message.trace_id,
                    created_at=message.created_at,
                )
                for message in detail.messages
            ],
        )


def _not_found() -> HTTPException:
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
    conversation_id: uuid.UUID, user: User, store: Store
) -> ConversationDetailOut:
    detail = store.get(user.id, conversation_id)
    if detail is None:
        raise _not_found()
    return ConversationDetailOut.of_detail(detail)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: uuid.UUID, user: User, store: Store) -> Response:
    if not store.delete(user.id, conversation_id):
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class MessageIn(BaseModel):
    """A player message. The length cap is configuration, enforced by the store."""

    content: str = Field(min_length=1)


def begin_turn(
    conversation_id: uuid.UUID, body: MessageIn, user: User, request: Request
) -> PreparedTurn:
    """Every check that can refuse a message, run before the event stream opens so a
    refusal is a plain HTTP error rather than an `error` event inside a 200: the
    conversation must be the user's (404) and the message must fit the cap (422). The
    player's message is committed here; the answer is stored when it is ready."""
    with _collaborators(request).open_store() as store:
        history = store.history(user.id, conversation_id)
        if history is None:
            raise _not_found()
        store.add_message(user.id, conversation_id, "user", body.content)
    question = Question(
        text=body.content,
        history=tuple(history),
        user_id=user.id,
        conversation_id=conversation_id,
    )
    return PreparedTurn(question=question, answer_id=uuid.uuid4())


@router.post("/{conversation_id}/messages", response_class=EventSourceResponse)
def post_message(
    turn: Annotated[PreparedTurn, Depends(begin_turn)], request: Request
) -> Iterator[ServerSentEvent]:
    collaborators = _collaborators(request)
    yield from stream_turn(turn, collaborators.coach, collaborators.open_store)


def _message_too_long(request: Request, error: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": str(error)}
    )


def create_app(verifier: TokenVerifier, open_store: OpenStore, coach: Coach) -> FastAPI:
    app = FastAPI(title="HexCoach API")
    app.state.collaborators = _Collaborators(verifier, open_store, coach)
    # App-wide: the cap is enforced in the store, so any endpoint that writes a player
    # message gets a clear 422 rather than a 500.
    app.add_exception_handler(MessageTooLongError, _message_too_long)
    app.include_router(router)
    return app


def production_app() -> FastAPI:
    """The API wired to Supabase Auth, Postgres and the provider chain (an ASGI factory
    for uvicorn)."""
    from backend.agent.coach import database_coach
    from backend.db import make_engine
    from backend.llm.providers import chat_chain

    engine = make_engine()
    limits = limits_from_env()

    @contextmanager
    def open_store() -> Generator[ConversationStore]:
        with engine.begin() as connection:
            yield SqlConversationStore(connection, limits)

    coach = database_coach(engine, chat_chain())
    return create_app(supabase_verifier(supabase_url()), open_store, coach)
