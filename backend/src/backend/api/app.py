"""The HTTP API (issues #11, #12, #16, #19, #21, #22): Supabase-authenticated
conversations, streamed chat, feedback, decks, account deletion and a health check.

This module is the composition point. Each area's routes live in their own module
(conversations, messages, feedback, decks, account, health) and reach the app's
collaborators through `dependencies.py`.

`create_app` takes those collaborators (the token verifier, a way to open the conversation
store and the decks for one request, the coach that answers messages, the account
deletion, the Langfuse client feedback is scored with, a database ping for `/health`, and
the card catalog that answers' Card tags are checked against),
so tests build the app with fake keys, in-memory stores, a scripted coach, a recording
account deletion and a fake Langfuse; `production_app` wires Supabase's JWKS, Postgres,
the real agent, Langfuse and the CORS origins from the environment. Serve it with
`uv run backend serve`.
"""

import uuid
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import Literal, cast

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.agent.coach import Coach
from backend.agent.tracing import ScoreClient, langfuse_scores
from backend.api import account, conversations, decks, feedback, health, messages
from backend.api.auth import TokenVerifier, supabase_verifier
from backend.api.cards import OpenCards
from backend.api.dependencies import Collaborators, DeleteAccount, PingDatabase
from backend.api.turn import OpenStore
from backend.cards.catalog import CardCatalog, SqlCardCatalog
from backend.config import cors_allowed_origins, supabase_url
from backend.conversations.limits import (
    Limits,
    MessageTooLongError,
    TooManyMentionsError,
    limits_from_env,
)
from backend.conversations.store import ConversationStore, SqlConversationStore
from backend.decks.access import DeckAccess, OpenDecks
from backend.decks.importing import DecklistTooLongError, max_decklist_chars_from_env
from backend.decks.store import SqlDeckStore
from backend.mentions import UnknownMentionError
from backend.quota.admission import MessageQuota, QuotaExceededError, quota_settings_from_env
from backend.quota.store import SqlUsageStore, UsageStore

RefusalCode = Literal[
    "message_too_long", "decklist_too_long", "too_many_mentions", "unknown_card", "unknown_deck"
]
"""Why a player's message or decklist was refused with a 422 (request validation errors
keep FastAPI's own shape)."""


_REFUSAL_CODES: dict[type[Exception], RefusalCode] = {
    MessageTooLongError: "message_too_long",
    DecklistTooLongError: "decklist_too_long",
    TooManyMentionsError: "too_many_mentions",
}


def _refusal_code(error: Exception) -> RefusalCode:
    if isinstance(error, UnknownMentionError):
        return "unknown_card" if error.mention.kind == "card" else "unknown_deck"
    return _REFUSAL_CODES[type(error)]


def _refused(request: Request, error: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": str(error), "code": _refusal_code(error)},
    )


def _quota_exceeded(request: Request, error: Exception) -> JSONResponse:
    # Retry-After is repeated in the body: a cross-origin fetch can't read the header
    # unless CORS exposes it.
    refusal = cast(QuotaExceededError, error)
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "detail": refusal.message,
            "code": refusal.code,
            "retry_after": refusal.retry_after,
        },
        headers={"Retry-After": str(refusal.retry_after)},
    )


def create_app(
    verifier: TokenVerifier,
    open_store: OpenStore,
    *,
    open_decks: OpenDecks,
    coach: Coach,
    delete_account: DeleteAccount,
    scores: ScoreClient | None = None,
    ping_database: PingDatabase | None = None,
    open_cards: OpenCards | None = None,
    cors_origins: Sequence[str] = (),
    limits: Limits | None = None,
    quota: MessageQuota | None = None,
) -> FastAPI:
    """`scores` is None when Langfuse isn't configured: feedback is then stored, not scored.

    `ping_database` None means there is no database to check, `open_cards` None means
    no Card tag ever validates, and `quota` None means messages are not limited per player
    (tests of other endpoints).
    `limits` holds the caps the API checks itself (message length and mentions, before a
    message takes a quota slot; the store still enforces the message and history caps);
    None means the defaults.
    """
    app = FastAPI(title="HexCoach API")
    # The frontend authenticates with a bearer header, never cookies, so no credentials mode.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_origins),
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.state.collaborators = Collaborators(
        verifier=verifier,
        open_store=open_store,
        open_decks=open_decks,
        coach=coach,
        delete_account=delete_account,
        scores=scores,
        ping_database=ping_database,
        open_cards=open_cards,
        limits=limits or Limits(),
        quota=quota,
    )
    # App-wide: the caps are enforced in the store and in import_decklist, so any endpoint
    # that takes a player message or decklist gets a clear 422 rather than a 500.
    for refusal in (*_REFUSAL_CODES, UnknownMentionError):
        app.add_exception_handler(refusal, _refused)
    app.add_exception_handler(QuotaExceededError, _quota_exceeded)
    for area in (conversations, messages, feedback, decks, account, health):
        app.include_router(area.router)
    return app


def production_app() -> FastAPI:
    """The API wired to Supabase Auth, Postgres and the provider chain (an ASGI factory
    for uvicorn)."""
    from backend.accounts import delete_account
    from backend.agent.coach import database_coach
    from backend.db import make_engine, ping_database
    from backend.llm.providers import chat_chain

    engine = make_engine()
    limits = limits_from_env()
    max_decklist_chars = max_decklist_chars_from_env()

    @contextmanager
    def open_store() -> Generator[ConversationStore]:
        with engine.begin() as connection:
            yield SqlConversationStore(connection, limits)

    @contextmanager
    def open_decks() -> Generator[DeckAccess]:
        with engine.begin() as connection:
            yield DeckAccess(
                SqlDeckStore(connection), SqlCardCatalog(connection), max_decklist_chars
            )

    @contextmanager
    def open_usage() -> Generator[UsageStore]:
        with engine.begin() as connection:
            yield SqlUsageStore(connection)

    @contextmanager
    def open_cards() -> Generator[CardCatalog]:
        with engine.connect() as connection:
            yield SqlCardCatalog(connection)

    def delete_user(user_id: uuid.UUID) -> None:
        with engine.begin() as connection:
            delete_account(connection, user_id)

    return create_app(
        supabase_verifier(supabase_url()),
        open_store,
        open_decks=open_decks,
        coach=database_coach(engine, chat_chain()),
        delete_account=delete_user,
        scores=langfuse_scores(),
        ping_database=lambda: ping_database(engine),
        open_cards=open_cards,
        cors_origins=cors_allowed_origins(),
        limits=limits,
        quota=MessageQuota(quota_settings_from_env(), open_usage),
    )
