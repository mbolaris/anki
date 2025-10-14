"""Flask application factory for the Anki deck viewer."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from flask import Flask, render_template

from .deck_loader import DeckCollection, DeckLoadError, load_collection


def create_app(apkg_path: Optional[Path] = None) -> Flask:
    """Create and configure the Flask application.

    Parameters
    ----------
    apkg_path:
        Optional path to the Anki package file. When ``None`` the default path
        of ``data/MCAT_High_Yield.apkg`` relative to the project root is used.
    """

    app = Flask(__name__, template_folder="templates", static_folder="static")

    package_path = _resolve_package_path(apkg_path)

    try:
        deck_collection = load_collection(package_path)
    except DeckLoadError as exc:
        deck_collection = None
        app.logger.warning("Unable to load deck: %s", exc)

    @app.context_processor
    def inject_globals():
        return {
            "deck_collection": deck_collection,
            "missing_package": deck_collection is None,
            "package_path": package_path,
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

    return app


def _resolve_package_path(explicit_path: Optional[Path]) -> Path:
    """Return the package path to load, checking common filename variants."""

    if explicit_path is not None:
        return explicit_path

    default = Path("data/MCAT_High_Yield.apkg")
    if default.exists():
        return default

    data_dir = default.parent
    # Accept alternate filenames with spaces or hyphens in case the user kept
    # the original Anki export name.
    for name in (
        "MCAT High Yield.apkg",
        "MCAT-High-Yield.apkg",
    ):
        candidate = data_dir / name
        if candidate.exists():
            return candidate

    return default


__all__ = ["create_app"]
