import threading
import time
import uuid
from collections import deque
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from backend.config import InvalidConfigError
from backend.quota import admission
from backend.quota.admission import (
    DEFAULT_MESSAGES_PER_DAY,
    DEFAULT_MESSAGES_PER_MINUTE,
    MessageQuota,
    QuotaExceededError,
    QuotaSettings,
    quota_settings_from_env,
)
from backend.quota.store import UsageStore
from tests.quota.fake_clock import FakeClock
from tests.quota.memory_usage import InMemoryUsageStore, memory_quota

ALICE = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")
BOB = uuid.UUID("bbbbbbbb-0000-4000-8000-000000000002")

EVENING = datetime(2026, 11, 17, 22, 30, tzinfo=UTC)


_quota = memory_quota


def _refusal(quota: MessageQuota, user: uuid.UUID = ALICE) -> QuotaExceededError:
    with pytest.raises(QuotaExceededError) as caught:
        quota.reserve(user)
    return caught.value


def test_a_player_may_send_up_to_the_per_minute_limit_then_must_wait_a_minute() -> None:
    clock = FakeClock(EVENING)
    quota = _quota(QuotaSettings(messages_per_minute=2, messages_per_day=100), clock)

    quota.reserve(ALICE)
    quota.reserve(ALICE)
    refused = _refusal(quota)

    assert (refused.code, refused.retry_after) == ("rate_limited", 60)
    clock.advance(seconds=59)
    assert _refusal(quota).retry_after == 1
    clock.advance(seconds=1)
    quota.reserve(ALICE)


def test_the_minute_slides_so_each_message_frees_its_slot_a_minute_after_it_was_sent() -> None:
    clock = FakeClock(EVENING)
    quota = _quota(QuotaSettings(messages_per_minute=2, messages_per_day=100), clock)
    quota.reserve(ALICE)  # at 0s
    clock.advance(seconds=20)
    quota.reserve(ALICE)  # at 20s
    clock.advance(seconds=10)

    assert _refusal(quota).retry_after == 30  # the 0s message frees up at 60s
    clock.advance(seconds=30)
    quota.reserve(ALICE)  # at 60s
    assert _refusal(quota).retry_after == 20  # now the 20s message is the oldest


def test_one_players_burst_does_not_throttle_another() -> None:
    clock = FakeClock(EVENING)
    quota = _quota(QuotaSettings(messages_per_minute=1, messages_per_day=100), clock)
    quota.reserve(ALICE)

    assert _refusal(quota, ALICE).code == "rate_limited"
    quota.reserve(BOB)


def test_the_daily_quota_runs_out_and_comes_back_at_utc_midnight() -> None:
    clock = FakeClock(EVENING)  # 22:30 UTC
    quota = _quota(QuotaSettings(messages_per_minute=100, messages_per_day=2), clock)
    quota.reserve(ALICE)
    quota.reserve(ALICE)

    refused = _refusal(quota)

    assert (refused.code, refused.retry_after) == ("daily_quota_reached", 90 * 60)
    quota.reserve(BOB)  # everyone has their own day
    clock.advance(minutes=89, seconds=59)
    assert _refusal(quota).retry_after == 1
    clock.advance(seconds=1)
    quota.reserve(ALICE)


def test_the_day_is_the_utc_day_whatever_zone_the_clock_reports() -> None:
    brasilia = timezone(timedelta(hours=-3))
    clock = FakeClock(datetime(2026, 11, 17, 20, 59, tzinfo=brasilia))  # 23:59 UTC
    quota = _quota(QuotaSettings(messages_per_minute=100, messages_per_day=1), clock)
    quota.reserve(ALICE)
    assert _refusal(quota).retry_after == 60

    clock.advance(minutes=1)  # 21:00 in Brasilia, a new day in UTC
    quota.reserve(ALICE)


def test_a_throttled_message_does_not_count_against_the_day() -> None:
    clock = FakeClock(EVENING)
    quota = _quota(QuotaSettings(messages_per_minute=1, messages_per_day=2), clock)
    quota.reserve(ALICE)
    assert _refusal(quota).code == "rate_limited"

    clock.advance(minutes=1)
    quota.reserve(ALICE)
    clock.advance(minutes=1)
    assert _refusal(quota).code == "daily_quota_reached"


class _DequeThatYields(deque[datetime]):
    """Hands the GIL to another thread right after its length is read, which widens the
    gap between counting the minute's slots and taking one far enough for threads to hit."""

    def __len__(self) -> int:
        length = super().__len__()
        time.sleep(0.001)
        return length


