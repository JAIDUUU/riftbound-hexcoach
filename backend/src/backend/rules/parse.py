"""Parse extracted Core Rules text into one chunk per rule number.

The extracted text (see `extract.py`) puts every rule id at column zero with its text
beside it; continuation lines and examples are indented. Pages break mid-sentence with a
form feed and carry no headers or footers, so a page break is just an empty line.

A rule whose text is a bare title (no sentence-ending punctuation) is a heading; headings
name the section that following rules belong to. Headings are kept as chunks themselves,
since they carry citable rule ids (for example `001. Golden Rule`).
"""

import re
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

_RULE_LINE = re.compile(r"^(\d{3}(?:\.[0-9a-z]+)*)\. +(\S.*)$")
_LAST_UPDATED = re.compile(r"Last Updated:\s*(\d{4}-\d{2}-\d{2})")
_SPACES = re.compile(r"[ \t]+")
_SENTENCE_END = (".", ":", "?", "!")
_CLOSING_QUOTES = "\"'\u201d\u2019"
_HEADING_MAX_WORDS = 8


@dataclass(frozen=True, slots=True)
class RuleChunk:
    """One rule of the Core Rules document, with its place in the hierarchy."""

    rule_id: str
    text: str
    section: str | None
    parent_id: str | None
    is_heading: bool


def rules_date(text: str) -> date:
    """The document's own "Last Updated" date, used as the rules version."""
    match = _LAST_UPDATED.search(text)
    if match is None:
        raise ValueError('The rules text has no "Last Updated: YYYY-MM-DD" header.')
    return date.fromisoformat(match.group(1))


def _is_heading(rule_id: str, text: str) -> bool:
    """A top-level rule whose text is a bare title, like `001. Golden Rule`."""
    bare = text.rstrip(_CLOSING_QUOTES)
    return (
        "." not in rule_id
        and "\n" not in text
        and len(text.split()) <= _HEADING_MAX_WORDS
        and not bare.endswith(_SENTENCE_END)
    )


def _assemble(paragraphs: list[list[str]]) -> str:
    return "\n".join(" ".join(lines) for lines in paragraphs if lines)


def parse_rules(text: str) -> list[RuleChunk]:
    """One chunk per rule id, in document order, with section and parent metadata."""
    collected: list[tuple[str, str]] = []
    paragraphs: list[list[str]] = []
    for raw_line in text.replace("\f", "\n").splitlines():
        line = _SPACES.sub(" ", raw_line).strip()
        started = _RULE_LINE.match(raw_line)
        if started:
            if collected and paragraphs:
                collected[-1] = (collected[-1][0], _assemble(paragraphs))
            rule_id, first_text = started.group(1), _SPACES.sub(" ", started.group(2)).strip()
            collected.append((rule_id, ""))
            paragraphs = [[first_text]]
        elif line and collected:
            # Example blocks start their own paragraph; wrapped lines continue the last one.
            if line.startswith("Example:"):
                paragraphs.append([line])
            else:
                paragraphs[-1].append(line)
    if collected and paragraphs:
        collected[-1] = (collected[-1][0], _assemble(paragraphs))

    chunks: list[RuleChunk] = []
    section: str | None = None
    for rule_id, rule_text in collected:
        heading = _is_heading(rule_id, rule_text)
        parent_id = rule_id.rsplit(".", 1)[0] if "." in rule_id else None
        chunks.append(RuleChunk(rule_id, rule_text, section, parent_id, heading))
        if heading:
            section = rule_text
    return chunks


def _successors(rule_id: str) -> set[str]:
    """Every rule id that may legally follow `rule_id` in document order."""
    allowed = {f"{rule_id}.1", f"{rule_id}.a"}  # first child
    components = rule_id.split(".")
    for depth in range(len(components), 0, -1):  # next sibling of the rule or any ancestor
        *prefix, last = components[:depth]
        bumped = str(int(last) + 1).zfill(len(last)) if last.isdigit() else chr(ord(last) + 1)
        allowed.add(".".join([*prefix, bumped]))
    return allowed


def sequence_problems(chunks: list[RuleChunk]) -> tuple[list[str], list[str]]:
    """Check that rule ids read like a correctly extracted document.

    Returns (problems, gaps). A problem is an id that cannot follow its predecessor and
    means the extraction mangled the numbering. A gap is a skip between top-level rules,
    which the document does on purpose between rule groups (002 -> 050) but is still
    worth a look after a re-ingest.
    """
    problems: list[str] = []
    gaps: list[str] = []
    for previous, current in pairwise(chunks):
        if current.rule_id in _successors(previous.rule_id):
            continue
        previous_top, current_top = (
            int(chunk.rule_id.split(".")[0]) for chunk in (previous, current)
        )
        if "." not in current.rule_id and current_top > previous_top:
            gaps.append(f"{previous.rule_id} -> {current.rule_id}")
        else:
            problems.append(f"{previous.rule_id} -> {current.rule_id}")
    return problems, gaps
