import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone

import pytest

from backend.config import InvalidConfigError
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
from tests.quota.memory_usage import InMemoryUsageStore

ALICE = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")
BOB = uuid.UUID("bbbbbbbb-0000-4000-8000-000000000002")

EVENING = datetime(2026, 11, 17, 22, 30, tzinfo=UTC)


def _quota(settings: QuotaSettings, clock: FakeClock) -> MessageQuota:
    usage = InMemoryUsageStore()

    @contextmanager
    def open_usage() -> Generator[UsageStore]:
        yield usage

    return MessageQuota(settings, open_usage, clock)


def _refusal(quota: MessageQuota, user: uuid.UUID = ALICE) -> QuotaExceededError:
    with pytest.raises(QuotaExceededError) as caught:
        quota.admit(user)
    return caught.value


def test_a_player_may_send_up_to_the_per_minute_limit_then_must_wait_a_minute() -> None:
    clock = FakeClock(EVENING)
    quota = _quota(QuotaSettings(messages_per_minute=2, messages_per_day=100), clock)

    quota.admit(ALICE)
    quota.admit(ALICE)
    refused = _refusal(quota)

    assert (refused.code, refused.retry_after) == ("rate_limited", 60)
    clock.advance(seconds=59)
    assert _refusal(quota).retry_after == 1
    clock.advance(seconds=1)
    quota.admit(ALICE)


def test_the_minute_slides_so_each_message_frees_its_slot_a_minute_after_it_was_sent() -> None:
    clock = FakeClock(EVENING)
    quota = _quota(QuotaSettings(messages_per_minute=2, messages_per_day=100), clock)
    quota.admit(ALICE)  # at 0s
    clock.advance(seconds=20)
    quota.admit(ALICE)  # at 20s
    clock.advance(seconds=10)

    assert _refusal(quota).retry_after == 30  # the 0s message frees up at 60s
    clock.advance(seconds=30)
    quota.admit(ALICE)  # at 60s
    assert _refusal(quota).retry_after == 20  # now the 20s message is the oldest


def test_one_players_burst_does_not_throttle_another() -> None:
    clock = FakeClock(EVENING)
    quota = _quota(QuotaSettings(messages_per_minute=1, messages_per_day=100), clock)
    quota.admit(ALICE)

    assert _refusal(quota, ALICE).code == "rate_limited"
    quota.admit(BOB)


def test_the_daily_quota_runs_out_and_comes_back_at_utc_midnight() -> None:
    clock = FakeClock(EVENING)  # 22:30 UTC
    quota = _quota(QuotaSettings(messages_per_minute=100, messages_per_day=2), clock)
    quota.admit(ALICE)
    quota.admit(ALICE)

    refused = _refusal(quota)

    assert (refused.code, refused.retry_after) == ("daily_quota_reached", 90 * 60)
    quota.admit(BOB)  # everyone has their own day
    clock.advance(minutes=89, seconds=59)
    assert _refusal(quota).retry_after == 1
    clock.advance(seconds=1)
    quota.admit(ALICE)


def test_the_day_is_the_utc_day_whatever_zone_the_clock_reports() -> None:
    brasilia = timezone(timedelta(hours=-3))
    clock = FakeClock(datetime(2026, 11, 17, 20, 59, tzinfo=brasilia))  # 23:59 UTC
    quota = _quota(QuotaSettings(messages_per_minute=100, messages_per_day=1), clock)
    quota.admit(ALICE)
    assert _refusal(quota).retry_after == 60

    clock.advance(minutes=1)  # 21:00 in Brasilia, a new day in UTC
    quota.admit(ALICE)


def test_a_throttled_message_does_not_count_against_the_day() -> None:
    clock = FakeClock(EVENING)
    quota = _quota(QuotaSettings(messages_per_minute=1, messages_per_day=2), clock)
    quota.admit(ALICE)
    assert _refusal(quota).code == "rate_limited"

    clock.advance(minutes=1)
    quota.admit(ALICE)
    clock.advance(minutes=1)
    assert _refusal(quota).code == "daily_quota_reached"


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
