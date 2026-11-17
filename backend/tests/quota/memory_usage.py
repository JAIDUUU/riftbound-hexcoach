"""An in-memory UsageStore for DB-free quota and API tests.

test_usage_store_contract.py runs the same counting rules against this and the real
SqlUsageStore, so tests built on this fake can't drift from production.
"""

import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import date

from backend.quota.admission import Clock, MessageQuota, QuotaSettings
from backend.quota.store import UsageStore


class InMemoryUsageStore:
    def __init__(self) -> None:
        self.counts: dict[tuple[uuid.UUID, date], int] = {}

    def consume(self, user_id: uuid.UUID, day: date, limit: int) -> int | None:
        used = self.counts.get((user_id, day), 0)
        if used >= limit:
            return None
        self.counts[user_id, day] = used + 1
        return used + 1


def memory_quota(settings: QuotaSettings, clock: Clock) -> MessageQuota:
    """A MessageQuota counting in a fresh InMemoryUsageStore."""
    usage = InMemoryUsageStore()

    @contextmanager
    def open_usage() -> Generator[UsageStore]:
        yield usage

    return MessageQuota(settings, open_usage, clock)
