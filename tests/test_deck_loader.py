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
        conn.execute("CREATE TABLE col (decks TEXT, models TEXT)")
        models = {
            "1": {
                "name": "Basic",
                "flds": [
                    {"name": "Front"},
                    {"name": "Back"},
                    {"name": "Extra"},
                ],
                "tmpls": [
                    {
                        "name": "Card 1",
                        "qfmt": "<div>{{Front}}</div>",
                        "afmt": "{{FrontSide}}<hr id=answer>{{Back}}",
                    }
                ],
            },
            "2": {
                "name": "Cloze",
                "flds": [
                    {"name": "Text"},
                    {"name": "Back Extra"},
                    {"name": "Extra"},
                ],
                "tmpls": [
                    {
                        "name": "Cloze",
                        "qfmt": "{{cloze:Text}}",
                        "afmt": "{{cloze:Text}}<br>{{Back Extra}}",
                    }
                ],
            },
        }
        conn.execute(
            "INSERT INTO col (decks, models) VALUES (?, ?)",
            (json.dumps({"1": {"name": "Deck"}}), json.dumps(models)),
        )
        conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, flds TEXT, mid INTEGER)")
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
        conn.execute("INSERT INTO notes (id, flds, mid) VALUES (1, ?, 1)", (fields_basic,))
        conn.execute("INSERT INTO notes (id, flds, mid) VALUES (2, ?, 2)", (fields_cloze,))
        conn.execute(
            "CREATE TABLE cards (id INTEGER PRIMARY KEY, nid INTEGER, did INTEGER, ord INTEGER, due INTEGER)"
        )
        conn.execute("INSERT INTO cards VALUES (1, 1, 1, 0, 0)")
        conn.execute("INSERT INTO cards VALUES (2, 2, 1, 0, 1)")
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
    html = '<img src="diagram.png"><img src="diagram"><img src="/other.png">'
    media_map = {"diagram.png": "diagram.png", "diagram": "diagram.png"}
    result = deck_loader._inline_media(html, media_map, "/media")
    assert result.startswith('<img src="/media/diagram.png"')
    assert '<img src="/media/diagram.png"' in result
    assert "/other.png" in result


def test_read_media_copies_manifest(tmp_path: Path, tmp_media_dir: Path) -> None:
    extracted = tmp_path / "apkg"
    extracted.mkdir()
    media_json = extracted / "media"
    (extracted / "0").write_text("img")
    media_json.write_text(json.dumps({"0": "diagram.png"}))
    manifest = deck_loader._read_media(extracted, tmp_media_dir)
    assert manifest["diagram.png"] == "diagram.png"
    assert manifest["diagram"] == "diagram.png"
    assert (tmp_media_dir / "diagram.png").exists()


def test_render_cloze_masks_and_reveals_active_index() -> None:
    html = deck_loader._render_cloze("{{c1::Heart}} pumps", reveal=False, active_index=1)
    assert 'class="cloze blank"' in html
    assert "…" in html
    revealed = deck_loader._render_cloze("{{c1::Heart}} pumps", reveal=True, active_index=1)
    assert '<mark class="cloze reveal">Heart</mark>' in revealed
    assert "Heart" in revealed


def test_render_cloze_only_reveals_selected_deletion() -> None:
    text = "{{c1::Heart::Organ}} pumps {{c2::blood::Fluid}}"
    front = deck_loader._render_cloze(text, reveal=False, active_index=2)
    assert front.count("cloze blank") == 2
    assert "Fluid" in front
    assert "Organ" not in front
    back = deck_loader._render_cloze(text, reveal=True, active_index=2)
    assert "blood" in back
    assert "Heart" not in back
    assert back.count("cloze blank") == 1


def test_render_anki_template_supports_sections() -> None:
    template = "{{#Image}}<div>{{Image}}</div>{{/Image}}{{^Footer}}<span>No footer</span>{{/Footer}}"
    fields = {"Image": "<img src=\"diagram.png\">", "Footer": ""}
    rendered = deck_loader._render_anki_template(template, fields)
    assert "<div><img src=\"diagram.png\"></div>" in rendered
    assert "No footer" in rendered


def test_build_media_url_handles_trailing_slashes() -> None:
    assert deck_loader._build_media_url("diagram.png", "/media/") == "/media/diagram.png"


def test_load_from_sqlite_parses_cards(tmp_path: Path, tmp_media_dir: Path) -> None:
    db_path = tmp_path / "collection.anki21"
    _create_sqlite_collection(db_path)

    media_map = {"diagram.png": "diagram.png"}
    collection = deck_loader._load_from_sqlite(db_path, media_map, "/media")
    basic_card = collection.decks[1].cards[0]
    cloze_card = collection.decks[1].cards[1]
    assert basic_card.card_type == "basic"
    assert "<div>What is 2 + 2?</div>" in basic_card.question
    assert "<hr id=answer>" in basic_card.answer
    assert cloze_card.card_type == "cloze"
    assert cloze_card.cloze_deletions == [{"num": 1, "content": "Heart"}]
    assert "{{c1" not in cloze_card.answer
    assert '<mark class="cloze reveal">Heart</mark>' in cloze_card.answer


def test_load_from_sqlite_handles_multi_cloze_notes(tmp_path: Path, tmp_media_dir: Path) -> None:
    db_path = tmp_path / "collection.anki21"
    _create_sqlite_collection(db_path)
    conn = sqlite3.connect(db_path)
    try:
        fields_multi = deck_loader._FIELD_SEPARATOR.join(
            [
                "{{c1::Alpha::Larger}} or {{c2::Beta::Lower}}",
                "",
                "",
            ]
        )
        conn.execute("INSERT INTO notes (id, flds, mid) VALUES (3, ?, 2)", (fields_multi,))
        conn.execute("INSERT INTO cards VALUES (3, 3, 1, 0, 2)")
        conn.execute("INSERT INTO cards VALUES (4, 3, 1, 1, 3)")
        conn.commit()
    finally:
        conn.close()

    media_map = {"diagram.png": "diagram.png"}
    collection = deck_loader._load_from_sqlite(db_path, media_map, "/media")
    deck = collection.decks[1]
    multi_cards = {card.card_id: card for card in deck.cards if card.note_id == 3}
    assert set(multi_cards) == {3, 4}

    first = multi_cards[3]
    assert first.question.count("cloze blank") == 2
    assert "Larger" in first.question
    assert "Lower" not in first.question
    assert '<mark class="cloze reveal">Alpha</mark>' in first.answer
    assert "Beta" not in first.answer

    second = multi_cards[4]
    assert second.question.count("cloze blank") == 2
    assert "Lower" in second.question
    assert "Larger" not in second.question
    assert '<mark class="cloze reveal">Beta</mark>' in second.answer
    assert "Alpha" not in second.answer


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
