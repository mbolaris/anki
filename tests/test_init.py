"""Tests for the package-level helpers and Flask application factory.

These tests cover small helpers in `anki_viewer.__init__` as well as a set
of Flask routes by monkeypatching the heavy package loader with a lightweight
fake that returns a deterministic DeckCollection.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from anki_viewer import _gather_image_sources, _normalize_media_url_path, create_app
from anki_viewer import deck_loader


def test_normalize_media_url_path_variants() -> None:
    assert _normalize_media_url_path(None) == "/media"
    assert _normalize_media_url_path("") == "/media"
    assert _normalize_media_url_path("media") == "/media"
    assert _normalize_media_url_path("/assets/") == "/assets"


def test_gather_image_sources_ignores_non_media_prefix() -> None:
    card = SimpleNamespace(
        question='<img src="/media/a.png"><img src="/static/b.png">',
        answer=None,
        extra_fields=[],
    )
    assert _gather_image_sources(card, media_url_path="/media") == ["/media/a.png"]


def test_flask_routes_with_monkeypatched_loader(tmp_path: Path, monkeypatch) -> None:
    """Monkeypatch the package loader to provide a simple collection and
    assert several routes behave as expected (JSON payloads, media serving
    and error responses).
    """

    media_dir = tmp_path / "media"
    # Prepare a fake load_collection implementation that writes a media file
    # and returns a DeckCollection with one deck and one image card.
    def fake_load_collection(pkg_path, *, media_dir: Path | None = None, media_url_path: str = "/media"):
        media_dir.mkdir(parents=True, exist_ok=True)
        # create a media file that the media endpoint can serve
        img = media_dir / "img.png"
        img.write_bytes(b"PNGDATA")

        card = deck_loader.Card(
            card_id=1,
            note_id=1,
            deck_id=10,
            deck_name="Example",
            template_ordinal=0,
            question=f"<img src=\"{media_url_path}/img.png\">",
            answer="",
            card_type="image",
            question_revealed=None,
            extra_fields=[],
            raw_question=None,
            cloze_deletions=[],
        )
        deck = deck_loader.Deck(deck_id=10, name="Example", cards=[card])
        collection = deck_loader.DeckCollection(decks={10: deck}, media_directory=media_dir, media_filenames={"img.png": "img.png"}, media_url_path=media_url_path)
        return collection

    monkeypatch.setattr("anki_viewer.load_collection", fake_load_collection)

    app = create_app(Path("dummy.apkg"), media_url_path="/media")
    client = app.test_client()

    # The index should render (collection exists because fake loader returned one)
    resp = client.get("/")
    assert resp.status_code == 200

    # Card JSON endpoint should return the image and debug information
    resp = client.get("/deck/10/card/1.json")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == 1
    assert "debug" in data
    # Ensure media status was reported for the found image
    dbg = data["debug"]
    assert "image_file_status" in dbg
    # Confirm the media endpoint serves the created file
    media_resp = client.get("/media/img.png")
    assert media_resp.status_code == 200
    assert media_resp.data == b"PNGDATA"

    # Missing media returns 404
    missing = client.get("/media/missing.png")
    assert missing.status_code == 404

    # api/cards should list the single card
    api = client.get("/api/cards")
    assert api.status_code == 200
    assert api.get_json()["cards"][0]["id"] == 1

    # switch endpoint without a data_dir should return 404
    sw = client.get("/switch/anything.apkg")
    assert sw.status_code == 404
