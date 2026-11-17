"""The HTTP API (issue #11): Supabase-authenticated conversations.

`create_app` takes its collaborators (the token verifier, a way to open a
conversation store for one request, and a database ping for `/health`), so tests build
the app with fake keys and an in-memory store; `production_app` wires Supabase's JWKS,
Postgres and the CORS origins from the environment. Serve it with `uv run backend serve`.

`/health` is public on purpose (issue #22): the scheduled keep-alive hits it so the free
Supabase project sees a query and doesn't pause. It says only "ok" or 503.
"""

import logging
import uuid
from collections.abc import Callable, Generator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from backend.agent.graph import Role
from backend.api.auth import (
    AuthenticatedUser,
    AuthError,
    AuthUnavailableError,
    TokenVerifier,
    supabase_verifier,
)
from backend.config import cors_allowed_origins, supabase_url
from backend.conversations.limits import MAX_TITLE_CHARS, MessageTooLongError, limits_from_env
from backend.conversations.store import (
    Conversation,
    ConversationDetail,
    ConversationStore,
    SqlConversationStore,
)

_log = logging.getLogger(__name__)

OpenStore = Callable[[], AbstractContextManager[ConversationStore]]
"""Opens a store for one request; leaving the context commits (or rolls back on error)."""

PingDatabase = Callable[[], None]
"""Runs one trivial query against the database; raises if it can't be reached."""


@dataclass(frozen=True, slots=True)
class _Collaborators:
    verifier: TokenVerifier
    open_store: OpenStore
    ping_database: PingDatabase | None


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


class HealthOut(BaseModel):
    status: Literal["ok"]


health_router = APIRouter()


@health_router.get("/health")
def health(request: Request) -> HealthOut:
    """Unauthenticated, for the keep-alive ping: a query keeps the free Supabase project awake."""
    ping_database = _collaborators(request).ping_database
    if ping_database is not None:
        try:
            ping_database()
        except Exception:
            _log.exception("Health check: the database did not answer")
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Database is unavailable"
            ) from None
    return HealthOut(status="ok")


def _message_too_long(request: Request, error: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": str(error)}
    )


def create_app(
    verifier: TokenVerifier,
    open_store: OpenStore,
    *,
    ping_database: PingDatabase | None = None,
    cors_origins: Sequence[str] = (),
) -> FastAPI:
    """`ping_database` None means there is no database to check (tests of other endpoints)."""
    app = FastAPI(title="HexCoach API")
    # The frontend authenticates with a bearer header, never cookies, so no credentials mode.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_origins),
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.state.collaborators = _Collaborators(verifier, open_store, ping_database)
    # App-wide: the cap is enforced in the store, so any endpoint that writes a player
    # message gets a clear 422 rather than a 500.
    app.add_exception_handler(MessageTooLongError, _message_too_long)
    app.include_router(router)
    app.include_router(health_router)
    return app


def production_app() -> FastAPI:
    """The API wired to Supabase Auth and Postgres (an ASGI factory for uvicorn)."""
    from backend.db import make_engine, ping_database

    engine = make_engine()
    limits = limits_from_env()

    @contextmanager
    def open_store() -> Generator[ConversationStore]:
        with engine.begin() as connection:
            yield SqlConversationStore(connection, limits)

    return create_app(
        supabase_verifier(supabase_url()),
        open_store,
        ping_database=lambda: ping_database(engine),
        cors_origins=cors_allowed_origins(),
    )
