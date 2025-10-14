"""Utilities for loading flashcard content from Anki ``.apkg`` packages."""
from __future__ import annotations

import json
import re
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from zipfile import ZipFile

_FIELD_SEPARATOR = "\x1f"
_CLOZE_PATTERN = re.compile(
    r"{{c(?P<index>\d+)::(?P<text>.*?)(::(?P<hint>.*?))?}}",
    re.DOTALL | re.IGNORECASE,
)


class DeckLoadError(RuntimeError):
    """Raised when the Anki package cannot be processed."""


@dataclass(frozen=True)
class Card:
    """Representation of a single flashcard."""

    card_id: int
    note_id: int
    deck_id: int
    deck_name: str
    template_ordinal: int
    question: str
    answer: str
    extra_fields: List[str] = field(default_factory=list)


@dataclass
class Deck:
    """Grouping of cards that belong to the same deck."""

    deck_id: int
    name: str
    cards: List[Card] = field(default_factory=list)


@dataclass
class DeckCollection:
    """Container for all decks contained in an Anki collection."""

    decks: Dict[int, Deck]

    @property
    def total_cards(self) -> int:
        return sum(len(deck.cards) for deck in self.decks.values())


def load_collection(package_path: Path) -> DeckCollection:
    """Load an Anki package and return the parsed cards grouped by deck."""

    if not package_path.exists():
        raise DeckLoadError(f"Package not found: {package_path}")

    with tempfile.TemporaryDirectory(prefix="anki_viewer_") as tmp_dir:
        _extract_package(package_path, tmp_dir)
        collection_path = _find_collection_file(Path(tmp_dir))
        return _load_from_sqlite(collection_path)


def _extract_package(package_path: Path, destination: str) -> None:
    try:
        with ZipFile(package_path) as archive:
            archive.extractall(destination)
    except Exception as exc:  # pragma: no cover - defensive programming
        raise DeckLoadError(f"Failed to unpack package: {exc}") from exc


def _find_collection_file(extracted_path: Path) -> Path:
    for candidate in ("collection.anki21", "collection.anki2"):
        potential = extracted_path / candidate
        if potential.exists():
            return potential
    raise DeckLoadError("collection.anki21 not found in package")


def _load_from_sqlite(collection_path: Path) -> DeckCollection:
    try:
        conn = sqlite3.connect(str(collection_path))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:  # pragma: no cover - defensive programming
        raise DeckLoadError(f"Failed to open SQLite database: {exc}") from exc

    with conn:
        deck_names = _read_deck_names(conn)
        cards = _read_cards(conn, deck_names)

    decks: Dict[int, Deck] = {}
    for card in cards:
        decks.setdefault(card.deck_id, Deck(deck_id=card.deck_id, name=card.deck_name)).cards.append(card)

    for deck in decks.values():
        deck.cards.sort(key=lambda c: (c.template_ordinal, c.card_id))

    return DeckCollection(decks=decks)


def _read_deck_names(conn: sqlite3.Connection) -> Dict[int, str]:
    cursor = conn.execute("SELECT decks FROM col LIMIT 1")
    row = cursor.fetchone()
    if row is None:
        raise DeckLoadError("The collection database is missing metadata")

    try:
        decks_json = json.loads(row["decks"])
    except (json.JSONDecodeError, KeyError) as exc:
        raise DeckLoadError("Could not parse deck metadata") from exc

    return {int(deck_id): data.get("name", str(deck_id)) for deck_id, data in decks_json.items()}


def _read_cards(conn: sqlite3.Connection, deck_names: Dict[int, str]) -> Iterable[Card]:
    query = """
        SELECT
            cards.id AS card_id,
            cards.nid AS note_id,
            cards.did AS deck_id,
            cards.ord AS template_ordinal,
            notes.flds AS note_fields
        FROM cards
        JOIN notes ON notes.id = cards.nid
        ORDER BY cards.did, cards.due, cards.id
    """
    for row in conn.execute(query):
        fields = row["note_fields"].split(_FIELD_SEPARATOR)
        question, answer, extra = _format_card_fields(fields)
        deck_id = int(row["deck_id"])
        deck_name = deck_names.get(deck_id, str(deck_id))
        yield Card(
            card_id=int(row["card_id"]),
            note_id=int(row["note_id"]),
            deck_id=deck_id,
            deck_name=deck_name,
            template_ordinal=int(row["template_ordinal"]),
            question=question,
            answer=answer,
            extra_fields=extra,
        )


def _format_card_fields(fields: List[str]) -> Tuple[str, str, List[str]]:
    if not fields:
        return "", "", []

    base_question = fields[0]
    base_answer = fields[1] if len(fields) > 1 else ""
    extras = fields[2:] if len(fields) > 2 else []

    question_is_cloze = _CLOZE_PATTERN.search(base_question) is not None

    if question_is_cloze:
        question_html = _render_cloze(base_question, reveal=False)
        answer_sections = [_render_cloze(base_question, reveal=True)]
        if base_answer:
            answer_sections.append(
                f"<div class=\"cloze-extra\">{_render_field(base_answer, reveal_cloze=True)}</div>"
            )
        answer_html = "".join(answer_sections)
    else:
        question_html = _render_field(base_question, reveal_cloze=False)
        answer_html = _render_field(base_answer, reveal_cloze=True)

    extras_html = [_render_field(value, reveal_cloze=True) for value in extras]
    return question_html, answer_html, extras_html


def _render_cloze(text: str, *, reveal: bool) -> str:
    def replace(match: re.Match) -> str:
        index = match.group("index")
        content = match.group("text") or ""
        hint = match.group("hint")

        hint_html = f" <span class=\"cloze-hint\">({hint})</span>" if hint else ""

        if reveal:
            return (
                f"<span class=\"cloze cloze-revealed\" data-cloze=\"{index}\">"
                f"<span class=\"cloze-index\">{index}</span> {content}{hint_html}"
                "</span>"
            )

        return (
            f"<span class=\"cloze cloze-hidden\" data-cloze=\"{index}\">"
            f"<span class=\"cloze-placeholder\">…</span>{hint_html}"
            "</span>"
        )

    rendered = _CLOZE_PATTERN.sub(replace, text)
    return _normalize_field_html(rendered)


def _render_field(text: str, *, reveal_cloze: bool) -> str:
    if not text:
        return ""

    if _CLOZE_PATTERN.search(text):
        return _render_cloze(text, reveal=reveal_cloze)

    return _normalize_field_html(text)


def _normalize_field_html(text: str) -> str:
    if not text:
        return ""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    return cleaned.replace("\n", "<br>\n")


__all__ = [
    "Card",
    "Deck",
    "DeckCollection",
    "DeckLoadError",
    "load_collection",
]
