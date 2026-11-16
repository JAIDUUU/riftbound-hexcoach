"""Parse the official post-set FAQ Markdown files in data/FAQs into chunks.

Each file starts with a small frontmatter header (title, url, date, set). The bodies vary
by era, so three shapes are handled:

- "Q:" question lines with the answer following (Origins, Spiritforged)
- bold "**question**" lines with the answer following (Radiance)
- essay-style rulings under bare topic headings (Unleashed, Vendetta), which become
  paragraph chunks grouped under their heading

A file with an unusable header (missing or still a "<placeholder>") is reported rather
than guessed at; a missing url alone is a warning because it only affects provenance.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

_PLACEHOLDER = re.compile(r"<[^>]*>")
_MARKDOWN_LINK = re.compile(r"\]\((?P<target>[^)]+)\)")
_BOLD_QUESTION = re.compile(r"^\*\*(?P<question>.+)\*\*$")
_HEADING_MAX_WORDS = 8
# Group consecutive prose paragraphs into chunks of roughly this many characters, so
# essay-style rulings neither explode into one-line chunks nor exceed what the
# embedding model can usefully encode (bge truncates past 512 tokens).
_PROSE_CHUNK_TARGET = 1200


@dataclass(frozen=True, slots=True)
class FaqChunk:
    text: str
    section: str | None
    is_question: bool


@dataclass(frozen=True, slots=True)
class FaqDocument:
    title: str
    url: str | None
    date: date
    set_code: str
    chunks: tuple[FaqChunk, ...]
    warnings: tuple[str, ...]


class FaqParseError(ValueError):
    """The file cannot be ingested; the message lists every problem found."""


def _parse_date(raw: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_header(lines: list[str]) -> tuple[dict[str, str], int]:
    """The frontmatter fields and the index of the first body line."""
    stripped = [line.strip() for line in lines]
    try:
        start = stripped.index("---")
        end = stripped.index("---", start + 1)
    except ValueError as error:
        raise FaqParseError("no frontmatter header (--- ... ---) found") from error
    fields: dict[str, str] = {}
    for line in stripped[start + 1 : end]:
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip().lower()] = value.strip()
    return fields, end + 1


def _header_values(fields: dict[str, str], problems: list[str], warnings: list[str]):
    def usable(name: str) -> str | None:
        value = fields.get(name, "")
        return None if not value or _PLACEHOLDER.search(value) else value

    title = usable("title")
    if title is None:
        problems.append("title is missing or a placeholder")
    set_code = usable("set")
    if set_code is None:
        problems.append("set is missing or a placeholder")
    raw_date = usable("date")
    parsed_date = _parse_date(raw_date) if raw_date else None
    if parsed_date is None:
        problems.append("date is missing, a placeholder, or not M/D/YYYY or YYYY-MM-DD")
    url = usable("url")
    if url is not None and (match := _MARKDOWN_LINK.search(url)):
        url = match.group("target")
    if url is None:
        warnings.append("url is missing or a placeholder; chunks will carry no source url")
    return title, url, parsed_date, set_code


def _is_heading(line: str) -> bool:
    bare = line.strip().strip("*_").strip("\u201c\u201d\"'")  # markdown emphasis, quotes
    if not bare or len(bare.split()) > _HEADING_MAX_WORDS:
        return False
    return bare[-1] not in ".?!:,;"


def _flush_prose(paragraphs: list[str], section: str | None, chunks: list[FaqChunk]) -> None:
    group: list[str] = []
    size = 0
    for paragraph in paragraphs:
        if group and size + len(paragraph) > _PROSE_CHUNK_TARGET:
            chunks.append(FaqChunk("\n\n".join(group), section, is_question=False))
            group, size = [], 0
        group.append(paragraph)
        size += len(paragraph)
    if group:
        chunks.append(FaqChunk("\n\n".join(group), section, is_question=False))
    paragraphs.clear()


def _question_of(line: str) -> str | None:
    if line.startswith("Q:"):
        return line[2:].strip()
    if match := _BOLD_QUESTION.match(line):
        return match.group("question").strip()
    return None


def _parse_body(lines: list[str]) -> list[FaqChunk]:
    chunks: list[FaqChunk] = []
    section: str | None = None
    prose: list[str] = []  # completed paragraphs outside any Q/A
    paragraph: list[str] = []  # the paragraph currently being accumulated
    question: str | None = None
    answer: list[str] = []

    def end_paragraph() -> None:
        if paragraph:
            prose.append(" ".join(paragraph))
            paragraph.clear()

    def end_question() -> None:
        nonlocal question
        if question is not None:
            body = "\n".join(part for part in answer if part).strip()
            chunks.append(FaqChunk(f"Q: {question}\nA: {body}", section, is_question=True))
            question = None
            answer.clear()

    for raw_line in lines:
        line = raw_line.strip()
        if new_question := _question_of(line):
            end_question()
            end_paragraph()
            question = new_question
            continue
        if question is not None:
            # A heading ends the Q/A block, but only once there is answer text and the
            # previous line was blank; mid-answer fragments must not be mistaken for one.
            after_blank = bool(answer) and not answer[-1]
            if line and _is_heading(line) and any(answer) and after_blank:
                end_question()
                section = line
            else:
                answer.append(line)
            continue
        if not line:
            end_paragraph()
        elif _is_heading(line):
            end_paragraph()
            _flush_prose(prose, section, chunks)
            section = line
        else:
            paragraph.append(line)
    end_question()
    end_paragraph()
    _flush_prose(prose, section, chunks)
    return chunks


def parse_faq(text: str) -> FaqDocument:
    lines = text.splitlines()
    problems: list[str] = []
    warnings: list[str] = []
    fields, body_start = _parse_header(lines)
    title, url, parsed_date, set_code = _header_values(fields, problems, warnings)
    chunks = _parse_body(lines[body_start:])
    if not chunks:
        problems.append("no chunks found in the body")
    if problems:
        raise FaqParseError("; ".join(problems))
    assert title is not None and parsed_date is not None and set_code is not None
    return FaqDocument(
        title=title,
        url=url,
        date=parsed_date,
        set_code=set_code,
        chunks=tuple(chunks),
        warnings=tuple(warnings),
    )


def load_faq(path: Path) -> FaqDocument:
    try:
        return parse_faq(path.read_text(encoding="utf-8"))
    except FaqParseError as error:
        raise FaqParseError(f"{path.name}: {error}") from error