def test_messages_sent_at_once_never_take_more_than_the_minutes_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admission, "deque", _DequeThatYields)
    senders, per_minute = 8, 3
    quota = _quota(
        QuotaSettings(messages_per_minute=per_minute, messages_per_day=1000), FakeClock(EVENING)
    )
    together = threading.Barrier(senders)
    sent: list[bool] = []

    def send() -> None:
        together.wait()
        try:
            quota.reserve(ALICE)
        except QuotaExceededError:
            sent.append(False)
        else:
            sent.append(True)

    threads = [threading.Thread(target=send) for _ in range(senders)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sent.count(True) == per_minute


def test_limits_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        QuotaSettings(messages_per_day=0)


def test_limits_come_from_the_environment_with_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # Blank, not deleted: load_dotenv would re-populate a deleted variable from .env.
    monkeypatch.setenv("MESSAGES_PER_MINUTE", "")
    monkeypatch.setenv("MESSAGES_PER_DAY", "7")

    assert quota_settings_from_env() == QuotaSettings(
        messages_per_minute=DEFAULT_MESSAGES_PER_MINUTE, messages_per_day=7
    )
    assert DEFAULT_MESSAGES_PER_DAY != 7  # the override really overrode something


def test_a_bad_limit_setting_is_a_clear_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MESSAGES_PER_MINUTE", "0")

    with pytest.raises(InvalidConfigError, match="MESSAGES_PER_MINUTE must be positive"):
        quota_settings_from_env()


def test_a_refund_gives_back_both_the_minute_slot_and_the_day_slot() -> None:
    clock = FakeClock(EVENING)
    quota = _quota(QuotaSettings(messages_per_minute=1, messages_per_day=1), clock)
    failed = quota.reserve(ALICE)

    quota.refund(failed)

    quota.reserve(ALICE)  # same instant: neither limit holds the failed message
    assert _refusal(quota).code == "rate_limited"


def test_refunding_twice_gives_back_only_once() -> None:
    clock = FakeClock(EVENING)
    quota = _quota(QuotaSettings(messages_per_minute=100, messages_per_day=2), clock)
    quota.reserve(ALICE)
    failed = quota.reserve(ALICE)

    quota.refund(failed)
    quota.refund(failed)

    quota.reserve(ALICE)
    assert _refusal(quota).code == "daily_quota_reached"


def test_a_run_that_fails_after_midnight_refunds_the_day_it_was_counted_on() -> None:
    clock = FakeClock(datetime(2026, 11, 17, 23, 59, 30, tzinfo=UTC))
    quota = _quota(QuotaSettings(messages_per_minute=100, messages_per_day=1), clock)
    failed = quota.reserve(ALICE)
    clock.advance(minutes=1)  # the run ends on the next UTC day
    quota.reserve(ALICE)  # the new day's one message

    quota.refund(failed)

    assert _refusal(quota).code == "daily_quota_reached"  # today's message still counts


def test_a_message_the_daily_quota_refuses_takes_no_minute_slot() -> None:
    clock = FakeClock(EVENING)
    quota = _quota(QuotaSettings(messages_per_minute=1, messages_per_day=1), clock)
    first = quota.reserve(ALICE)
    clock.advance(minutes=1)
    assert _refusal(quota).code == "daily_quota_reached"

    quota.refund(first)

    quota.reserve(ALICE)  # the refused attempt left the minute free


class _FlakyUsage(InMemoryUsageStore):
    """Its first release fails, as a dropped database connection would."""

    def __init__(self) -> None:
        super().__init__()
        self.failures_left = 1

    def release(self, user_id: uuid.UUID, day: date) -> None:
        if self.failures_left:
            self.failures_left -= 1
            raise ConnectionError("usage table unreachable")
        super().release(user_id, day)


def test_a_refund_that_fails_can_be_retried_and_is_logged_with_what_to_fix(
    caplog: pytest.LogCaptureFixture,
) -> None:
    usage = _FlakyUsage()

    @contextmanager
    def open_usage() -> Generator[UsageStore]:
        yield usage

    quota = MessageQuota(QuotaSettings(messages_per_day=1), open_usage, FakeClock(EVENING))
    reservation = quota.reserve(ALICE)

    with pytest.raises(ConnectionError):
        quota.refund(reservation)

    assert str(ALICE) in caplog.text and "2026-11-17" in caplog.text
    assert not reservation.refunded
    quota.refund(reservation)
    assert reservation.refunded
    quota.reserve(ALICE)  # the day's one slot is free again
