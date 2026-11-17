"""Whether a player may send another message right now: a per-minute throttle, then a
daily quota.

The throttle is in memory and per process: a burst is refused without touching the
database, and a restart (or a second process) starts it afresh. That is enough to stop
a runaway client; the daily quota is the real budget, and it lives in Postgres
(`UsageStore`) so it survives restarts and holds across processes. The day is the UTC
calendar day, so every quota resets at 00:00 UTC.

The numbers are configuration with placeholder defaults: Grill Decisions sets the real
ones once the free-tier limits of the providers and Supabase are verified.
"""

import math
import threading
import uuid
from collections import deque
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Literal

from backend.config import positive_int_env, require_positive
from backend.quota.store import UsageStore

DEFAULT_MESSAGES_PER_MINUTE = 5  # placeholder until the free-tier limits are verified
DEFAULT_MESSAGES_PER_DAY = 50  # placeholder until the free-tier limits are verified

_MINUTE = timedelta(minutes=1)

Clock = Callable[[], datetime]
"""The current time, timezone-aware."""

OpenUsage = Callable[[], AbstractContextManager[UsageStore]]
"""Opens the usage counter for one unit of work; leaving the context commits."""

QuotaCode = Literal["rate_limited", "daily_quota_reached"]


class QuotaExceededError(Exception):
    """The player has to wait before sending another message."""

    def __init__(self, code: QuotaCode, retry_after: int, message: str) -> None:
        self.code = code
        self.retry_after = retry_after  # whole seconds until a message would be accepted
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class QuotaSettings:
    messages_per_minute: int = DEFAULT_MESSAGES_PER_MINUTE
    messages_per_day: int = DEFAULT_MESSAGES_PER_DAY

    def __post_init__(self) -> None:
        require_positive("messages_per_minute", self.messages_per_minute)
        require_positive("messages_per_day", self.messages_per_day)


def quota_settings_from_env() -> QuotaSettings:
    return QuotaSettings(
        messages_per_minute=positive_int_env("MESSAGES_PER_MINUTE", DEFAULT_MESSAGES_PER_MINUTE),
        messages_per_day=positive_int_env("MESSAGES_PER_DAY", DEFAULT_MESSAGES_PER_DAY),
    )


def _seconds_until(moment: datetime, now: datetime) -> int:
    return max(1, math.ceil((moment - now).total_seconds()))


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MessageQuota:
    def __init__(
        self, settings: QuotaSettings, open_usage: OpenUsage, clock: Clock = _utc_now
    ) -> None:
        self.settings = settings
        self.open_usage = open_usage
        self.clock = clock
        self._lock = threading.Lock()
        self._recent: dict[uuid.UUID, deque[datetime]] = {}

    def admit(self, user_id: uuid.UUID) -> None:
        """Count one message for the player, or raise QuotaExceededError."""
        now = self.clock().astimezone(UTC)
        self._throttle(user_id, now)
        with self.open_usage() as usage:
            counted = usage.consume(user_id, now.date(), self.settings.messages_per_day)
        if counted is None:
            midnight = datetime.combine(now.date() + timedelta(days=1), time(), UTC)
            raise QuotaExceededError(
                "daily_quota_reached",
                _seconds_until(midnight, now),
                f"You've used all {self.settings.messages_per_day} of today's demo messages."
                " The quota resets at 00:00 UTC.",
            )

    def _throttle(self, user_id: uuid.UUID, now: datetime) -> None:
        with self._lock:
            recent = self._recent.setdefault(user_id, deque())
            while recent and recent[0] <= now - _MINUTE:
                recent.popleft()
            if len(recent) >= self.settings.messages_per_minute:
                raise QuotaExceededError(
                    "rate_limited",
                    _seconds_until(recent[0] + _MINUTE, now),
                    "You're sending messages too quickly. Please wait a moment.",
                )
            recent.append(now)
