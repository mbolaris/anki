"""Flask application factory for the Anki deck viewer.

The module exposes :func:`create_app` which is used both by ``app.py`` and the
test-suite to instantiate a fully configured Flask application. Additional
helpers provide specialised behaviour such as extracting image references from
cards.
"""
from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Iterable, Optional

from flask import Flask, abort, flash, jsonify, redirect, render_template, send_from_directory, url_for
from werkzeug.exceptions import NotFound

from .card_types import (
    detect_card_type,
    is_cloze_card,
    is_image_card,
    parse_cloze_deletions,
)
from .deck_loader import DeckCollection, DeckLoadError, load_collection

_DEFAULT_MEDIA_URL_PATH = "/media"
_IMAGE_SRC_PATTERN = re.compile(r"<img[^>]+src=['\"]([^'\"]+)['\"][^>]*>", re.IGNORECASE)


def create_app(apkg_path: Optional[Path] = None, *, media_url_path: str | None = None, data_dir: Optional[Path] = None) -> Flask:
    """Create and configure the Flask application.

    Parameters
    ----------
    apkg_path:
        Optional path to the Anki package file. When ``None`` the default path
        of ``data/MCAT_High_Yield.apkg`` relative to the project root is used.
    media_url_path:
        Optional URL prefix used when serving extracted media files. When not
        provided the default of ``/media`` is applied.
    data_dir:
        Optional path to directory containing .apkg files. When provided, allows
        switching between multiple deck files.

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
    app.secret_key = "anki_viewer_secret_key_change_in_production"

    configured_media_path = (
        media_url_path if media_url_path is not None else app.config.get("MEDIA_URL_PATH")
    )
    media_url_path = _normalize_media_url_path(configured_media_path)
    app.config["MEDIA_URL_PATH"] = media_url_path

    media_directory = Path(tempfile.mkdtemp(prefix="anki_viewer_media_"))
    app.config["MEDIA_DIRECTORY"] = media_directory
    app.config["DATA_DIR"] = data_dir

    # Discover available deck files
    available_packages = []
    if data_dir and data_dir.exists():
        available_packages = sorted([p for p in data_dir.glob("*.apkg") if p.is_file()])

    # Cache for loaded decks - keeps all decks in memory for fast switching
    deck_cache = {}

    # State for current deck - will be modified by switch_deck
    current_state = {
        "package_path": apkg_path or (available_packages[0] if available_packages else Path("data/MCAT_High_Yield.apkg")),
        "deck_collection": None,
        "media_directory": media_directory,
    }

    def _load_deck(pkg_path: Path) -> DeckCollection | None:
        """Load a deck and update current state. Uses cache for instant switching."""
        # Check if deck is already cached
        cache_key = str(pkg_path)
        if cache_key in deck_cache:
            app.logger.info(f"Loading deck from cache: {pkg_path.name}")
            current_state["deck_collection"] = deck_cache[cache_key]
            current_state["package_path"] = pkg_path
            return deck_cache[cache_key]

        try:
            app.logger.info(f"Loading deck from file: {pkg_path.name}")
            # Clean old media directory
            _clean_media_directory(current_state["media_directory"])

            collection = load_collection(
                pkg_path,
                media_dir=current_state["media_directory"],
                media_url_path=media_url_path,
            )

            # Store in cache
            deck_cache[cache_key] = collection

            current_state["deck_collection"] = collection
            current_state["package_path"] = pkg_path
            return collection
        except DeckLoadError as exc:
            app.logger.warning("Unable to load deck: %s", exc)
            current_state["deck_collection"] = None
            return None

    # Load initial deck
    _load_deck(current_state["package_path"])

    @app.context_processor
    def inject_globals() -> dict:
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
            "deck_collection": current_state["deck_collection"],
            "missing_package": current_state["deck_collection"] is None,
            "package_path": current_state["package_path"],
            "media_url_path": media_url_path,
            "available_packages": available_packages,
            "current_package": current_state["package_path"],
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
        if current_state["deck_collection"] is None:
            return render_template("missing_package.html", package_path=current_state["package_path"])
        return render_template("index.html", collection=current_state["deck_collection"])

    @app.route("/switch/<path:filename>")
    def switch_deck(filename: str):
        """Switch to a different deck file.

        Parameters
        ----------
        filename:
            Name of the .apkg file to load.

        Returns
        -------
        werkzeug.wrappers.response.Response
            Redirect to homepage.
        """
        if not data_dir:
            abort(404)

        target_path = data_dir / filename
        if not target_path.exists() or target_path.suffix != '.apkg':
            abort(404)

        # Hot reload the new deck
        _load_deck(target_path)
        flash(f"Switched to {filename}")
        return redirect(url_for('index'))

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
        if current_state["deck_collection"] is None:
            return render_template("missing_package.html", package_path=current_state["package_path"]), 404

        deck = current_state["deck_collection"].decks.get(deck_id)
        if deck is None:
            return render_template("deck_not_found.html", deck_id=deck_id), 404

        return render_template("deck.html", deck=deck, collection=current_state["deck_collection"])

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
        if current_state["deck_collection"] is None:
            abort(404)

        deck = current_state["deck_collection"].decks.get(deck_id)
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

        if current_state["deck_collection"] is None:
            abort(503)

        cards_payload = []
        for deck in current_state["deck_collection"].decks.values():
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


def _clean_media_directory(media_dir: Path) -> None:
    """Remove all files and directories from the media directory.

    Parameters
    ----------
    media_dir:
        Directory to clean.
    """
    if not media_dir.exists():
        return

    for item in media_dir.iterdir():
        try:
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        except Exception:
            pass
