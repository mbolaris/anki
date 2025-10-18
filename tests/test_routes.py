"""Integration tests for Flask routes."""
from __future__ import annotations

import re
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
        template_ordinal=0,
        question="<span class='cloze blank'>…</span>",
        answer="<mark class='cloze reveal'>four</mark>",
        card_type="cloze",
        question_revealed="<mark class='cloze reveal'>four</mark>",
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
def app(
    sample_collection: DeckCollection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator:
    """Create a Flask app that serves the sample collection."""

    monkeypatch.setattr(anki_viewer, "load_collection", lambda *_, **__: sample_collection)
    application = create_app(data_dir=tmp_path)
    application.config["MEDIA_DIRECTORY"] = sample_collection.media_directory

    for stored_name in sample_collection.media_filenames.values():
        media_path = sample_collection.media_directory / stored_name
        if not media_path.exists():
            media_path.write_bytes(b"PNG")

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
    # Ensure any file-like objects opened by the response are closed to avoid
    # ResourceWarning about unclosed files when running the test suite.
    try:
        response.close()
    except Exception:
        pass


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
    # Close the response explicitly in case the test client created any
    # temporary file-like objects during handling.
    try:
        response.close()
    except Exception:
        pass
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


def test_rating_endpoint_allows_multiple_labels(client) -> None:
    """Ratings API should preserve independent labels for a card."""

    response = client.post(
        "/api/card/1/rating",
        json={"deck_id": 1, "rating": ["favorite"]},
    )
    assert response.status_code == 200
    assert response.get_json()["rating"] == ["favorite"]

    response = client.post(
        "/api/card/1/rating",
        json={"deck_id": 1, "rating": ["favorite", "memorized"]},
    )
    assert response.status_code == 200
    assert response.get_json()["rating"] == ["favorite", "memorized"]

    response = client.get("/api/deck/1/ratings")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload == {"ratings": {"1": ["favorite", "memorized"]}}


def test_normalize_media_url_path_variations() -> None:
    """Internal helper should normalise user-provided media paths."""

    assert anki_viewer._normalize_media_url_path("media") == "/media"
    assert anki_viewer._normalize_media_url_path("/assets/") == "/assets"
    assert anki_viewer._normalize_media_url_path("") == "/media"


def _extract_toggle_button(html: str, action: str) -> str:
    match = re.search(
        rf"<button[^>]+data-action=\"{action}\"[^>]*>.*?</button>",
        html,
        re.DOTALL,
    )
    assert match is not None
    return match.group(0)


def _extract_rating_button(html: str, rating: str) -> str:
    match = re.search(
        rf"<button[^>]+data-action=\"set-rating\"[^>]+data-rating=\"{rating}\"[^>]*>.*?</button>",
        html,
        re.DOTALL,
    )
    assert match is not None
    return match.group(0)


def test_deck_template_hides_memorized_by_default(app, sample_collection: DeckCollection) -> None:
    """Regular decks should hide memorized cards initially."""

    with app.test_request_context('/'):
        template = app.jinja_env.get_template("deck.html")
        html = template.render(deck=sample_collection.decks[1], collection=sample_collection)

    assert 'data-hide-memorized-default="true"' in html
    button = _extract_toggle_button(html, "toggle-hide-memorized")
    assert 'aria-pressed="true"' in button
    assert 'title="Show memorized cards"' in button
    assert '>Hide Memorized<' in button


def test_favorites_template_shows_memorized_by_default(app, sample_collection: DeckCollection) -> None:
    """Favorites view should surface memorized cards automatically."""

    with app.test_request_context('/'):
        template = app.jinja_env.get_template("deck.html")
        html = template.render(
            deck=sample_collection.decks[1],
            collection=sample_collection,
            is_favorites=True,
        )

    assert 'data-hide-memorized-default="false"' in html
    button = _extract_toggle_button(html, "toggle-hide-memorized")
    assert 'aria-pressed="false"' in button
    assert 'title="Hide memorized cards"' in button
    assert '>Show Memorized<' in button


def test_debug_control_is_rendered_as_toggle(app, sample_collection: DeckCollection) -> None:
    """Debug control should present toggle state information for accessibility."""

    with app.test_request_context('/'):
        template = app.jinja_env.get_template("deck.html")
        html = template.render(deck=sample_collection.decks[1], collection=sample_collection)

    toggle = _extract_toggle_button(html, "toggle-debug")
    assert 'class="toolbar-toggle toggle-switch"' in toggle
    assert 'title="Show debug information (D)"' in toggle
    assert 'data-role="toggle-state">Off<' in toggle


def test_card_has_memorized_rating_control(app, sample_collection: DeckCollection) -> None:
    """Each card should expose a memorized rating control."""

    with app.test_request_context('/'):
        template = app.jinja_env.get_template("deck.html")
        html = template.render(deck=sample_collection.decks[1], collection=sample_collection)

    button = _extract_rating_button(html, "memorized")
    assert 'class="rating-button rating-button--memorized"' in button
    assert 'title="Mark as Memorized"' in button
    assert '>Memorized<' in button
