"""The HTTP API: Supabase-authenticated conversations (issue #11) and decks (issue #16).

`create_app` takes its collaborators (the token verifier and a way to open each store
for one request), so tests build the app with fake keys and in-memory stores;
`production_app` wires Supabase's JWKS and Postgres. Serve it with `uv run backend serve`.
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
from backend.api.auth import (
    AuthenticatedUser,
    AuthError,
    AuthUnavailableError,
    TokenVerifier,
    supabase_verifier,
)
from backend.cards.catalog import CardCatalog, SqlCardCatalog
from backend.config import supabase_url
from backend.conversations.limits import MAX_TITLE_CHARS, MessageTooLongError, limits_from_env
from backend.conversations.store import (
    Conversation,
    ConversationDetail,
    ConversationStore,
    SqlConversationStore,
)
from backend.decks.importing import DeckImport, import_decklist
from backend.decks.parse import SECTIONS, Section
from backend.decks.store import MAX_DECK_NAME_CHARS, Deck, DeckStore, SqlDeckStore
from backend.decks.warnings import WarningKind

OpenStore = Callable[[], AbstractContextManager[ConversationStore]]
"""Opens a store for one request; leaving the context commits (or rolls back on error)."""


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


def _message_too_long(request: Request, error: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": str(error)}
    )


def create_app(verifier: TokenVerifier, open_store: OpenStore, open_decks: OpenDecks) -> FastAPI:
    app = FastAPI(title="HexCoach API")
    app.state.collaborators = _Collaborators(verifier, open_store, open_decks)
    # App-wide: the cap is enforced in the store, so any endpoint that writes a player
    # message gets a clear 422 rather than a 500.
    app.add_exception_handler(MessageTooLongError, _message_too_long)
    app.include_router(router)
    app.include_router(decks_router)
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

    @contextmanager
    def open_decks() -> Generator[DeckAccess]:
        with engine.begin() as connection:
            yield DeckAccess(SqlDeckStore(connection), SqlCardCatalog(connection))

    return create_app(supabase_verifier(supabase_url()), open_store, open_decks)
