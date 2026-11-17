"""The HTTP API (issue #11): Supabase-authenticated conversations, and feedback (#19).

`create_app` takes its collaborators (the token verifier, a way to open a conversation
store for one request, and the Langfuse client feedback is scored with), so tests build
the app with fake keys, an in-memory store and a fake Langfuse; `production_app` wires
Supabase's JWKS, Postgres and Langfuse. Serve it with `uv run backend serve`.
"""

import uuid
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from backend.agent.graph import Role
from backend.agent.tracing import ScoreClient, langfuse_scores, score_feedback
from backend.api.auth import (
    AuthenticatedUser,
    AuthError,
    AuthUnavailableError,
    TokenVerifier,
    supabase_verifier,
)
from backend.config import supabase_url
from backend.conversations.limits import MAX_TITLE_CHARS, MessageTooLongError, limits_from_env
from backend.conversations.store import (
    Conversation,
    ConversationDetail,
    ConversationStore,
    Message,
    Rating,
    SqlConversationStore,
)

OpenStore = Callable[[], AbstractContextManager[ConversationStore]]
"""Opens a store for one request; leaving the context commits (or rolls back on error)."""


@dataclass(frozen=True, slots=True)
class _Collaborators:
    verifier: TokenVerifier
    open_store: OpenStore
    scores: ScoreClient | None


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


def score_client(request: Request) -> ScoreClient | None:
    return _collaborators(request).scores


User = Annotated[AuthenticatedUser, Depends(current_user)]
# scope="function": the transaction commits before the response is sent, so a failed
# commit can never hide behind a 2xx the client already received.
Store = Annotated[ConversationStore, Depends(conversation_store, scope="function")]
Scores = Annotated[ScoreClient | None, Depends(score_client)]


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
    feedback: Rating | None

    @classmethod
    def of(cls, message: Message) -> "MessageOut":
        return cls(
            id=message.id,
            role=message.role,
            content=message.content,
            trace_id=message.trace_id,
            created_at=message.created_at,
            feedback=None if message.feedback is None else message.feedback.rating,
        )


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut]

    @classmethod
    def of_detail(cls, detail: ConversationDetail) -> "ConversationDetailOut":
        return cls(
            **ConversationOut.of(detail.conversation).model_dump(),
            messages=[MessageOut.of(message) for message in detail.messages],
        )


class FeedbackIn(BaseModel):
    rating: Rating


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


@router.put("/{conversation_id}/messages/{message_id}/feedback")
def give_feedback(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    body: FeedbackIn,
    user: User,
    store: Store,
    scores: Scores,
) -> MessageOut:
    message = store.give_feedback(user.id, conversation_id, message_id, body.rating)
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    if scores is not None and message.trace_id is not None and message.feedback is not None:
        score_feedback(scores, message.id, message.trace_id, message.feedback)
    return MessageOut.of(message)


def _message_too_long(request: Request, error: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": str(error)}
    )


def create_app(
    verifier: TokenVerifier, open_store: OpenStore, scores: ScoreClient | None = None
) -> FastAPI:
    """`scores` is None when Langfuse isn't configured: feedback is then stored, not scored."""
    app = FastAPI(title="HexCoach API")
    app.state.collaborators = _Collaborators(verifier, open_store, scores)
    # App-wide: the cap is enforced in the store, so any endpoint that writes a player
    # message gets a clear 422 rather than a 500.
    app.add_exception_handler(MessageTooLongError, _message_too_long)
    app.include_router(router)
    return app


def production_app() -> FastAPI:
    """The API wired to Supabase Auth and Postgres (an ASGI factory for uvicorn)."""
    from backend.db import make_engine

    engine = make_engine()
    limits = limits_from_env()

    @contextmanager
    def open_store() -> Generator[ConversationStore]:
        with engine.begin() as connection:
            yield SqlConversationStore(connection, limits)

    return create_app(supabase_verifier(supabase_url()), open_store, langfuse_scores())
