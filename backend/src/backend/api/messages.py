"""Sending a message (issues #12, #18, #20): every check that can refuse it runs before
the event stream opens, then the turn streams as server-sent events (turn.py)."""

import logging
import uuid
from collections.abc import Callable, Iterator, Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field

from backend.agent.coach import Question
from backend.api.auth import AuthenticatedUser
from backend.api.conversations import conversation_not_found
from backend.api.dependencies import User, collaborators
from backend.api.turn import PreparedTurn, stream_turn
from backend.conversations.limits import TooManyMentionsError
from backend.mentions import UnknownMentionError, resolve_mentions
from backend.turns import Mention, Mentioned, MentionKind, answered_turns

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations")


def _reserve_slot(request: Request, user: AuthenticatedUser) -> Callable[[], None]:
    """Take the message's slot in the player's limits (429 when full); returns the refund."""
    quota = collaborators(request).quota
    if quota is None:
        return lambda: None
    reservation = quota.reserve(user.id)
    return lambda: quota.refund(reservation)


def _refund_quietly(refund: Callable[[], None]) -> None:
    """Refund on the way out of a refusal: a failing refund is logged, never raised, so
    the player still gets the refusal's own 404 or 422 rather than a 500."""
    try:
        refund()
    except Exception:
        _log.exception("Could not refund the quota slot of a refused message")


class MentionIn(BaseModel):
    """An @ mention: a Card by its oracle id (the client card index's `id`), or a Deck."""

    kind: MentionKind
    id: uuid.UUID


class MessageIn(BaseModel):
    """A player message. The length cap is configuration, enforced by the store."""

    content: str = Field(min_length=1)
    mentions: list[MentionIn] = Field(default_factory=list[MentionIn])


def _check_and_resolve_mentions(
    request: Request, user_id: uuid.UUID, mentions: Sequence[MentionIn]
) -> tuple[Mentioned, ...]:
    """Hold the mentions to the cap, then resolve them; either failing is a 422."""
    if not mentions:
        return ()
    app = collaborators(request)
    try:
        app.limits.check_mentions(len(mentions))
        with app.open_decks() as access:
            return resolve_mentions([Mention(m.kind, m.id) for m in mentions], user_id, access)
    except (TooManyMentionsError, UnknownMentionError) as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None


def begin_turn(
    conversation_id: uuid.UUID, body: MessageIn, user: User, request: Request
) -> PreparedTurn:
    """Every check that can refuse a message, run before the event stream opens so a
    refusal is a plain HTTP error rather than an `error` event inside a 200: the
    conversation must be the user's (404), the message must fit the cap (422), its
    mentions must resolve to Cards and the user's own Decks (422), and only then must the
    player be within their message limits (429), so a refused message never counts. The
    player's message is committed here; the answer is stored when it is ready.

    Each step is its own short transaction, one after another, so a request never holds
    two pooled connections at once. If storing the message fails after the slot was
    taken, the slot is refunded; a turn that later ends in `error` refunds it too."""
    app = collaborators(request)
    with app.open_store() as store:
        history = store.history(user.id, conversation_id)
    if history is None:
        raise conversation_not_found()
    app.limits.check_message(body.content)
    mentions = _check_and_resolve_mentions(request, user.id, body.mentions)
    refund = _reserve_slot(request, user)
    try:
        with app.open_store() as store:
            if store.add_message(user.id, conversation_id, "user", body.content) is None:
                raise conversation_not_found()  # deleted since its history was read
    except BaseException:
        _refund_quietly(refund)
        raise
    question = Question(
        text=body.content,
        history=tuple(answered_turns(history)),
        user_id=user.id,
        conversation_id=conversation_id,
        mentions=mentions,
    )
    return PreparedTurn(question=question, answer_id=uuid.uuid4(), refund=refund)


@router.post("/{conversation_id}/messages", response_class=EventSourceResponse)
def post_message(
    turn: Annotated[PreparedTurn, Depends(begin_turn)], request: Request
) -> Iterator[ServerSentEvent]:
    app = collaborators(request)
    yield from stream_turn(turn, app.coach, app.open_store, app.open_cards)
