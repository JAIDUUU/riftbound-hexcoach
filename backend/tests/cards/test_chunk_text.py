from backend.cards.chunk_text import card_text_chunk
from backend.cards.collapse import Card


def test_a_card_with_a_supertype_gets_a_full_type_line(cards_by_name: dict[str, Card]) -> None:
    chunk = card_text_chunk(cards_by_name["Sona, Harmonious"])

    assert chunk.startswith("Sona, Harmonious (Champion Unit)\n")
    assert "At the end of your turn" in chunk


def test_a_card_without_a_supertype_uses_the_bare_type(cards_by_name: dict[str, Card]) -> None:
    chunk = card_text_chunk(cards_by_name["Annie, Dark Child"])

    assert chunk == "Annie, Dark Child (Legend)\nAt the end of your turn, ready 2 runes."
