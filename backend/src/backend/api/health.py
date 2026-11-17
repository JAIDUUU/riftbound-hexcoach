"""`/health` (issue #22), public on purpose: the scheduled keep-alive hits it so the free
Supabase project sees a query and doesn't pause. It says only "ok" or 503."""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from backend.api.dependencies import collaborators

_log = logging.getLogger(__name__)


class HealthOut(BaseModel):
    status: Literal["ok"]


router = APIRouter()


@router.get("/health")
def health(request: Request) -> HealthOut:
    """Unauthenticated, for the keep-alive ping: a query keeps the free Supabase project awake."""
    ping_database = collaborators(request).ping_database
    if ping_database is not None:
        try:
            ping_database()
        except Exception:
            _log.exception("Health check: the database did not answer")
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Database is unavailable"
            ) from None
    return HealthOut(status="ok")
