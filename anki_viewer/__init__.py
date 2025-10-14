"""Flask application factory for the Anki deck viewer."""
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
        return {
            "deck_collection": deck_collection,
            "missing_package": deck_collection is None,
            "package_path": package_path,
            "media_url_path": media_url_path,
        }

    @app.route("/")
    def index():
        if deck_collection is None:
            return render_template("missing_package.html", package_path=package_path)
        return render_template("index.html", collection=deck_collection)

    @app.route("/deck/<int:deck_id>")
    def deck(deck_id: int):
        if deck_collection is None:
            return render_template("missing_package.html", package_path=package_path), 404

        deck = deck_collection.decks.get(deck_id)
        if deck is None:
            return render_template("deck_not_found.html", deck_id=deck_id), 404

        return render_template("deck.html", deck=deck, collection=deck_collection)

    @app.route("/deck/<int:deck_id>/card/<int:card_id>.json")
    def card_data(deck_id: int, card_id: int):
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

    media_route_prefix = media_url_path or _DEFAULT_MEDIA_URL_PATH

    @app.route(f"{media_route_prefix}/<path:filename>")
    def media(filename: str):
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
    """Return a canonical media URL prefix for *value*."""

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
    """Extract unique image sources from the HTML content of *card*."""

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
