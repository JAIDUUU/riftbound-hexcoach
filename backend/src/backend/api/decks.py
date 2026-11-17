"""Decks (issue #16): saved Decklists with their import validation, and a preview that
validates without saving. Someone else's deck is a plain 404."""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from backend.api.dependencies import Decks, User
from backend.decks.importing import DeckImport
from backend.decks.parse import SECTIONS, Section
from backend.decks.store import MAX_DECK_NAME_CHARS, Deck
from backend.decks.warnings import WarningKind


class DecklistIn(BaseModel):
    decklist: str


class DeckIn(DecklistIn):
    name: str = Field(min_length=1, max_length=MAX_DECK_NAME_CHARS)


class CardRefOut(BaseModel):
    oracle_id: str
    oracle_name: str


class DeckLineOut(BaseModel):
    line: int
    count: int
    name: str  # as written
    card: CardRefOut | None  # None: no card has that name; see suggestions
    suggestions: list[str]


class SectionOut(BaseModel):
    section: Section
    cards: list[DeckLineOut]


class DeckWarningOut(BaseModel):
    kind: WarningKind
    message: str
    line: int | None


class DeckImportOut(BaseModel):
    sections: list[SectionOut]  # every section, in decklist order, empty ones included
    warnings: list[DeckWarningOut]

    @classmethod
    def of(cls, imported: DeckImport) -> "DeckImportOut":
        def lines_in(section: Section) -> list[DeckLineOut]:
            return [
                DeckLineOut(
                    line=resolved.line.number,
                    count=resolved.line.count,
                    name=resolved.line.name,
                    card=CardRefOut(
                        oracle_id=resolved.card.oracle_id, oracle_name=resolved.card.oracle_name
                    )
                    if resolved.card
                    else None,
                    suggestions=list(resolved.suggestions),
                )
                for resolved in imported.lines
                if resolved.line.section == section
            ]

        return cls(
            sections=[SectionOut(section=s, cards=lines_in(s)) for s in SECTIONS],
            warnings=[
                DeckWarningOut(kind=w.kind, message=w.message, line=w.line)
                for w in imported.warnings
            ],
        )


class DeckSummaryOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, deck: Deck) -> "DeckSummaryOut":
        return cls(
            id=deck.id, name=deck.name, created_at=deck.created_at, updated_at=deck.updated_at
        )


class DeckOut(DeckSummaryOut):
    decklist: str
    validation: DeckImportOut

    @classmethod
    def of_import(cls, deck: Deck, imported: DeckImport) -> "DeckOut":
        return cls(
            **DeckSummaryOut.of(deck).model_dump(),
            decklist=deck.decklist,
            validation=DeckImportOut.of(imported),
        )


def _deck_not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Deck not found")


router = APIRouter(prefix="/decks")


@router.post("/preview")
def preview_deck(body: DecklistIn, user: User, access: Decks) -> DeckImportOut:
    """Import validation without saving, for the Decks page's preview."""
    return DeckImportOut.of(access.import_new(body.decklist))


@router.post("", status_code=status.HTTP_201_CREATED)
def create_deck(body: DeckIn, user: User, access: Decks) -> DeckOut:
    imported = access.import_new(body.decklist)
    return DeckOut.of_import(access.decks.create(user.id, body.name, body.decklist), imported)


@router.get("")
def list_decks(user: User, access: Decks) -> list[DeckSummaryOut]:
    return [DeckSummaryOut.of(deck) for deck in access.decks.list_for_user(user.id)]


@router.get("/{deck_id}")
def read_deck(deck_id: uuid.UUID, user: User, access: Decks) -> DeckOut:
    deck = access.decks.get(user.id, deck_id)
    if deck is None:
        raise _deck_not_found()
    return DeckOut.of_import(deck, access.import_saved(deck))


@router.put("/{deck_id}")
def update_deck(deck_id: uuid.UUID, body: DeckIn, user: User, access: Decks) -> DeckOut:
    imported = access.import_new(body.decklist)
    deck = access.decks.update(user.id, deck_id, body.name, body.decklist)
    if deck is None:
        raise _deck_not_found()
    return DeckOut.of_import(deck, imported)


@router.delete("/{deck_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deck(deck_id: uuid.UUID, user: User, access: Decks) -> Response:
    if not access.decks.delete(user.id, deck_id):
        raise _deck_not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
