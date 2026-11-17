"""The HTTP API (issue #11): Supabase-authenticated conversations, feedback (#19) and decks (#16).

`create_app` takes its collaborators (the token verifier, a way to open the conversation
store and the decks for one request, the Langfuse client feedback is scored with, and a
database ping for `/health`), so tests build the app with fake keys, in-memory stores and
a fake Langfuse; `production_app` wires Supabase's JWKS, Postgres, Langfuse and the CORS
origins from the environment. Serve it with `uv run backend serve`.

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

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
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
from backend.cards.catalog import CardCatalog, SqlCardCatalog
from backend.config import cors_allowed_origins, supabase_url
from backend.conversations.limits import MAX_TITLE_CHARS, MessageTooLongError, limits_from_env
from backend.conversations.store import (
    Conversation,
    ConversationDetail,
    ConversationStore,
    Message,
    Rating,
    SqlConversationStore,
    UnscorableMessageError,
)
from backend.decks.importing import DeckImport, import_decklist
from backend.decks.parse import SECTIONS, Section
from backend.decks.store import MAX_DECK_NAME_CHARS, Deck, DeckStore, SqlDeckStore
from backend.decks.warnings import WarningKind

_log = logging.getLogger(__name__)

OpenStore = Callable[[], AbstractContextManager[ConversationStore]]
"""Opens a store for one request; leaving the context commits (or rolls back on error)."""

PingDatabase = Callable[[], None]
"""Runs one trivial query against the database; raises if it can't be reached."""


@dataclass(frozen=True, slots=True)
class DeckAccess:
    """One request's decks: the user's saved decks and the cards to validate them against."""

    decks: DeckStore
    cards: CardCatalog


OpenDecks = Callable[[], AbstractContextManager[DeckAccess]]
"""Opens deck access for one request; leaving the context commits (or rolls back on error)."""


@dataclass(frozen=True, slots=True)
class _Collaborators:
    verifier: TokenVerifier
    open_store: OpenStore
    open_decks: OpenDecks
    scores: ScoreClient | None
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
    after_response: BackgroundTasks,
) -> MessageOut:
    try:
        message = store.give_feedback(user.id, conversation_id, message_id, body.rating)
    except UnscorableMessageError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    if scores is not None and message.trace_id is not None and message.feedback is not None:
        # Runs after the store has committed, so Langfuse never gets a vote we lost.
        after_response.add_task(
            score_feedback, scores, message.id, message.trace_id, message.feedback
        )
    return MessageOut.of(message)


def deck_access(request: Request) -> Generator[DeckAccess]:
    with _collaborators(request).open_decks() as access:
        yield access


Decks = Annotated[DeckAccess, Depends(deck_access, scope="function")]


class DecklistIn(BaseModel):
    decklist: str


class DeckIn(DecklistIn):
    name: str = Field(min_length=1, max_length=MAX_DECK_NAME_CHARS)


class CardRefOut(BaseModel):
    oracle_id: str
    oracle_name: str


class DeckLineOut(BaseModel):
    line: int
    count: int
    name: str  # as written
    card: CardRefOut | None  # None: no card has that name; see suggestions
    suggestions: list[str]


class SectionOut(BaseModel):
    section: Section
    cards: list[DeckLineOut]


class DeckWarningOut(BaseModel):
    kind: WarningKind
    message: str
    line: int | None


class DeckImportOut(BaseModel):
    sections: list[SectionOut]  # every section, in decklist order, empty ones included
    warnings: list[DeckWarningOut]

    @classmethod
    def of(cls, imported: DeckImport) -> "DeckImportOut":
        def lines_in(section: Section) -> list[DeckLineOut]:
            return [
                DeckLineOut(
                    line=resolved.line.line,
                    count=resolved.line.count,
                    name=resolved.line.name,
                    card=CardRefOut(
                        oracle_id=resolved.card.oracle_id, oracle_name=resolved.card.oracle_name
                    )
                    if resolved.card
                    else None,
                    suggestions=list(resolved.suggestions),
                )
                for resolved in imported.lines
                if resolved.line.section == section
            ]

        return cls(
            sections=[SectionOut(section=s, cards=lines_in(s)) for s in SECTIONS],
            warnings=[
                DeckWarningOut(kind=w.kind, message=w.message, line=w.line)
                for w in imported.warnings
            ],
        )


class DeckSummaryOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, deck: Deck) -> "DeckSummaryOut":
        return cls(
            id=deck.id, name=deck.name, created_at=deck.created_at, updated_at=deck.updated_at
        )


class DeckOut(DeckSummaryOut):
    decklist: str
    validation: DeckImportOut

    @classmethod
    def of_import(cls, deck: Deck, imported: DeckImport) -> "DeckOut":
        return cls(
            **DeckSummaryOut.of(deck).model_dump(),
            decklist=deck.decklist,
            validation=DeckImportOut.of(imported),
        )


def _deck_not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Deck not found")


decks_router = APIRouter(prefix="/decks")


@decks_router.post("/preview")
def preview_deck(body: DecklistIn, user: User, access: Decks) -> DeckImportOut:
    """Import validation without saving, for the Decks page's preview."""
    return DeckImportOut.of(import_decklist(body.decklist, access.cards))


@decks_router.post("", status_code=status.HTTP_201_CREATED)
def create_deck(body: DeckIn, user: User, access: Decks) -> DeckOut:
    imported = import_decklist(body.decklist, access.cards)
    return DeckOut.of_import(access.decks.create(user.id, body.name, body.decklist), imported)


@decks_router.get("")
def list_decks(user: User, access: Decks) -> list[DeckSummaryOut]:
    return [DeckSummaryOut.of(deck) for deck in access.decks.list_for_user(user.id)]


@decks_router.get("/{deck_id}")
def read_deck(deck_id: uuid.UUID, user: User, access: Decks) -> DeckOut:
    deck = access.decks.get(user.id, deck_id)
    if deck is None:
        raise _deck_not_found()
    return DeckOut.of_import(deck, import_decklist(deck.decklist, access.cards))


@decks_router.put("/{deck_id}")
def update_deck(deck_id: uuid.UUID, body: DeckIn, user: User, access: Decks) -> DeckOut:
    imported = import_decklist(body.decklist, access.cards)
    deck = access.decks.update(user.id, deck_id, body.name, body.decklist)
    if deck is None:
        raise _deck_not_found()
    return DeckOut.of_import(deck, imported)


@decks_router.delete("/{deck_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deck(deck_id: uuid.UUID, user: User, access: Decks) -> Response:
    if not access.decks.delete(user.id, deck_id):
        raise _deck_not_found()
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
    open_decks: OpenDecks,
    *,
    scores: ScoreClient | None = None,
    ping_database: PingDatabase | None = None,
    cors_origins: Sequence[str] = (),
) -> FastAPI:
    """`scores` is None when Langfuse isn't configured: feedback is then stored, not scored.

    `ping_database` None means there is no database to check (tests of other endpoints).
    """
    app = FastAPI(title="HexCoach API")
    # The frontend authenticates with a bearer header, never cookies, so no credentials mode.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_origins),
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.state.collaborators = _Collaborators(
        verifier, open_store, open_decks, scores, ping_database
    )
    # App-wide: the cap is enforced in the store, so any endpoint that writes a player
    # message gets a clear 422 rather than a 500.
    app.add_exception_handler(MessageTooLongError, _message_too_long)
    app.include_router(router)
    app.include_router(decks_router)
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

    @contextmanager
    def open_decks() -> Generator[DeckAccess]:
        with engine.begin() as connection:
            yield DeckAccess(SqlDeckStore(connection), SqlCardCatalog(connection))

    return create_app(
        supabase_verifier(supabase_url()),
        open_store,
        open_decks,
        scores=langfuse_scores(),
        ping_database=lambda: ping_database(engine),
        cors_origins=cors_allowed_origins(),
    )
