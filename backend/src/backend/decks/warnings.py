"""Import validation warnings: every problem found in a Decklist, none of which block saving.

One type for parse problems, unknown cards and structural checks alike, so the Decks page
renders a single list and keys its display off `kind`.
"""

from dataclasses import dataclass
from typing import Literal

WarningKind = Literal[
    "malformed_line",
    "outside_section",
    "unknown_section",
    "unknown_card",
    "section_size",
    "copy_limit",
]


@dataclass(frozen=True, slots=True)
class DeckWarning:
    kind: WarningKind
    message: str
    line: int | None = None  # 1-based source line, when the warning is about one line
