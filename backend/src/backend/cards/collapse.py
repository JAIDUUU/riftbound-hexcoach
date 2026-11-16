"""Collapse Rifthunt printings into one Card per oracle id."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from backend.cards.rifthunt import RifthuntPrinting, RifthuntSnapshot
from backend.cards.text import clean_card_text
from backend.cards.vocabulary import CardType, Domain, Rarity, Supertype

# Rifthunt marks third-party printings only through the prefix of its legacy `id` field.
# This is the one place that field is read; identity everywhere else is `riftboundId`.
_THIRD_PARTY_ID_PREFIXES = ("tcg:", "dotgg:")


@dataclass(frozen=True, slots=True)
class Card:
    """A distinct Riftbound card, identified by its oracle id.

    Text and stats come from one representative printing; see `collapse_printings`.
    """

    oracle_id: str
    oracle_name: str
    aliases: tuple[str, ...]
    card_type: CardType
    supertype: Supertype | None
    domains: tuple[Domain, ...]
    energy: int | None
    might: int | None
    power: int | None
    rarity: Rarity
    tags: tuple[str, ...]
    raw_text: str
    cleaned_text: str
    representative_id: str
    set_code: str
    image_path: str | None
    image_url: str
    printing_count: int
    snapshot_fetched: datetime


def _is_plain(printing: RifthuntPrinting) -> bool:
    """A plain printing is not alternate art, signature or overnumbered, and has no name suffix."""
    return not (
        printing["alt"]
        or printing["sig"]
        or printing["over"]
        or printing["name"] != printing["cleanName"]
    )


def _is_official(printing: RifthuntPrinting) -> bool:
    return not printing["id"].startswith(_THIRD_PARTY_ID_PREFIXES)


def _stable_order(printing: RifthuntPrinting) -> tuple[str, str]:
    return printing["riftboundId"], printing["printing_id"]


def _representative(
    printings: Iterable[RifthuntPrinting], released: Mapping[str, str]
) -> RifthuntPrinting:
    """Pick the printing whose text and stats define the card.

    Preference: plain over variant, official id over third-party id, then the latest set
    release (newest wording). Ties go to the lowest riftboundId so the result is deterministic.
    """
    ordered = sorted(printings, key=_stable_order)
    return max(
        ordered,
        key=lambda printing: (
            _is_plain(printing),
            _is_official(printing),
            released.get(printing["set"], ""),
        ),
    )


def _card_from_group(
    printings: list[RifthuntPrinting], released: Mapping[str, str], fetched: datetime
) -> Card:
    chosen = _representative(printings, released)
    oracle_name = chosen["cleanName"]
    raw_text = chosen["text"] or ""
    other_names = {printing["cleanName"] for printing in printings} - {oracle_name}
    return Card(
        oracle_id=chosen["oracle_id"],
        oracle_name=oracle_name,
        aliases=tuple(sorted(other_names)),
        card_type=chosen["type"],
        supertype=chosen["supertype"],
        domains=tuple(chosen["domains"]),
        energy=chosen["energy"],
        might=chosen["might"],
        power=chosen["power"],
        rarity=chosen["rarity"],
        tags=tuple(chosen["tags"]),
        raw_text=raw_text,
        cleaned_text=clean_card_text(raw_text),
        representative_id=chosen["riftboundId"],
        set_code=chosen["set"],
        image_path=chosen["img"],
        image_url=chosen["imgUrl"],
        printing_count=len(printings),
        snapshot_fetched=fetched,
    )


def collapse_printings(snapshot: RifthuntSnapshot) -> list[Card]:
    """Turn a Rifthunt bulk snapshot into one Card per oracle id, sorted by oracle name."""
    released = {entry["id"]: entry["released"] for entry in snapshot["sets"]}
    fetched = datetime.fromisoformat(snapshot["fetched"])
    by_oracle_id: dict[str, list[RifthuntPrinting]] = {}
    for printing in snapshot["cards"]:
        by_oracle_id.setdefault(printing["oracle_id"], []).append(printing)
    cards = (_card_from_group(group, released, fetched) for group in by_oracle_id.values())
    return sorted(cards, key=lambda card: card.oracle_name)
