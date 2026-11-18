import pytest
from langchain_core.tools import BaseTool

from backend.agent.tools import make_lookup_card
from backend.cards.collapse import Card
from tests.cards.memory_catalog import InMemoryCardCatalog


@pytest.fixture
def tool(cards_by_name: dict[str, Card]) -> BaseTool:
    return make_lookup_card(InMemoryCardCatalog(cards_by_name.values()))


def test_a_known_card_returns_its_name_type_line_and_cleaned_text(tool: BaseTool) -> None:
    result = tool.invoke({"name": "Sona, Harmonious"})

    assert result == (
        "Sona, Harmonious (Champion Unit)\n"
        "At the end of your turn, if I'm at a battlefield, ready up to 4 friendly runes."
    )


def test_lookup_matches_like_the_catalog_any_case_and_aliases(tool: BaseTool) -> None:
    assert "Deflect" in tool.invoke({"name": "  pouty poro  "})
    assert tool.invoke({"name": "Recruit (NX)"}).startswith("Recruit (Token Unit)")


def test_an_unknown_name_suggests_close_names_in_their_original_casing(tool: BaseTool) -> None:
    result = tool.invoke({"name": "sona harmonius"})

    assert "No card named 'sona harmonius'" in result
    assert "Sona, Harmonious" in result
    assert "call lookup_card again" in result


def test_an_alias_near_miss_is_suggested_too(tool: BaseTool) -> None:
    result = tool.invoke({"name": "Recruit (NZ)"})

    assert "No card named 'Recruit (NZ)'" in result
    assert "Recruit (NX)" in result  # the alias, which a retried lookup would match


def test_a_name_unlike_anything_says_so_and_forbids_invention(tool: BaseTool) -> None:
    result = tool.invoke({"name": "Xyzzyplugh"})

    assert "no similar name exists" in result
    assert "Do not invent" in result


def test_the_tool_presents_itself_to_the_model_as_lookup_card(tool: BaseTool) -> None:
    assert tool.name == "lookup_card"
    assert "card" in tool.description.lower()
    assert "memory" in tool.description.lower()
