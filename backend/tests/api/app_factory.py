"""One way for API tests to build the app: every collaborator a test doesn't care about
gets a default that is unused or inert, so adding a collaborator to `create_app` only
touches the tests that use it.

The defaults: the fake Supabase verifier, a fresh in-memory conversation store, no decks,
a coach and an account deletion that fail the test if they ever run, and no Langfuse,
health ping, card catalog, CORS origins or message limits.
"""

from collections.abc import Generator, Sequence
from contextlib import contextmanager

from fastapi import FastAPI

from backend.agent.coach import Coach
from backend.agent.tracing import ScoreClient
from backend.api.app import create_app
from backend.api.auth import TokenVerifier
from backend.api.cards import OpenCards
from backend.api.dependencies import DeleteAccount, PingDatabase
from backend.api.turn import OpenStore
from backend.cards.catalog import CardCatalog
from backend.conversations.limits import Limits
from backend.conversations.store import ConversationStore
from backend.decks.access import OpenDecks
from backend.quota.admission import MessageQuota
from tests.api.accounts import unused_account_deletion
from tests.api.coaches import unused_coach
from tests.api.tokens import fake_verifier
from tests.conversations.memory_store import InMemoryConversationStore
from tests.decks.memory_store import no_decks


def opening(store: ConversationStore) -> OpenStore:
    """Opens the same store for every unit of work, as a request would see a database."""

    @contextmanager
    def open_store() -> Generator[ConversationStore]:
        yield store

    return open_store


def opening_cards(catalog: CardCatalog) -> OpenCards:
    @contextmanager
    def open_cards() -> Generator[CardCatalog]:
        yield catalog

    return open_cards


def make_app(
    *,
    store: ConversationStore | None = None,
    open_store: OpenStore | None = None,
    verifier: TokenVerifier | None = None,
    open_decks: OpenDecks = no_decks,
    coach: Coach = unused_coach,
    delete_account: DeleteAccount = unused_account_deletion,
    scores: ScoreClient | None = None,
    ping_database: PingDatabase | None = None,
    open_cards: OpenCards | None = None,
    cors_origins: Sequence[str] = (),
    limits: Limits | None = None,
    quota: MessageQuota | None = None,
) -> FastAPI:
    """`store` is shorthand for `open_store=opening(store)`; pass at most one of them."""
    assert store is None or open_store is None, "pass store or open_store, not both"
    if open_store is None:
        open_store = opening(store or InMemoryConversationStore(Limits()))
    return create_app(
        verifier or fake_verifier(),
        open_store,
        open_decks=open_decks,
        coach=coach,
        delete_account=delete_account,
        scores=scores,
        ping_database=ping_database,
        open_cards=open_cards,
        cors_origins=cors_origins,
        limits=limits,
        quota=quota,
    )
