"""Flask application factory for the Anki deck viewer.

The module exposes :func:`create_app` which is used both by ``app.py`` and the
test-suite to instantiate a fully configured Flask application. Additional
helpers provide specialised behaviour such as extracting image references from
cards.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from logging import Logger
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Iterable

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.exceptions import NotFound

from .card_types import (
    detect_card_type,
    is_cloze_card,
    is_image_card,
    parse_cloze_deletions,
)
from .deck_loader import DeckCollection, DeckLoadError, load_collection
from .ratings import RatingsStore

_DEFAULT_MEDIA_URL_PATH = "/media"
_IMAGE_SRC_PATTERN = re.compile(r"<img[^>]+src=['\"]([^'\"]+)['\"][^>]*>", re.IGNORECASE)

# In-process caches to avoid repeated os.listdir/stat for common lookups.
# _MEDIA_NAMES_CACHE: {abs_path: (timestamp, set_of_names)}
_MEDIA_NAMES_CACHE: dict = {}
# _MEDIA_LOOKUP_CACHE: {(abs_path, filename): (timestamp, stored_name, reason)}
_MEDIA_LOOKUP_CACHE: dict = {}

@dataclass
class _AppState:
    """Holds mutable state for the running application."""

    media_directory: Path
    package_path: Path
    deck_collection: DeckCollection | None = None
    deck_cache: dict[str, DeckCollection] = field(default_factory=dict)

    def load_deck(
        self,
        pkg_path: Path,
        *,
        clean_media: bool,
        media_url_path: str,
    ) -> tuple[DeckCollection | None, bool]:
        """Load *pkg_path* into memory and update the cached state."""

        cache_key = str(pkg_path.resolve())
        if cache_key in self.deck_cache:
            collection = self.deck_cache[cache_key]
            self.deck_collection = collection
            self.package_path = pkg_path
            return collection, True

        try:
            if clean_media:
                _clean_media_directory(self.media_directory)

            collection = load_collection(
                pkg_path,
                media_dir=self.media_directory,
                media_url_path=media_url_path,
            )
        except DeckLoadError:
            self.deck_collection = None
            self.package_path = pkg_path
            raise

        self.deck_cache[cache_key] = collection
        self.deck_collection = collection
        self.package_path = pkg_path
        return collection, False


def create_app(
    apkg_path: Path | None = None,
    *,
    media_url_path: str | None = None,
    data_dir: Path | None = None,
) -> Flask:
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
    app.config.setdefault("MEDIA_LOOKUP_TTL", float(os.environ.get("ANKI_MEDIA_LOOKUP_TTL", "5.0")))

    _configure_secret_key(app)

    configured_media_path = media_url_path or app.config.get("MEDIA_URL_PATH")
    media_url_path = _normalize_media_url_path(configured_media_path)
    app.config["MEDIA_URL_PATH"] = media_url_path

    media_directory = _resolve_media_directory(data_dir)
    app.config["MEDIA_DIRECTORY"] = media_directory
    app.config["DATA_DIR"] = data_dir
    app.logger.info("Media directory: %s", media_directory)

    available_packages = _discover_packages(data_dir)
    starting_package = _select_starting_package(apkg_path, available_packages)

    state = _AppState(media_directory=media_directory, package_path=starting_package)

    ratings_store = RatingsStore(data_dir)
    media_lookup_stats = {"count": 0, "total_time_s": 0.0}

    def load_deck(pkg_path: Path, *, clean_media: bool = True) -> DeckCollection | None:
        try:
            collection, from_cache = state.load_deck(
                pkg_path,
                clean_media=clean_media,
                media_url_path=media_url_path,
            )
        except DeckLoadError as exc:
            app.logger.warning("Unable to load deck %s: %s", pkg_path.name, exc)
            return None

        if from_cache:
            app.logger.info("Loaded deck from cache: %s", pkg_path.name)
        else:
            app.logger.info("Loaded deck from file: %s", pkg_path.name)
        return collection

    load_deck(starting_package)

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
            "deck_collection": state.deck_collection,
            "missing_package": state.deck_collection is None,
            "package_path": state.package_path,
            "media_url_path": media_url_path,
            "available_packages": available_packages,
            "current_package": state.package_path,
        }

    def _build_deck_filters(collection: DeckCollection) -> list[dict[str, str | None]]:
        """Create metadata describing available top-level deck filters."""

        root_names: dict[str, None] = {}
        for deck in collection.decks.values():
            root = deck.name.split("::", 1)[0]
            root_names[root] = None

        shortcuts = [str(number) for number in range(1, 10)]
        filters: list[dict[str, str | None]] = []
        for index, root_name in enumerate(sorted(root_names.keys(), key=str.casefold)):
            shortcut = shortcuts[index] if index < len(shortcuts) else None
            filters.append({
                "label": root_name,
                "value": root_name,
                "shortcut": shortcut,
            })

        return filters

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
        if state.deck_collection is None:
            return render_template("missing_package.html", package_path=state.package_path)
        collection = state.deck_collection
        filters = _build_deck_filters(collection)
        return render_template(
            "index.html",
            collection=collection,
            deck_filters=filters,
        )

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
        load_deck(target_path)
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
        if state.deck_collection is None:
            return render_template("missing_package.html", package_path=state.package_path), 404

        deck = state.deck_collection.decks.get(deck_id)
        if deck is None:
            return render_template("deck_not_found.html", deck_id=deck_id), 404

        return render_template("deck.html", deck=deck, collection=state.deck_collection)

    @app.route("/favorites")
    def favorites():
        """Render a virtual deck containing all favorite cards from all loaded decks.

        Returns
        -------
        werkzeug.wrappers.response.Response
            Response containing the favorites deck view.
        """
        if not data_dir:
            abort(501, description="Favorites deck requires data directory")

        favorites_map = ratings_store.get_all_favorites()

        if not favorites_map:
            flash("No favorite cards yet! Mark some cards as favorites to see them here.")
            return redirect(url_for('index'))

        favorite_cards = _collect_favorite_cards(
            available_packages,
            loader=load_deck,
            favorites_map=favorites_map,
            media_directory=state.media_directory,
            logger=app.logger,
        )

        if not favorite_cards:
            flash("No favorite cards found. The favorites may be from decks that are no longer available.")
            return redirect(url_for('index'))

        favorites_deck = SimpleNamespace(
            deck_id=999999,  # Special ID for favorites
            name="Favorites",
            cards=favorite_cards
        )

        return render_template("deck.html", deck=favorites_deck, collection=state.deck_collection, is_favorites=True)

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
        if state.deck_collection is None:
            abort(404)

        deck = state.deck_collection.decks.get(deck_id)
        if deck is None:
            abort(404)

        card = next((card for card in deck.cards if card.card_id == card_id), None)
        if card is None:
            abort(404)

        image_sources = _gather_image_sources(card, media_url_path=media_url_path)

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
        if card.card_type == "image" and image_sources:
            payload["images"] = image_sources

        # Use the consolidated debug helper (keeps logic in one place)
        payload["debug"] = _build_card_debug_payload(
            card,
            image_sources=image_sources,
            media_url_path=media_url_path,
            media_directory=state.media_directory,
            deck_collection=state.deck_collection,
        )
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

        if state.deck_collection is None:
            abort(503)

        cards_payload = []
        for deck in state.deck_collection.decks.values():
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

    @app.route("/health")
    def health():
        """Lightweight health check used by monitoring and dev tooling."""
        return jsonify({"status": "ok"})

    @app.route("/dev/media-matches/<path:filename>")
    def dev_media_matches(filename: str):
        """Developer-only endpoint that lists case-insensitive filename matches.

        Enabled when the environment variable ANKI_VIEWER_DEV=1 or when Flask
        debug mode is active. This is only for troubleshooting and should not be
        exposed in production.
        """
        enabled = os.environ.get("ANKI_VIEWER_DEV") == "1" or app.debug
        if not enabled:
            abort(404)

        media_dir = app.config.get("MEDIA_DIRECTORY")
        if media_dir is None:
            abort(404)

        # collect case-insensitive matches in the media directory
        try:
            matches = [entry.name for entry in Path(media_dir).iterdir() if entry.is_file() and entry.name.lower() == filename.lower()]
        except OSError:
            matches = []

        return jsonify({"requested": filename, "matches": matches})

    @app.route("/dev/media-stats")
    def dev_media_stats():
        """Developer-only endpoint exposing media lookup stats.

        Enabled when ANKI_VIEWER_DEV=1 or app.debug. Returns counts and average
        lookup time in milliseconds.
        """
        enabled = os.environ.get("ANKI_VIEWER_DEV") == "1" or app.debug
        if not enabled:
            abort(404)

        stats = dict(media_lookup_stats)
        avg_ms = None
        if stats.get("count"):
            avg_ms = (stats.get("total_time_s", 0.0) / max(1, stats.get("count"))) * 1000.0

        return jsonify({
            "count": stats.get("count", 0),
            "total_time_ms": int(stats.get("total_time_s", 0.0) * 1000),
            "avg_lookup_time_ms": int(avg_ms) if avg_ms is not None else None,
        })

    @app.route("/api/deck/<int:deck_id>/ratings")
    def get_ratings(deck_id: int):
        """Get all card ratings for a specific deck.

        Parameters
        ----------
        deck_id:
            Identifier of the deck.

        Returns
        -------
        flask.Response
            JSON payload with ratings mapping (card_id -> rating).
        """
        if not data_dir:
            abort(501, description="Ratings storage not configured")

        ratings = ratings_store.load(deck_id)
        return jsonify({"ratings": ratings})

    @app.route("/api/card/<int:card_id>/rating", methods=["POST"])
    def set_rating(card_id: int):
        """Set or clear a rating for a specific card.

        Parameters
        ----------
        card_id:
            Identifier of the card.

        Request Body
        ------------
        JSON with:
            - deck_id: int - The deck containing the card
            - rating: str - "favorite", "bad", or "" to clear

        Returns
        -------
        flask.Response
            JSON payload with success status.
        """
        if not data_dir:
            abort(501, description="Ratings storage not configured")

        data = request.get_json() or {}
        deck_id = data.get("deck_id")
        rating = data.get("rating", "")

        if not deck_id:
            abort(400, description="deck_id is required")

        if rating not in ["favorite", "bad", "memorized", ""]:
            abort(400, description="rating must be 'favorite', 'bad', 'memorized', or empty string")

        # Load existing ratings
        ratings = ratings_store.load(deck_id)

        # Update or remove rating
        card_id_str = str(card_id)
        if rating:
            ratings[card_id_str] = rating
        else:
            ratings.pop(card_id_str, None)

        # Save back
        ratings_store.save(deck_id, ratings)

        return jsonify({"success": True, "card_id": card_id, "rating": rating})

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

        # Delegate the lookup to a helper that returns (stored_name, reason)
        # where reason is one of: 'exact', 'map-exact', 'map-ci', 'fs-ci'
        start = time.time()
        ttl = float(app.config.get("MEDIA_LOOKUP_TTL", 5.0))
        candidate, reason = _find_media_for_filename(media_dir, filename, state.deck_collection, ttl=ttl)
        elapsed = time.time() - start

        # update in-memory stats
        try:
            media_lookup_stats["count"] += 1
            media_lookup_stats["total_time_s"] += elapsed
        except Exception:
            pass

        if candidate:
            try:
                resp = send_from_directory(media_dir, candidate)
                # diagnostic timing header in milliseconds
                resp.headers["X-Media-Lookup-Time-ms"] = str(int(elapsed * 1000))
                if reason and reason != "exact":
                    resp.headers["X-Media-Fallback"] = reason
                return resp
            except (FileNotFoundError, NotFound, OSError):
                pass

        abort(404)

    return app


__all__ = [
    "create_app",
    "detect_card_type",
    "is_cloze_card",
    "is_image_card",
    "parse_cloze_deletions",
]


def _configure_secret_key(app: Flask) -> None:
    """Configure ``app.secret_key`` with sensible defaults."""

    env_secret = os.environ.get("ANKI_VIEWER_SECRET_KEY") or os.environ.get("FLASK_SECRET_KEY")
    if env_secret:
        app.secret_key = env_secret
        return

    app.secret_key = "anki_viewer_secret_key_change_in_production"
    try:
        app.logger.warning(
            "Using default secret key for Flask; set ANKI_VIEWER_SECRET_KEY in production to a secure value"
        )
    except Exception:
        pass


def _resolve_media_directory(data_dir: Path | None) -> Path:
    """Return an absolute media directory, creating it when needed."""

    if data_dir:
        media_dir = (data_dir / "media").resolve()
        media_dir.mkdir(parents=True, exist_ok=True)
    else:
        media_dir = Path(tempfile.mkdtemp(prefix="anki_viewer_media_"))

    if not media_dir.is_absolute():
        raise ValueError(f"Media directory must be absolute path, got: {media_dir}")
    if not media_dir.exists():
        raise ValueError(f"Media directory does not exist: {media_dir}")

    return media_dir


def _discover_packages(data_dir: Path | None) -> list[Path]:
    """Return all ``.apkg`` packages contained in *data_dir*."""

    if not data_dir or not data_dir.exists():
        return []
    return sorted(p for p in data_dir.glob("*.apkg") if p.is_file())


def _select_starting_package(provided: Path | None, packages: Iterable[Path]) -> Path:
    """Choose the initial deck to load for the application."""

    if provided:
        return provided

    preferred = next((p for p in packages if p.name == "MCAT_Milesdown.apkg"), None)
    if preferred:
        return preferred

    return next(iter(packages), Path("data/MCAT_High_Yield.apkg"))


def _collect_favorite_cards(
    packages: Iterable[Path],
    *,
    loader: Callable[..., DeckCollection | None],
    favorites_map: dict[int, dict[str, str]],
    media_directory: Path,
    logger: Logger,
) -> list[object]:
    """Aggregate favorite cards from all known decks."""

    if not packages:
        return []

    _clean_media_directory(media_directory)
    favorite_cards: list[object] = []

    for pkg_path in packages:
        try:
            collection = loader(pkg_path, clean_media=False)
        except Exception as exc:  # pragma: no cover - defensive log
            logger.warning("Failed to load cards from %s: %s", pkg_path, exc)
            continue

        if not collection:
            continue

        for deck_id, deck in collection.decks.items():
            favorite_ids = favorites_map.get(deck_id)
            if not favorite_ids:
                continue

            favorite_cards.extend(
                card for card in deck.cards if str(card.card_id) in favorite_ids
            )

    return favorite_cards


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


def _build_card_debug_payload(
    card: object,
    *,
    image_sources: Iterable[str],
    media_url_path: str,
    media_directory: Path | None,
    deck_collection: DeckCollection | None,
) -> dict[str, object]:
    """Return diagnostic metadata describing *card* and its media assets."""

    debug: dict[str, object] = {
        "note_id": getattr(card, "note_id", None),
        "deck_id": getattr(card, "deck_id", None),
        "deck_name": getattr(card, "deck_name", None),
        "template_ordinal": getattr(card, "template_ordinal", None),
        "raw_question": getattr(card, "raw_question", None),
        "cloze_deletions": getattr(card, "cloze_deletions", []),
        "question_html_length": len(getattr(card, "question", "") or ""),
        "answer_html_length": len(getattr(card, "answer", "") or ""),
        "has_question_revealed": getattr(card, "question_revealed", None) is not None,
        "extra_fields_count": len(getattr(card, "extra_fields", []) or []),
    }

    card_type = getattr(card, "card_type", None)
    sources_list = list(image_sources)
    if not sources_list and card_type != "image":
        return debug

    debug["image_sources_found"] = sources_list
    debug["media_url_path"] = media_url_path
    debug["media_directory"] = str(media_directory) if media_directory else None

    if media_directory and media_directory.exists():
        debug["image_file_status"] = _describe_image_files(media_directory, sources_list)

    if deck_collection and deck_collection.media_filenames:
        media_filenames = deck_collection.media_filenames
        debug["available_media_files_sample"] = list(media_filenames.keys())[:10]
        debug["total_media_files"] = len(media_filenames)

        similar = _find_similar_media_files(sources_list, media_filenames.keys())
        if similar:
            debug["similar_media_files"] = similar

    return debug


def _describe_image_files(media_dir: Path, image_sources: Iterable[str]) -> dict[str, dict[str, object]]:
    """Return on-disk metadata for the images referenced in *image_sources*."""

    status: dict[str, dict[str, object]] = {}
    for src in image_sources:
        filename = _extract_filename(src)
        file_path = media_dir / filename
        exists = file_path.exists()
        status[src] = {
            "filename": filename,
            "exists_on_disk": exists,
            "full_path": str(file_path) if exists else None,
        }
    return status


def _find_similar_media_files(
    image_sources: Iterable[str],
    media_filenames: Iterable[str],
) -> dict[str, list[str]]:
    """Suggest filenames from *media_filenames* that closely match image references."""

    normalised_media = [
        (filename, _normalise_filename(filename))
        for filename in media_filenames
    ]

    suggestions: dict[str, list[str]] = {}
    for src in image_sources:
        filename = _extract_filename(src)
        base_name = _normalise_filename(filename)
        matches = [
            original
            for original, normalised in normalised_media
            if base_name in normalised or normalised in base_name
        ]
        if matches:
            suggestions[filename] = matches[:5]
    return suggestions


def _extract_filename(path: str) -> str:
    """Return the basename component of *path* regardless of separator used."""

    if "/" in path:
        return path.rsplit("/", 1)[-1]
    if "\\" in path:
        return path.rsplit("\\", 1)[-1]
    return path


def _normalise_filename(filename: str) -> str:
    """Return a simplified representation of *filename* for comparison."""

    stem = filename.rsplit(".", 1)[0]
    return stem.lower().replace("_", " ").replace("-", " ")


def _find_media_for_filename(media_dir: Path, filename: str, collection: DeckCollection | None, ttl: float | None = None) -> tuple[str | None, str | None]:
    """Find a safe media filename to serve for *filename*.

    Lookup order (safe, deterministic):
    1. Exact filesystem path (supports subpaths)
    2. Exact key in collection.media_filenames (case-sensitive)
    3. Case-insensitive full-key match in collection.media_filenames (single match only)
    4. Case-insensitive filename match in the media directory itself (single match only)

    Returns a tuple of (stored_filename_to_serve, reason) where reason is one
    of: 'exact', 'map-exact', 'map-ci', 'fs-ci'. If nothing is found returns
    (None, None).
    """
    # Disallow fuzzy lookups for paths that contain directory separators
    if "/" in filename or "\\" in filename:
        return None, None

    # consult per-dir lookup cache first
    if ttl is None:
        effective_ttl = 5.0
    else:
        effective_ttl = float(ttl)

    # Nested helpers for caching - define before first use to avoid
    # UnboundLocalError when referenced earlier in the function.
    def _get_media_names_cached(dirpath: str, ttl: float) -> set[str]:
        """Return a cached set of filenames for dirpath using module-level cache.

        The cache is invalidated if the directory mtime changes. This allows
        tests (which may create files between requests) to see new files
        immediately while still avoiding repeated full directory scans.
        """
        now = time.time()
        key = os.path.abspath(dirpath)
        entry = _MEDIA_NAMES_CACHE.get(key)

        # Try to read current directory mtime; if unavailable, fall back to
        # always-refresh behaviour.
        try:
            dir_mtime = os.path.getmtime(key)
        except OSError:
            dir_mtime = None

        if entry:
            stored_ts, stored_names, stored_mtime = entry[0], entry[1], entry[2]
            if stored_mtime is not None and dir_mtime is not None:
                # If directory mtime changed, force a refresh
                if stored_mtime == dir_mtime and now - stored_ts < ttl:
                    return stored_names
            else:
                # If we can't determine mtimes, fall back to time-based TTL
                if now - stored_ts < ttl:
                    return stored_names

        try:
            names = {n for n in os.listdir(key) if os.path.isfile(os.path.join(key, n))}
        except OSError:
            names = set()

        _MEDIA_NAMES_CACHE[key] = (now, names, dir_mtime)
        return names

    def _get_cached_lookup(dirpath: str, filename: str, ttl: float):
        """Return cached lookup result (stored_name, reason) if fresh and dir
        hasn't changed, else None.
        """
        now = time.time()
        key = (os.path.abspath(dirpath), filename)
        entry = _MEDIA_LOOKUP_CACHE.get(key)
        if not entry:
            return None

        stored_ts, stored_name, stored_reason, stored_dir_mtime = entry
        # If cached entry is too old, drop it
        if now - stored_ts >= ttl:
            return None

        # If directory mtime available, ensure it matches
        try:
            current_mtime = os.path.getmtime(os.path.abspath(dirpath))
        except OSError:
            current_mtime = None

        if stored_dir_mtime is not None and current_mtime is not None:
            if stored_dir_mtime != current_mtime:
                return None

        return stored_name, stored_reason

    def _set_cached_lookup(dirpath: str, filename: str, stored: str | None, reason: str | None):
        try:
            dir_mtime = os.path.getmtime(os.path.abspath(dirpath))
        except OSError:
            dir_mtime = None
        key = (os.path.abspath(dirpath), filename)
        _MEDIA_LOOKUP_CACHE[key] = (time.time(), stored, reason, dir_mtime)

    cached = _get_cached_lookup(str(media_dir), filename, effective_ttl)
    if cached is not None:
        return cached

    # 2/3) Prefer the collection's media map if available (fast, avoids scanning)
    if collection and collection.media_filenames:
        # exact key
        if filename in collection.media_filenames:
            _set_cached_lookup(str(media_dir), filename, collection.media_filenames[filename], "map-exact")
            return collection.media_filenames[filename], "map-exact"

        # case-insensitive full key matches
        filename_lower = filename.lower()
        ci_matches = [stored for key, stored in collection.media_filenames.items() if key.lower() == filename_lower]
        if len(ci_matches) == 1:
            _set_cached_lookup(str(media_dir), filename, ci_matches[0], "map-ci")
            return ci_matches[0], "map-ci"
        if len(ci_matches) > 1:
            # ambiguous map matches; don't guess
            _set_cached_lookup(str(media_dir), filename, None, None)
            return None, None

    # 4) As a last resort, inspect the filesystem for case-insensitive matches.
    # Use a short-lived in-process cache to avoid re-scanning the media
    # directory for every single lookup (reduces overhead when serving many
    # images for a deck). The cache is keyed by absolute directory path and
    # stores a set of filenames along with the timestamp it was read.
    names = _get_media_names_cached(str(media_dir), ttl=effective_ttl)
    ci_matches = [n for n in names if n.lower() == filename.lower()]

    if len(ci_matches) > 1:
        # Ambiguous on disk; never guess
        _set_cached_lookup(str(media_dir), filename, None, None)
        return None, None
    if len(ci_matches) == 1:
        stored_name = ci_matches[0]
        if stored_name == filename:
            _set_cached_lookup(str(media_dir), filename, stored_name, "exact")
            return stored_name, "exact"
        _set_cached_lookup(str(media_dir), filename, stored_name, "fs-ci")
        return stored_name, "fs-ci"

    # Nothing found
    return None, None


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
