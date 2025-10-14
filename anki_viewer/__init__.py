"""Flask application factory for the Anki deck viewer.

The module exposes :func:`create_app` which is used both by ``app.py`` and the
test-suite to instantiate a fully configured Flask application. Additional
helpers provide specialised behaviour such as extracting image references from
cards.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Iterable, Optional

from flask import Flask, abort, jsonify, render_template, send_from_directory
from werkzeug.exceptions import NotFound

from .card_types import (
    detect_card_type,
    is_cloze_card,
    is_image_card,
    parse_cloze_deletions,
)
from .deck_loader import DeckLoadError, load_collection


_IMAGE_SRC_PATTERN = re.compile(r"<img[^>]+src=['\"]([^'\"]+)['\"][^>]*>", re.IGNORECASE)
_DEFAULT_MEDIA_URL_PATH = "/media"


def create_app(apkg_path: Optional[Path] = None, *, media_url_path: str | None = None) -> Flask:
    """Create and configure the Flask application.

    Parameters
    ----------
    apkg_path:
        Optional path to the Anki package file. When ``None`` the default path
        of ``data/MCAT_High_Yield.apkg`` relative to the project root is used.
    media_url_path:
        Optional URL prefix used when serving extracted media files. When not
        provided the default of ``/media`` is applied.

    Returns
    -------
    flask.Flask
        A ready-to-use Flask application. The returned instance has the
        ``MEDIA_DIRECTORY`` and ``MEDIA_URL_PATH`` configuration values set and
        registers routes for rendering decks and serving card data.

    Examples
    --------
    >>> from anki_viewer import create_app
    >>> app = create_app()
    >>> client = app.test_client()
    >>> client.get('/').status_code in {200, 404}
    True
    """

    app = Flask(__name__, template_folder="templates", static_folder="static")
    configured_media_path = (
        media_url_path if media_url_path is not None else app.config.get("MEDIA_URL_PATH")
    )
    media_url_path = _normalize_media_url_path(configured_media_path)
    app.config["MEDIA_URL_PATH"] = media_url_path

    media_directory = Path(tempfile.mkdtemp(prefix="anki_viewer_media_"))
    app.config["MEDIA_DIRECTORY"] = media_directory

    package_path = apkg_path or Path("data/MCAT_High_Yield.apkg")

    try:
        deck_collection = load_collection(
            package_path,
            media_dir=media_directory,
            media_url_path=media_url_path,
        )
    except DeckLoadError as exc:
        deck_collection = None
        app.logger.warning("Unable to load deck: %s", exc)

    @app.context_processor
    def inject_globals():
        """Provide template helpers for rendering deck metadata.

        Returns
        -------
        dict
            Mapping of values injected into every template.

        Examples
        --------
        >>> inject_globals()["media_url_path"].startswith("/")
        True
        """
        return {
            "deck_collection": deck_collection,
            "missing_package": deck_collection is None,
            "package_path": package_path,
            "media_url_path": media_url_path,
        }

    @app.route("/")
    def index():
        """Render the landing page or missing package notice.

        Returns
        -------
        werkzeug.wrappers.response.Response
            Response object rendering the appropriate template.

        Examples
        --------
        >>> index().status_code in {200, 404}
        True
        """
        if deck_collection is None:
            return render_template("missing_package.html", package_path=package_path)
        return render_template("index.html", collection=deck_collection)

    @app.route("/deck/<int:deck_id>")
    def deck(deck_id: int):
        """Render the detail view for a specific deck.

        Parameters
        ----------
        deck_id:
            Identifier of the deck to render.

        Returns
        -------
        tuple | werkzeug.wrappers.response.Response
            Response containing the deck view or a 404 template.

        Examples
        --------
        >>> deck(0)[1] if isinstance(deck(0), tuple) else deck(0).status_code  # doctest: +SKIP
        404
        """
        if deck_collection is None:
            return render_template("missing_package.html", package_path=package_path), 404

        deck = deck_collection.decks.get(deck_id)
        if deck is None:
            return render_template("deck_not_found.html", deck_id=deck_id), 404

        return render_template("deck.html", deck=deck, collection=deck_collection)

    @app.route("/deck/<int:deck_id>/card/<int:card_id>.json")
    def card_data(deck_id: int, card_id: int):
        """Return JSON describing an individual card.

        The payload contains the card's text as well as any additional metadata
        derived during ingestion such as cloze deletions or inline image
        sources.

        Parameters
        ----------
        deck_id:
            Identifier of the deck containing the card.
        card_id:
            Identifier of the card within the deck.

        Returns
        -------
        flask.Response
            JSON payload describing the card.

        Examples
        --------
        >>> card_data(1, 1).status_code  # doctest: +SKIP
        200
        """
        if deck_collection is None:
            abort(404)

        deck = deck_collection.decks.get(deck_id)
        if deck is None:
            abort(404)

        card = next((card for card in deck.cards if card.card_id == card_id), None)
        if card is None:
            abort(404)

        payload = {
            "id": card.card_id,
            "type": card.card_type,
            "question": card.question,
            "answer": card.answer,
            "question_revealed": card.question_revealed,
            "extra_fields": card.extra_fields,
        }

        if card.card_type == "cloze":
            payload["text"] = card.raw_question or ""
            payload["clozes"] = [
                {"num": deletion.get("num"), "content": deletion.get("content")}
                for deletion in card.cloze_deletions
            ]
        elif card.card_type == "image":
            image_sources = _gather_image_sources(card, media_url_path=media_url_path)
            if image_sources:
                payload["images"] = image_sources

        return jsonify(payload)

    @app.route("/api/cards")
    def list_cards():
        """Return a JSON list containing high-level metadata for each card.

        This endpoint is primarily intended for automated verification and UI
        tests where only the deck identifier, card identifier and card type are
        required.

        Returns
        -------
        flask.Response
            JSON payload with a ``cards`` list.

        Examples
        --------
        >>> list_cards().json  # doctest: +SKIP
        {'cards': [...]}  # doctest: +SKIP
        """

        if deck_collection is None:
            abort(503)

        cards_payload = []
        for deck in deck_collection.decks.values():
            for card in deck.cards:
                cards_payload.append(
                    {
                        "id": card.card_id,
                        "deck_id": card.deck_id,
                        "deck_name": card.deck_name,
                        "type": card.card_type,
                    }
                )

        return jsonify({"cards": cards_payload})

    media_route_prefix = media_url_path or _DEFAULT_MEDIA_URL_PATH

    @app.route(f"{media_route_prefix}/<path:filename>")
    def media(filename: str):
        """Serve media files extracted from the Anki package.

        Parameters
        ----------
        filename:
            Relative filename of the media asset to serve.

        Returns
        -------
        flask.Response
            Response streaming the requested file.

        Examples
        --------
        >>> media('image.png').status_code  # doctest: +SKIP
        200
        """
        media_dir = app.config.get("MEDIA_DIRECTORY")
        if media_dir is None:
            abort(404)
        try:
            return send_from_directory(media_dir, filename)
        except (FileNotFoundError, NotFound):
            abort(404)

    return app


__all__ = [
    "create_app",
    "detect_card_type",
    "is_cloze_card",
    "is_image_card",
    "parse_cloze_deletions",
]


def _normalize_media_url_path(value: str | None) -> str:
    """Return a canonical media URL prefix for *value*.

    Parameters
    ----------
    value:
        Raw value retrieved from configuration or the environment.

    Returns
    -------
    str
        Sanitised path that always starts with a ``/`` and does not end with a
        trailing slash. When *value* is empty the default ``/media`` prefix is
        returned.

    Examples
    --------
    >>> _normalize_media_url_path('media')
    '/media'
    >>> _normalize_media_url_path('/assets/')
    '/assets'
    """

    if not value:
        return _DEFAULT_MEDIA_URL_PATH
    cleaned = value.strip()
    if not cleaned:
        return _DEFAULT_MEDIA_URL_PATH
    cleaned = cleaned.rstrip("/")
    if not cleaned:
        return _DEFAULT_MEDIA_URL_PATH
    if not cleaned.startswith("/"):
        cleaned = f"/{cleaned}"
    return cleaned


def _gather_image_sources(card: object, *, media_url_path: str) -> list[str]:
    """Extract unique image sources from the HTML content of *card*.

    Parameters
    ----------
    card:
        Card-like object containing HTML fields to inspect.
    media_url_path:
        Base path that valid image sources must begin with.

    Returns
    -------
    list[str]
        Sorted list of unique image URLs belonging to the provided card.

    Examples
    --------
    >>> from types import SimpleNamespace
    >>> sample = SimpleNamespace(question="<img src='/media/a.png'>", answer="")
    >>> _gather_image_sources(sample, media_url_path='/media')
    ['/media/a.png']
    """

    texts: Iterable[str | None] = (
        getattr(card, "question", None),
        getattr(card, "answer", None),
        getattr(card, "question_revealed", None),
    )
    extra_fields = getattr(card, "extra_fields", []) or []
    sources = set()

    for text in list(texts) + list(extra_fields):
        if not text:
            continue
        for match in _IMAGE_SRC_PATTERN.finditer(text):
            src = match.group(1)
            if not src:
                continue
            if src.startswith(media_url_path):
                sources.add(src)

    return sorted(sources)
