"""Utilities for loading flashcard content from Anki ``.apkg`` packages."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List
from zipfile import ZipFile

_FIELD_SEPARATOR = "\x1f"


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

    # Extract the package into a temporary directory. To avoid locking the
    # extracted SQLite file during cleanup on Windows, copy the collection
    # database out to a separate temporary file and open that copy instead.
    tmp_dir = tempfile.mkdtemp(prefix="anki_viewer_")
    try:
        _extract_package(package_path, tmp_dir)
        collection_path = _find_collection_file(Path(tmp_dir))

        # Copy the collection DB to a separate temp file outside the
        # extracted directory so we can safely close and remove the
        # extracted directory without the file being locked by SQLite.
        copy_path = Path(tempfile.mktemp(prefix="anki_viewer_collection_"))
        try:
            import shutil

            shutil.copy2(collection_path, copy_path)
            collection = _load_from_sqlite(copy_path)
        finally:
            try:
                Path(copy_path).unlink()
            except Exception:
                # Best effort cleanup of the copied DB; ignore errors.
                pass

        return collection
    finally:
        # Best-effort cleanup of the extracted package directory. On
        # Windows it's possible for other processes (indexers, AV) to hold
        # short-lived locks; ignore cleanup errors here.
        try:
            import shutil

            shutil.rmtree(tmp_dir)
        except Exception:
            pass


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
        # Use the connection as a context manager so it is closed when we're
        # done reading. Also convert the cards generator to a list while the
        # connection is still open to avoid holding the DB file open after
        # the temporary directory is removed.
        with sqlite3.connect(str(collection_path)) as conn:
            conn.row_factory = sqlite3.Row
            deck_names = _read_deck_names(conn)
            cards = _read_cards(conn, deck_names)
    except sqlite3.Error as exc:  # pragma: no cover - defensive programming
        raise DeckLoadError(f"Failed to open SQLite database: {exc}") from exc

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


def _read_cards(conn: sqlite3.Connection, deck_names: Dict[int, str]) -> List[Card]:
    """Read all cards from the collection and return a list of Card objects.

    This fetches all rows while the DB connection is open so no cursor or
    generator keeps the database file locked after the connection is closed.
    """
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
    rows = conn.execute(query).fetchall()
    cards: List[Card] = []
    for row in rows:
        fields = row["note_fields"].split(_FIELD_SEPARATOR)
        question = fields[0] if fields else ""
        answer = fields[1] if len(fields) > 1 else ""
        extra = fields[2:] if len(fields) > 2 else []
        deck_id = int(row["deck_id"])
        deck_name = deck_names.get(deck_id, str(deck_id))
        cards.append(
            Card(
                card_id=int(row["card_id"]),
                note_id=int(row["note_id"]),
                deck_id=deck_id,
                deck_name=deck_name,
                template_ordinal=int(row["template_ordinal"]),
                question=question,
                answer=answer,
                extra_fields=extra,
            )
        )
    return cards


__all__ = [
    "Card",
    "Deck",
    "DeckCollection",
    "DeckLoadError",
    "load_collection",
]
