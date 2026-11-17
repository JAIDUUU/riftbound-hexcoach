import pytest

from backend.config import InvalidConfigError
from backend.conversations.limits import (
    DEFAULT_MAX_HISTORY_MESSAGES,
    DEFAULT_MAX_MENTIONS,
    DEFAULT_MAX_MESSAGE_CHARS,
    Limits,
    MessageTooLongError,
    TooManyMentionsError,
    limits_from_env,
)


def test_messages_up_to_the_cap_pass_and_longer_ones_are_refused() -> None:
    limits = Limits(max_message_chars=10)

    limits.check_message("x" * 10)
    with pytest.raises(MessageTooLongError) as caught:
        limits.check_message("x" * 11)

    assert (caught.value.length, caught.value.cap) == (11, 10)


def test_caps_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        Limits(max_history_messages=0)


def test_caps_come_from_the_environment_with_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # Blank, not deleted: load_dotenv would re-populate a deleted variable from .env.
    monkeypatch.setenv("MAX_MESSAGE_CHARS", "")
    monkeypatch.setenv("MAX_HISTORY_MESSAGES", "6")

    assert limits_from_env() == Limits(
        max_message_chars=DEFAULT_MAX_MESSAGE_CHARS, max_history_messages=6
    )
    assert DEFAULT_MAX_HISTORY_MESSAGES != 6  # the override really overrode something


def test_mentions_up_to_the_cap_pass_and_more_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_MENTIONS", "3")
    limits = limits_from_env()

    limits.check_mentions(3)
    with pytest.raises(TooManyMentionsError, match="4 mentions; the limit is 3"):
        limits.check_mentions(4)
    assert DEFAULT_MAX_MENTIONS != 3


@pytest.mark.parametrize(
    ("raw", "problem"),
    [("lots", "whole number"), ("4.5", "whole number"), ("0", "positive"), ("-3", "positive")],
)
def test_a_bad_cap_setting_is_a_clear_config_error(
    monkeypatch: pytest.MonkeyPatch, raw: str, problem: str
) -> None:
    monkeypatch.setenv("MAX_MESSAGE_CHARS", raw)

    with pytest.raises(InvalidConfigError, match=f"MAX_MESSAGE_CHARS must be .*{problem}"):
        limits_from_env()
