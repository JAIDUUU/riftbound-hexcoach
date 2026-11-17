from backend.agent.tools import make_lookup_card

_CARDS = {
    "diana, lunari": "Diana, Lunari (Legend Unit)\nWhen I conquer: ready me.",
    "zhonya's hourglass": "Zhonya's Hourglass (Gear)\nExhaust: a unit gains Deflect.",
}

# The suggestion pool carries every name a lookup would match: oracle names and aliases
# (all_card_names in cards/repository.py), so alias near-misses also get suggestions.
_NAMES = ["Diana, Lunari", "Zhonya's Hourglass", "Imperial Decree", "Zhonyas"]


def _find(name: str) -> str | None:
    return _CARDS.get(name.strip().lower())


def _tool():
    return make_lookup_card(_find, lambda: _NAMES)


def test_a_known_card_returns_its_formatted_text() -> None:
    result = _tool().invoke({"name": "Diana, Lunari"})

    assert result == "Diana, Lunari (Legend Unit)\nWhen I conquer: ready me."


def test_lookup_is_as_forgiving_as_the_injected_store() -> None:
    # Case handling lives in the store (the DB matches case-insensitively); the tool
    # passes the name through untouched.
    result = _tool().invoke({"name": "  zhonya's hourglass  "})

    assert "Deflect" in result


def test_an_unknown_name_suggests_close_names_in_their_original_casing() -> None:
    result = _tool().invoke({"name": "diana lunary"})

    assert "No card named 'diana lunary'" in result
    assert "Diana, Lunari" in result
    assert "call lookup_card again" in result


def test_an_alias_near_miss_is_suggested_too() -> None:
    result = _tool().invoke({"name": "zhonias"})

    assert "No card named 'zhonias'" in result
    assert "Zhonyas" in result  # the alias, which a retried lookup would match


def test_a_name_unlike_anything_says_so_and_forbids_invention() -> None:
    result = _tool().invoke({"name": "Xyzzyplugh"})

    assert "no similar name exists" in result
    assert "Do not invent" in result


def test_the_tool_presents_itself_to_the_model_as_lookup_card() -> None:
    tool = _tool()

    assert tool.name == "lookup_card"
    assert "card" in tool.description.lower()
    assert "memory" in tool.description.lower()
