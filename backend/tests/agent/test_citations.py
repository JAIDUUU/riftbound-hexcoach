from datetime import date

from backend.agent.citations import cited_evidence, cited_rules
from backend.retrieval.repository import SearchHit, SourceType


def hit(source_type: SourceType, rule_id: str | None = None, title: str | None = None) -> SearchHit:
    return SearchHit(
        chunk_id=hash((source_type, rule_id, title)) % 1000,
        source_type=source_type,
        rule_id=rule_id,
        section=None,
        text="...",
        source_version="v",
        source_date=date(2026, 10, 9),
        title=title,
        source_url=None,
    )


RULE_472 = hit("rules", rule_id="472")
RULE_466_2_A = hit("rules", rule_id="466.2.a")
RULE_466 = hit("rules", rule_id="466")
ORIGINS_FAQ = hit("faq", title="Riftbound Origins FAQ")
ZHONYAS = hit("card_text", title="Zhonya's Hourglass")


def test_only_the_evidence_the_answer_cites_is_kept_most_authoritative_first() -> None:
    answer = (
        "No. Rule 472 allows one score per battlefield per turn, and the Riftbound Origins"
        " FAQ confirms replaying the unit doesn't reset that."
    )

    cited = cited_evidence(answer, [RULE_472, RULE_466, ORIGINS_FAQ, ZHONYAS])

    assert cited == [ORIGINS_FAQ, RULE_472]


def test_rules_match_by_exact_id_not_by_prefix() -> None:
    answer = "Damage is assigned per 466.2.a."

    assert cited_evidence(answer, [RULE_466, RULE_466_2_A]) == [RULE_466_2_A]


def test_sources_are_named_case_insensitively() -> None:
    answer = "zhonya's hourglass only grants Deflect."

    assert cited_evidence(answer, [ZHONYAS]) == [ZHONYAS]


def test_an_answer_that_cites_nothing_has_no_citations() -> None:
    assert cited_evidence("Which Diana do you mean?", [RULE_472, ORIGINS_FAQ]) == []


def test_cited_rules_finds_dotted_ids_and_strips_sentence_dots() -> None:
    answer = (
        "No - rule 472 says once per turn. Per 466.2.a. and rule 467.2.c.3, "
        "the trigger resolves first."
    )

    assert cited_rules(answer) == {"472", "466.2.a", "467.2.c.3"}


def test_years_dates_and_short_numbers_are_not_citations() -> None:
    answer = "As of the 2026-10-09 rules, with 4 might and 12 damage, see rule 472."

    assert cited_rules(answer) == {"472"}
