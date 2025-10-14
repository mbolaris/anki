"""Integration tests for Flask routes."""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

import anki_viewer
from anki_viewer import create_app
from anki_viewer.deck_loader import Card, Deck, DeckCollection, DeckLoadError


@pytest.fixture
def sample_collection(tmp_path: Path) -> DeckCollection:
    """Return a minimal collection with all supported card types."""

    media_dir = tmp_path / "media"
    media_dir.mkdir()
    image_filename = "diagram.png"
    (media_dir / image_filename).write_bytes(b"PNG")

    basic_card = Card(
        card_id=1,
        note_id=1,
        deck_id=1,
        deck_name="Test Deck",
        template_ordinal=0,
        question="What is 2 + 2?",
        answer="4",
        card_type="basic",
    )

    cloze_card = Card(
        card_id=2,
        note_id=2,
        deck_id=1,
        deck_name="Test Deck",
        template_ordinal=1,
        question="<span class='cloze-placeholder'>[...]</span>",
        answer="<span class='cloze-revealed'>four</span>",
        card_type="cloze",
        question_revealed="four",
        extra_fields=[],
        raw_question="{{c1::four}}",
        cloze_deletions=[{"num": 1, "content": "four"}],
    )

    image_card = Card(
        card_id=3,
        note_id=3,
        deck_id=1,
        deck_name="Test Deck",
        template_ordinal=2,
        question=f"<img src='/media/{image_filename}'>",
        answer="",
        card_type="image",
        extra_fields=[],
        cloze_deletions=[],
    )

    deck = Deck(deck_id=1, name="Test Deck", cards=[basic_card, cloze_card, image_card])
    collection = DeckCollection(
        decks={1: deck},
        media_directory=media_dir,
        media_filenames={image_filename: image_filename},
        media_url_path="/media",
    )
    return collection


@pytest.fixture
def app(sample_collection: DeckCollection, monkeypatch: pytest.MonkeyPatch) -> Iterator:
    """Create a Flask app that serves the sample collection."""

    monkeypatch.setattr(anki_viewer, "load_collection", lambda *_, **__: sample_collection)
    application = create_app()
    application.config["MEDIA_DIRECTORY"] = sample_collection.media_directory

    yield application


@pytest.fixture
def client(app) -> Iterator:
    """Provide a Flask test client."""

    with app.test_client() as client:
        yield client


@pytest.fixture
def failing_app(monkeypatch: pytest.MonkeyPatch) -> Iterator:
    """Create an app whose deck loading fails to exercise error paths."""

    def _fail(*_, **__):
        raise DeckLoadError("boom")

    monkeypatch.setattr(anki_viewer, "load_collection", _fail)
    application = create_app()
    yield application


def test_api_cards_returns_card_types(client) -> None:
    """The API should return metadata for all cards including their type."""

    response = client.get("/api/cards")
    assert response.status_code == 200
    payload = response.get_json()
    assert {card["type"] for card in payload["cards"]} == {"basic", "cloze", "image"}


def test_media_route_serves_files(client, sample_collection: DeckCollection) -> None:
    """Media files stored in the collection should be downloadable."""

    response = client.get("/media/diagram.png")
    assert response.status_code == 200
    assert response.data == b"PNG"


def test_cloze_card_payload_contains_structure(client) -> None:
    """Cloze card endpoint should include the original text and deletions."""

    response = client.get("/deck/1/card/2.json")
    data = response.get_json()
    assert data["type"] == "cloze"
    assert data["text"] == "{{c1::four}}"
    assert data["clozes"] == [{"num": 1, "content": "four"}]


def test_missing_card_and_media_return_404(client) -> None:
    """Routes should return a 404 status for missing resources."""

    missing_card = client.get("/deck/1/card/999.json")
    missing_media = client.get("/media/missing.png")
    assert missing_card.status_code == 404
    assert missing_media.status_code == 404


def test_deck_route_returns_404_for_unknown_deck(client) -> None:
    """The deck view should return a 404 when the deck ID is unknown."""

    response = client.get("/deck/999")
    assert response.status_code == 404


def test_media_route_returns_404_without_directory(app) -> None:
    """If no media directory is configured the media route should 404."""

    app.config["MEDIA_DIRECTORY"] = None
    with app.test_client() as test_client:
        response = test_client.get("/media/diagram.png")
    assert response.status_code == 404


def test_index_handles_missing_collection(failing_app) -> None:
    """A missing deck package should render the helpful error page."""

    with failing_app.test_client() as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Deck package not found" in response.get_data(as_text=True)


def test_api_cards_returns_503_when_deck_missing(failing_app) -> None:
    """The cards API exposes a 503 status when the deck cannot be loaded."""

    with failing_app.test_client() as client:
        response = client.get("/api/cards")
    assert response.status_code == 503


def test_normalize_media_url_path_variations() -> None:
    """Internal helper should normalise user-provided media paths."""

    assert anki_viewer._normalize_media_url_path("media") == "/media"
    assert anki_viewer._normalize_media_url_path("/assets/") == "/assets"
    assert anki_viewer._normalize_media_url_path("") == "/media"
