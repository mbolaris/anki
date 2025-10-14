"""Unit tests for deck loader utilities."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from zipfile import ZipFile

from anki_viewer import deck_loader


def _create_sqlite_collection(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE col (decks TEXT)")
        conn.execute("INSERT INTO col VALUES (?)", (json.dumps({"1": {"name": "Deck"}}),))
        conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, flds TEXT)")
        fields_basic = deck_loader._FIELD_SEPARATOR.join([
            "What is 2 + 2?",
            "4",
            "",
        ])
        fields_cloze = deck_loader._FIELD_SEPARATOR.join([
            "{{c1::Heart}} pumps blood",
            "Answer",
            "Extra",
        ])
        conn.execute("INSERT INTO notes VALUES (1, ?)", (fields_basic,))
        conn.execute("INSERT INTO notes VALUES (2, ?)", (fields_cloze,))
        conn.execute(
            "CREATE TABLE cards (id INTEGER PRIMARY KEY, nid INTEGER, did INTEGER, ord INTEGER, due INTEGER)"
        )
        conn.execute("INSERT INTO cards VALUES (1, 1, 1, 0, 0)")
        conn.execute("INSERT INTO cards VALUES (2, 2, 1, 1, 1)")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def tmp_media_dir(tmp_path: Path) -> Path:
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    return media_dir


def test_sanitize_media_filename_removes_unsafe_chars() -> None:
    assert deck_loader._sanitize_media_filename(" folder/weird name?.png") == "weird_name_.png"


def test_dedupe_filename_appends_counter(tmp_media_dir: Path) -> None:
    first = tmp_media_dir / "image.png"
    first.write_text("data")
    assert deck_loader._dedupe_filename(tmp_media_dir, "image.png") == "image_1.png"


def test_prepare_media_directory_clears_old_files(tmp_media_dir: Path) -> None:
    stale = tmp_media_dir / "old.txt"
    stale.write_text("stale")
    deck_loader._prepare_media_directory(tmp_media_dir)
    assert not stale.exists()


def test_store_media_file_copies_source(tmp_media_dir: Path, tmp_path: Path) -> None:
    source = tmp_path / "diagram.png"
    source.write_text("diagram")
    stored_name = deck_loader._store_media_file(tmp_media_dir, "diagram.png", source)
    assert stored_name == "diagram.png"
    assert (tmp_media_dir / stored_name).read_text() == "diagram"


def test_inline_media_rewrites_sources() -> None:
    html = '<img src="diagram.png"><img src="/other.png">'
    media_map = {"diagram.png": "diagram.png"}
    result = deck_loader._inline_media(html, media_map, "/media")
    assert result.startswith('<img src="/media/diagram.png"')
    assert "/other.png" in result


def test_read_media_copies_manifest(tmp_path: Path, tmp_media_dir: Path) -> None:
    extracted = tmp_path / "apkg"
    extracted.mkdir()
    media_json = extracted / "media"
    (extracted / "0").write_text("img")
    media_json.write_text(json.dumps({"0": "diagram.png"}))
    manifest = deck_loader._read_media(extracted, tmp_media_dir)
    assert manifest == {"diagram.png": "diagram.png"}
    assert (tmp_media_dir / "diagram.png").exists()


def test_render_cloze_outputs_placeholder() -> None:
    html = deck_loader._render_cloze("{{c1::Heart}}", reveal=False)
    assert "cloze-hidden" in html
    revealed = deck_loader._render_cloze("{{c1::Heart}}", reveal=True)
    assert "Heart" in revealed


def test_build_media_url_handles_trailing_slashes() -> None:
    assert deck_loader._build_media_url("diagram.png", "/media/") == "/media/diagram.png"


def test_load_from_sqlite_parses_cards(tmp_path: Path, tmp_media_dir: Path) -> None:
    db_path = tmp_path / "collection.anki21"
    _create_sqlite_collection(db_path)

    media_map = {"diagram.png": "diagram.png"}
    collection = deck_loader._load_from_sqlite(db_path, media_map, "/media")
    assert collection.decks[1].cards[0].card_type == "basic"
    assert collection.decks[1].cards[1].card_type == "cloze"
    assert collection.decks[1].cards[1].cloze_deletions == [{"num": 1, "content": "Heart"}]


def test_load_collection_raises_for_missing_package(tmp_path: Path) -> None:
    with pytest.raises(deck_loader.DeckLoadError):
        deck_loader.load_collection(tmp_path / "missing.apkg")


def test_load_collection_reads_package(tmp_path: Path, tmp_media_dir: Path) -> None:
    db_path = tmp_path / "collection.anki21"
    _create_sqlite_collection(db_path)

    package_path = tmp_path / "sample.apkg"
    with ZipFile(package_path, "w") as archive:
        archive.write(db_path, arcname="collection.anki21")
        archive.writestr("media", json.dumps({"0": "diagram.png"}))
        archive.writestr("0", "diagram")

    collection = deck_loader.load_collection(
        package_path,
        media_dir=tmp_media_dir,
        media_url_path="/media",
    )
    assert collection.total_cards == 2
    assert (tmp_media_dir / "diagram.png").exists()
