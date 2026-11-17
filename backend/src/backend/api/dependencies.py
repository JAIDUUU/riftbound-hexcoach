"""What every route module shares: the app's collaborators and the request dependencies
built on them (the signed-in user, the conversation store and deck access for one request).

`create_app` (app.py) stores the collaborators on the app; the route modules only reach
them through `collaborators(request)` and the annotated dependencies below, so each area
of the API can live in its own module without knowing how the app was wired.
"""

import uuid
from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.agent.coach import Coach
from backend.agent.tracing import ScoreClient
from backend.api.auth import AuthenticatedUser, AuthError, AuthUnavailableError, TokenVerifier
from backend.api.turn import OpenCards, OpenStore
from backend.conversations.limits import Limits
from backend.conversations.store import ConversationStore
from backend.decks.access import DeckAccess, OpenDecks
from backend.quota.admission import MessageQuota

PingDatabase = Callable[[], None]
"""Runs one trivial query against the database; raises if it can't be reached."""

DeleteAccount = Callable[[uuid.UUID], None]
"""Deletes the user's Supabase Auth account, committed before it returns. Everything the
user owns cascades from it; a user who is already gone is not an error."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Collaborators:
    verifier: TokenVerifier
    open_store: OpenStore
    open_decks: OpenDecks
    coach: Coach
    delete_account: DeleteAccount
    scores: ScoreClient | None
    ping_database: PingDatabase | None
    open_cards: OpenCards | None
    limits: Limits
    quota: MessageQuota | None


def collaborators(request: Request) -> Collaborators:
    # Set by create_app; Starlette's app.state is untyped, so this is the one cast.
    return cast(Collaborators, request.app.state.collaborators)


_bearer = HTTPBearer(auto_error=False)
_CHALLENGE = {"WWW-Authenticate": "Bearer"}


def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthenticatedUser:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token", _CHALLENGE)
    try:
        return collaborators(request).verifier.verify(credentials.credentials)
    except AuthError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", _CHALLENGE
        ) from None
    except AuthUnavailableError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Sign-in is temporarily unavailable"
        ) from None


def conversation_store(request: Request) -> Generator[ConversationStore]:
    with collaborators(request).open_store() as store:
        yield store


def deck_access(request: Request) -> Generator[DeckAccess]:
    with collaborators(request).open_decks() as access:
        yield access


User = Annotated[AuthenticatedUser, Depends(current_user)]
# scope="function": the transaction commits before the response is sent, so a failed
# commit can never hide behind a 2xx the client already received.
Store = Annotated[ConversationStore, Depends(conversation_store, scope="function")]
Decks = Annotated[DeckAccess, Depends(deck_access, scope="function")]
