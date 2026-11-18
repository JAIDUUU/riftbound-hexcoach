"""Feedback (issue #19): the player's thumbs up/down on an answer, stored on the message
and, when the answer was traced, sent to Langfuse as a score on its trace."""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel

from backend.agent.tracing import ScoreClient, score_feedback
from backend.api.conversations import MessageOut
from backend.api.dependencies import Store, User, collaborators
from backend.conversations.store import Feedback, NotAnAnswerError, Rating

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations")


def score_client(request: Request) -> ScoreClient | None:
    return collaborators(request).scores


Scores = Annotated[ScoreClient | None, Depends(score_client)]


class FeedbackIn(BaseModel):
    rating: Rating


def _send_score(
    scores: ScoreClient, message_id: uuid.UUID, trace_id: str, feedback: Feedback
) -> None:
    """Score the vote in Langfuse after the response. The vote is already stored, so a
    failure is logged with everything needed to send the score again, and nothing else."""
    try:
        score_feedback(scores, message_id, trace_id, feedback)
    except Exception:
        _log.exception(
            "Could not send the feedback score of message %s (trace %s, rating %s,"
            " given at %s) to Langfuse",
            message_id,
            trace_id,
            feedback.rating,
            feedback.given_at.isoformat(),
        )


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
    except NotAnAnswerError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    if scores is not None and message.trace_id is not None and message.feedback is not None:
        # Runs after the store has committed, so Langfuse never gets a vote we lost.
        after_response.add_task(_send_score, scores, message.id, message.trace_id, message.feedback)
    return MessageOut.of(message)
