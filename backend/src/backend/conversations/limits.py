"""Input caps on what players send and on how much history reaches the LLM.

The numbers are configuration (`MAX_MESSAGE_CHARS`, `MAX_HISTORY_MESSAGES`). The
defaults are placeholders: Grill Decisions sets the real numbers once the free-tier
limits of the providers and Supabase are verified, which is still an open item.
"""

from dataclasses import dataclass

from backend.config import positive_int_env, require_positive

DEFAULT_MAX_MESSAGE_CHARS = 4000  # placeholder until the free-tier limits are verified
DEFAULT_MAX_HISTORY_MESSAGES = 20  # placeholder until the free-tier limits are verified
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
        require_positive("max_message_chars", self.max_message_chars)
        require_positive("max_history_messages", self.max_history_messages)

    def check_message(self, content: str) -> None:
        if len(content) > self.max_message_chars:
            raise MessageTooLongError(len(content), self.max_message_chars)


def limits_from_env() -> Limits:
    return Limits(
        max_message_chars=positive_int_env("MAX_MESSAGE_CHARS", DEFAULT_MAX_MESSAGE_CHARS),
        max_history_messages=positive_int_env("MAX_HISTORY_MESSAGES", DEFAULT_MAX_HISTORY_MESSAGES),
    )
