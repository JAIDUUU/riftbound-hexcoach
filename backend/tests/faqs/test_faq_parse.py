from datetime import date

import pytest

from backend.faqs.parse import FaqParseError, parse_faq

HEADER = """\
  ---
  title: Riftbound Origins FAQ
  url: https://example.com/origins-faq/
  date: 10/16/2025
  set: OGN
  ---
"""


def test_q_style_questions_become_chunks_under_their_heading() -> None:
    document = parse_faq(
        HEADER
        + """
Intro paragraph that is not a question.

Scoring

Q: How do I score?
A detailed answer.

More answer after a blank line.

Q: What is the final point?
Another answer.
"""
    )

    assert document.title == "Riftbound Origins FAQ"
    assert document.url == "https://example.com/origins-faq/"
    assert document.date == date(2025, 10, 16)
    assert document.set_code == "OGN"
    questions = [chunk for chunk in document.chunks if chunk.is_question]
    assert [chunk.section for chunk in questions] == ["Scoring", "Scoring"]
    assert questions[0].text.startswith("Q: How do I score?\nA: A detailed answer.")
    assert "More answer after a blank line." in questions[0].text
    assert questions[1].text.startswith("Q: What is the final point?")


def test_bold_questions_and_relevant_rules_lines_are_kept_together() -> None:
    document = parse_faq(
        HEADER
        + """
**If I play Mobilize, do I still draw a card?**
No.

The channel event introduces a new game object.

_Relevant rules: 359.3.e.14.c._

**Second question?**
Yes.
"""
    )

    questions = [chunk for chunk in document.chunks if chunk.is_question]
    assert len(questions) == 2
    assert questions[0].text.startswith("Q: If I play Mobilize, do I still draw a card?\nA: No.")
    assert "_Relevant rules: 359.3.e.14.c._" in questions[0].text
    assert "Second question" not in questions[0].text


def test_essay_prose_is_grouped_into_paragraph_chunks_by_heading() -> None:
    long_paragraph = "This ruling explains a complicated interaction in detail. " * 30
    document = parse_faq(
        HEADER
        + f"""
Triggered Abilities

{long_paragraph}

{long_paragraph}

Control of Battlefields

A short closing ruling.
"""
    )

    prose = [chunk for chunk in document.chunks if not chunk.is_question]
    assert len(prose) == 3  # the two long paragraphs exceed one chunk's budget
    assert {chunk.section for chunk in prose[:2]} == {"Triggered Abilities"}
    assert prose[2].section == "Control of Battlefields"
    assert prose[2].text == "A short closing ruling."


def test_bare_question_paragraphs_become_qa_chunks() -> None:
    document = parse_faq(
        HEADER
        + """
What happens when you play Abandon on a spell played for its Flow cost?

It will be banished when it attempts to leave the chain.

A longer explanation paragraph about why that happens in some detail.

Relevant Rules: 359.3.f.1., 359.3.f.2.

What is the difference between the two uses of \u201cthis battlefield\u201d?

The first refers to the battlefield that she held.
"""
    )

    questions = [chunk for chunk in document.chunks if chunk.is_question]
    assert len(questions) == 2
    assert questions[0].text.startswith(
        "Q: What happens when you play Abandon on a spell played for its Flow cost?\n"
        "A: It will be banished when it attempts to leave the chain."
    )
    assert "Relevant Rules: 359.3.f.1., 359.3.f.2." in questions[0].text
    assert "difference" not in questions[0].text
    assert questions[1].text.endswith("The first refers to the battlefield that she held.")


def test_a_rhetorical_question_inside_a_marked_answer_does_not_split_it() -> None:
    document = parse_faq(
        HEADER
        + """
Q: Does Deflect stop this?
Yes.

But what happens if the opponent pays the cost?

Then the effect resolves normally.

Q: A second question?
Answer two.
"""
    )

    questions = [chunk for chunk in document.chunks if chunk.is_question]
    assert len(questions) == 2
    assert "what happens if the opponent pays the cost?" in questions[0].text
    assert "resolves normally" in questions[0].text


def test_a_heading_after_a_blank_line_ends_a_question_block() -> None:
    document = parse_faq(
        HEADER
        + """
Q: A question?
The answer.

Movement

Prose under the new heading, long enough not to look like a heading itself.
"""
    )

    question = next(chunk for chunk in document.chunks if chunk.is_question)
    assert "Movement" not in question.text
    prose = next(chunk for chunk in document.chunks if not chunk.is_question)
    assert prose.section == "Movement"


def test_markdown_wrapped_url_and_iso_date_are_accepted() -> None:
    document = parse_faq(
        """\
---
title: Radiance FAQ
url: [post](https://example.com/radiance/)
date: 2026-10-26
set: RAD
---
Q: One question?
Answer.
"""
    )

    assert document.url == "https://example.com/radiance/"
    assert document.date == date(2026, 10, 26)


def test_placeholder_title_and_set_are_fatal_and_reported_together() -> None:
    with pytest.raises(FaqParseError) as caught:
        parse_faq(
            """\
---
title: <post title>
url: https://example.com/
date: not-a-date
set: <set code>
---
Q: Q?
A.
"""
        )

    message = str(caught.value)
    assert "title is missing or a placeholder" in message
    assert "set is missing or a placeholder" in message
    assert "date is missing" in message


def test_a_placeholder_url_is_only_a_warning() -> None:
    document = parse_faq(
        """\
---
title: Spiritforged FAQ
url: <original post URL>
date: 1/13/2026
set: SFD
---
Q: Q?
A.
"""
    )

    assert document.url is None
    assert any("url" in warning for warning in document.warnings)


def test_a_file_without_frontmatter_is_rejected() -> None:
    with pytest.raises(FaqParseError, match="frontmatter"):
        parse_faq("Q: Just a question?\nAnswer.")
