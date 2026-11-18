"""Whether a player may send another message right now: a per-minute throttle, then a
daily quota.

Only answered messages count. A message reserves a slot in both limits once every other
pre-run check has passed, and the slot is refunded if the turn doesn't end in an answer
(see `begin_turn` and `run_turn`), so refused messages and failed runs cost the player
nothing.

The throttle is in memory and per process: a burst is refused without touching the
database, and a restart (or a second process) starts it afresh. That is enough to stop
a runaway client; the daily quota is the real budget, and it lives in Postgres
(`UsageStore`) so it survives restarts and holds across processes. The day is the UTC
calendar day, so every quota resets at 00:00 UTC.

The numbers are configuration with placeholder defaults: Grill Decisions sets the real
ones once the free-tier limits of the providers and Supabase are verified.
"""

import logging
import math
import threading
import uuid
from collections import deque
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from backend.config import positive_int_env, require_positive
from backend.quota.store import UsageStore

_log = logging.getLogger(__name__)

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


@dataclass(eq=False, slots=True)
class Reservation:
    """One message's slot in both limits, held until its turn ends."""

    user_id: uuid.UUID
    at: datetime  # UTC; the minute slot it holds, and so the day it was counted on
    refund_state: Literal["none", "in_progress", "done"] = "none"
    minute_freed: bool = False

    @property
    def day(self) -> date:
        return self.at.date()

    @property
    def refunded(self) -> bool:
        return self.refund_state == "done"


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

    def reserve(self, user_id: uuid.UUID) -> Reservation:
        """Take a slot for one message, or raise QuotaExceededError having taken none.

        Each limit is checked and taken in one step (under a lock, and in one SQL
        statement), so two messages sent at once can't both take the last slot.
        """
        now = self.clock().astimezone(UTC)
        reservation = Reservation(user_id, now)
        self._take_minute_slot(reservation)
        try:
            with self.open_usage() as usage:
                counted = usage.consume(user_id, now.date(), self.settings.messages_per_day)
        except BaseException:
            self._free_minute_slot(reservation)
            raise
        if counted is None:
            self._free_minute_slot(reservation)
            midnight = datetime.combine(now.date() + timedelta(days=1), time(), UTC)
            raise QuotaExceededError(
                "daily_quota_reached",
                _seconds_until(midnight, now),
                f"You've used all {self.settings.messages_per_day} of today's demo messages."
                " The quota resets at 00:00 UTC.",
            )
        return reservation

    def refund(self, reservation: Reservation) -> None:
        """Give the message's slots back (its turn didn't end in an answer).

        Once a refund succeeds, further refunds of the reservation do nothing, as does
        one made while another is under way. If giving back the daily slot fails, the
        error is logged with what an operator needs to give it back by hand, the
        reservation stays refundable, and the error is raised.
        """
        with self._lock:
            if reservation.refund_state != "none":
                return
            reservation.refund_state = "in_progress"
            if not reservation.minute_freed:
                self._free_minute_slot_locked(reservation)
                reservation.minute_freed = True
        try:
            with self.open_usage() as usage:
                usage.release(reservation.user_id, reservation.day)
        except BaseException:
            _log.exception(
                "Could not give back the daily message of user %s on %s (UTC);"
                " their usage count for that day is one too high",
                reservation.user_id,
                reservation.day.isoformat(),
            )
            with self._lock:
                reservation.refund_state = "none"
            raise
        with self._lock:
            reservation.refund_state = "done"

    def _take_minute_slot(self, reservation: Reservation) -> None:
        now = reservation.at
        with self._lock:
            recent = self._recent.setdefault(reservation.user_id, deque())
            while recent and recent[0] <= now - _MINUTE:
                recent.popleft()
            if len(recent) >= self.settings.messages_per_minute:
                raise QuotaExceededError(
                    "rate_limited",
                    _seconds_until(recent[0] + _MINUTE, now),
                    "You're sending messages too quickly. Please wait a moment.",
                )
            recent.append(now)

    def _free_minute_slot(self, reservation: Reservation) -> None:
        with self._lock:
            self._free_minute_slot_locked(reservation)

    def _free_minute_slot_locked(self, reservation: Reservation) -> None:
        recent = self._recent.get(reservation.user_id)
        if recent is not None and reservation.at in recent:
            recent.remove(reservation.at)  # already gone if its minute has passed
