from dataclasses import replace

import pytest

from backend.cards.collapse import Card
from backend.cards.images import preview_image_url


# Expected values are the `images.normal` URLs Rifthunt's card API returned for these
# printings on 2026-11-17, without the `?v=` version (see preview_image_url).
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (
            "Blazing Scorcher",
            "https://images.rifthunt.com/cards/normal/front/ogn/001/blazing-scorcher.webp",
        ),
        ("Recruit", "https://images.rifthunt.com/cards/normal/front/ven/t04/recruit.webp"),
        (
            "Sona, Harmonious",
            "https://images.rifthunt.com/cards/normal/front/ven/sp2/sona-harmonious.webp",
        ),
        ("Bird // Bomb", "https://images.rifthunt.com/cards/normal/front/rad/t01/bird-bomb.webp"),
    ],
)
def test_the_preview_is_the_normal_size_image_of_the_representative_printing(
    cards_by_name: dict[str, Card], name: str, expected: str
) -> None:
    assert preview_image_url(cards_by_name[name]) == expected


@pytest.mark.parametrize(
    ("name", "set_code", "representative_id", "expected"),
    [
        (
            "B.F. Sword",
            "SFD",
            "sfd-161-221",
            "https://images.rifthunt.com/cards/normal/front/sfd/161/b-f-sword.webp",
        ),
        (
            "Kai'Sa, Daughter of the Void",
            "OGN",
            "ogn-247-298",
            "https://images.rifthunt.com/cards/normal/front/ogn/247/kaisa-daughter-of-the-void.webp",
        ),
        (
            "Command: Attack",
            "RAD",
            "rad-033-167",
            "https://images.rifthunt.com/cards/normal/front/rad/033/command-attack.webp",
        ),
    ],
)
def test_names_with_dots_apostrophes_and_colons_are_slugged_like_rifthunt(
    cards_by_name: dict[str, Card], name: str, set_code: str, representative_id: str, expected: str
) -> None:
    card = replace(
        cards_by_name["Pouty Poro"],
        oracle_name=name,
        set_code=set_code,
        representative_id=representative_id,
    )

    assert preview_image_url(card) == expected
