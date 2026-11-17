"""Input caps on what players send and on how much history reaches the LLM.

The numbers are configuration (`MAX_MESSAGE_CHARS`, `MAX_HISTORY_MESSAGES`); the
defaults keep a free-tier provider's context and quota comfortable.
"""

from dataclasses import dataclass

from backend.config import MissingConfigError, optional_env

DEFAULT_MAX_MESSAGE_CHARS = 4000
DEFAULT_MAX_HISTORY_MESSAGES = 20
MAX_TITLE_CHARS = 200


class MessageTooLongError(ValueError):
    """A message is over the configured length cap."""

    def __init__(self, length: int, cap: int) -> None:
        self.length = length
        self.cap = cap
        super().__init__(f"Message is {length} characters; the limit is {cap}.")


@dataclass(frozen=True, slots=True)
class Limits:
    max_message_chars: int = DEFAULT_MAX_MESSAGE_CHARS
    max_history_messages: int = DEFAULT_MAX_HISTORY_MESSAGES

    def __post_init__(self) -> None:
        if self.max_message_chars < 1 or self.max_history_messages < 1:
            raise ValueError("Input caps must be positive.")

    def check_message(self, content: str) -> None:
        if len(content) > self.max_message_chars:
            raise MessageTooLongError(len(content), self.max_message_chars)


def _positive_int(name: str, default: int) -> int:
    raw = optional_env(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise MissingConfigError(f"{name} must be a whole number, got {raw!r}.") from None
    if value < 1:
        raise MissingConfigError(f"{name} must be positive, got {value}.")
    return value


def limits_from_env() -> Limits:
    return Limits(
        max_message_chars=_positive_int("MAX_MESSAGE_CHARS", DEFAULT_MAX_MESSAGE_CHARS),
        max_history_messages=_positive_int("MAX_HISTORY_MESSAGES", DEFAULT_MAX_HISTORY_MESSAGES),
    )
