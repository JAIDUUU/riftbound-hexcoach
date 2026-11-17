"""The daily message counter, one row per user per UTC day.

Counting and the limit check are a single statement, so two messages sent at the same
moment can never both take the last slot. The caller decides which day it is (see
`MessageQuota`), which keeps the day boundary in one place and testable with a fake clock.
"""

import uuid
from datetime import date
from typing import Protocol

from sqlalchemy import Connection
from sqlalchemy.dialects.postgresql import insert

from backend.quota.schema import daily_usage_table


class UsageStore(Protocol):
    def consume(self, user_id: uuid.UUID, day: date, limit: int) -> int | None:
        """Count one message against the user's day if fewer than `limit` are counted:
        the new count, or None (and nothing counted) when the day is already full."""
        ...


class SqlUsageStore:
    """UsageStore over Postgres; runs inside the caller's connection/transaction."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def consume(self, user_id: uuid.UUID, day: date, limit: int) -> int | None:
        statement = insert(daily_usage_table).values(user_id=user_id, day=day, messages=1)
        statement = statement.on_conflict_do_update(
            index_elements=[daily_usage_table.c.user_id, daily_usage_table.c.day],
            set_={"messages": daily_usage_table.c.messages + 1},
            where=daily_usage_table.c.messages < limit,
        ).returning(daily_usage_table.c.messages)
        return self.connection.execute(statement).scalar_one_or_none()
