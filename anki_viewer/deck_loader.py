"""Utilities for loading flashcard content from Anki ``.apkg`` packages."""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List
from urllib.parse import unquote
from zipfile import ZipFile

from .card_types import detect_card_type, parse_cloze_deletions

_FIELD_SEPARATOR = "\x1f"
_IMG_SRC_PATTERN = re.compile(r"(<img[^>]*\bsrc\s*=\s*)(['\"])(.*?)\2", re.IGNORECASE)
_UNQUOTED_IMG_SRC_PATTERN = re.compile(r"(<img[^>]*\bsrc\s*=\s*)([^'\"\s>]+)", re.IGNORECASE)
_CLOZE_PATTERN = re.compile(r"\{\{c(\d+)::(.*?)(?:::([^}]*))?\}\}", re.DOTALL | re.IGNORECASE)


class DeckLoadError(RuntimeError):
    """Raised when the Anki package cannot be processed."""


@dataclass(frozen=True)
class Card:
    """Representation of a single flashcard."""

    card_id: int
    note_id: int
    deck_id: int
    deck_name: str
    template_ordinal: int
    question: str
    answer: str
    card_type: str
    question_revealed: str | None = None
    extra_fields: List[str] = field(default_factory=list)
    raw_question: str | None = None
    cloze_deletions: List[Dict[str, object]] = field(default_factory=list)


@dataclass
class Deck:
    """Grouping of cards that belong to the same deck."""

    deck_id: int
    name: str
    cards: List[Card] = field(default_factory=list)


@dataclass
class DeckCollection:
    """Container for all decks contained in an Anki collection."""

    decks: Dict[int, Deck]
    media_directory: Path | None = None
    media_filenames: Dict[str, str] = field(default_factory=dict)
    media_url_path: str = "/media"

    @property
    def total_cards(self) -> int:
        """Return the total number of cards in the collection.

        Examples
        --------
        >>> deck = Deck(deck_id=1, name='Example', cards=[Card(1, 1, 1, 'Example', 0, '', '', 'basic')])
        >>> DeckCollection(decks={1: deck}).total_cards
        1
        """
        return sum(len(deck.cards) for deck in self.decks.values())

    def media_url_for(self, filename: str) -> str | None:
        """Return the served URL for a media *filename* when available.

        Parameters
        ----------
        filename:
            Name of the media file as referenced inside the Anki collection.

        Returns
        -------
        str | None
            Fully qualified URL for the stored media file or ``None`` when the
            filename is unknown to the collection.

        Examples
        --------
        >>> collection = DeckCollection(decks={}, media_filenames={'img.png': 'img.png'})
        >>> collection.media_url_for('img.png')
        '/media/img.png'
        >>> collection.media_url_for('missing.png') is None
        True
        """

        stored = self.media_filenames.get(filename)
        if not stored:
            return None
        base = self.media_url_path.rstrip("/")
        if not base:
            return stored
        return f"{base}/{stored}"


@dataclass(frozen=True)
class NoteModelTemplate:
    """Description of how a note should be rendered for a specific template."""

    name: str
    question_format: str
    answer_format: str


@dataclass(frozen=True)
class NoteModel:
    """Representation of an Anki note model including its fields and templates."""

    model_id: int
    name: str
    fields: List[str]
    templates: List[NoteModelTemplate]


def load_collection(
    package_path: Path,
    *,
    media_dir: Path | None = None,
    media_url_path: str = "/media",
) -> DeckCollection:
    """Load an Anki package and return the parsed cards grouped by deck.

    Parameters
    ----------
    package_path:
        Path to the ``.apkg`` package that should be parsed.
    media_dir:
        Optional directory into which media files are extracted. When omitted a
        temporary directory is created.
    media_url_path:
        Base URL under which the media files will be served by the Flask app.

    Returns
    -------
    DeckCollection
        Collection containing all decks and cards included in the package.

    Examples
    --------
    >>> from pathlib import Path
    >>> # ``MCAT_High_Yield.apkg`` ships with the repository; loading may fail
    >>> # during documentation builds that lack the data file, so guard access.
    >>> package = Path('data/MCAT_High_Yield.apkg')
    >>> package.exists()
    True
    """

    if not package_path.exists():
        raise DeckLoadError(f"Package not found: {package_path}")

    # Extract the package into a temporary directory. To avoid locking the
    # extracted SQLite file during cleanup on Windows, copy the collection
    # database out to a separate temporary file and open that copy instead.
    tmp_dir = tempfile.mkdtemp(prefix="anki_viewer_")
    media_directory = media_dir or Path(tempfile.mkdtemp(prefix="anki_viewer_media_"))
    _prepare_media_directory(media_directory)
    try:
        _extract_package(package_path, tmp_dir)
        extracted_path = Path(tmp_dir)
        collection_path = _find_collection_file(extracted_path)
        media_map = _read_media(extracted_path, media_directory)

        # Copy the collection DB to a separate temp file outside the
        # extracted directory so we can safely close and remove the
        # extracted directory without the file being locked by SQLite.
        copy_path = Path(tempfile.mktemp(prefix="anki_viewer_collection_"))
        try:
            shutil.copy2(collection_path, copy_path)
            collection = _load_from_sqlite(copy_path, media_map, media_url_path)
        finally:
            try:
                copy_path.unlink()
            except Exception:
                # Best effort cleanup of the copied DB; ignore errors.
                pass

        collection.media_directory = media_directory
        collection.media_filenames = media_map
        collection.media_url_path = media_url_path
        return collection
    finally:
        # Best-effort cleanup of the extracted package directory. On
        # Windows it's possible for other processes (indexers, AV) to hold
        # short-lived locks; ignore cleanup errors here.
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass


def _extract_package(package_path: Path, destination: str) -> None:
    """Extract the ``.apkg`` archive into *destination*.

    Parameters
    ----------
    package_path:
        Path to the source archive.
    destination:
        Directory into which the archive contents should be extracted.
    """
    try:
        with ZipFile(package_path) as archive:
            archive.extractall(destination)
    except Exception as exc:  # pragma: no cover - defensive programming
        raise DeckLoadError(f"Failed to unpack package: {exc}") from exc


def _find_collection_file(extracted_path: Path) -> Path:
    """Locate the main SQLite collection file inside *extracted_path*."""
    for candidate in ("collection.anki21", "collection.anki2"):
        potential = extracted_path / candidate
        if potential.exists():
            return potential
    raise DeckLoadError(f"No collection.anki file found in package at {extracted_path} (checked: collection.anki21, collection.anki2)")


def _read_media(extracted_path: Path, destination: Path) -> Dict[str, str]:
    """Copy media files from the extracted package to *destination*.

    Parameters
    ----------
    extracted_path:
        Directory containing the unpacked Anki package.
    destination:
        Directory where media files should be stored.

    Returns
    -------
    dict[str, str]
        Mapping from the original filename referenced by cards to the stored
        filename within *destination*.

    Examples
    --------
    >>> import tempfile
    >>> tmp = Path(tempfile.mkdtemp())
    >>> _read_media(tmp, tmp)
    {}
    """
    media_file = extracted_path / "media"
    if not media_file.exists():
        return {}

    try:
        manifest = json.loads(media_file.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeckLoadError("Could not parse media manifest") from exc

    media_map: Dict[str, str] = {}
    for key, filename in manifest.items():
        if not filename:
            continue
        file_path = extracted_path / key
        if not file_path.exists():
            continue
        try:
            stored_name = _store_media_file(destination, filename, file_path)
            if not stored_name:
                continue
            # Store with original filename
            media_map[filename] = stored_name
            # Store with lowercase filename for case-insensitive lookup
            filename_lower = filename.lower()
            if filename_lower != filename and filename_lower not in media_map:
                media_map[filename_lower] = stored_name
            # Store stem without extension
            stem = Path(filename).stem
            if stem and stem != filename and stem not in media_map:
                media_map[stem] = stored_name
            # Store lowercase stem
            stem_lower = stem.lower()
            if stem_lower and stem_lower != stem and stem_lower not in media_map:
                media_map[stem_lower] = stored_name
        except OSError:
            continue
    return media_map


def _load_from_sqlite(
    collection_path: Path, media_map: Dict[str, str], media_url_path: str
) -> DeckCollection:
    """Populate a :class:`DeckCollection` by reading the SQLite database.

    Parameters
    ----------
    collection_path:
        Path to the extracted ``collection.anki21`` file.
    media_map:
        Mapping of original media filenames to stored filenames.
    media_url_path:
        Base URL prefix used when inlining media into cards.

    Returns
    -------
    DeckCollection
        Fully populated collection instance ready for rendering in the web UI.

    Examples
    --------
    >>> from pathlib import Path
    >>> _load_from_sqlite(Path('collection.anki21'), {}, '/media')  # doctest: +SKIP
    """
    # Open the SQLite connection and ensure it is explicitly closed when
    # we're done. Note: sqlite3.Connection's context manager commits or
    # rollbacks but does not close the connection, which can leave open
    # connections and trigger ResourceWarning on some platforms. Using
    # a try/finally ensures the connection is closed.
    try:
        conn = sqlite3.connect(str(collection_path))
    except sqlite3.Error as exc:
        raise DeckLoadError(f"Failed to open SQLite database: {exc}") from exc

    try:
        conn.row_factory = sqlite3.Row
        deck_names = _read_deck_names(conn)
        models = _read_models(conn)
        cards = _read_cards(conn, deck_names, models, media_map, media_url_path)
    finally:
        try:
            conn.close()
        except Exception:
            # Best-effort close; ignore errors during cleanup.
            pass

    decks: Dict[int, Deck] = {}
    for card in cards:
        decks.setdefault(card.deck_id, Deck(deck_id=card.deck_id, name=card.deck_name)).cards.append(card)

    for deck in decks.values():
        deck.cards.sort(key=lambda c: (c.template_ordinal, c.card_id))

    return DeckCollection(decks=decks, media_filenames=media_map, media_url_path=media_url_path)


def _read_deck_names(conn: sqlite3.Connection) -> Dict[int, str]:
    """Return a mapping of deck IDs to human readable names.

    Parameters
    ----------
    conn:
        SQLite connection providing access to the ``col`` table.

    Returns
    -------
    dict[int, str]
        Mapping of deck identifier to the display name stored in the package.

    Examples
    --------
    >>> import sqlite3
    >>> conn = sqlite3.connect(':memory:')
    >>> _ = conn.execute('CREATE TABLE col (decks TEXT)')
    >>> _ = conn.execute('INSERT INTO col VALUES ("{}")')
    >>> _read_deck_names(conn)
    {}
    """
    cursor = conn.execute("SELECT decks FROM col LIMIT 1")
    row = cursor.fetchone()
    if row is None:
        raise DeckLoadError("The collection database is missing metadata")

    try:
        decks_json = json.loads(row["decks"])
    except (json.JSONDecodeError, KeyError) as exc:
        raise DeckLoadError("Could not parse deck metadata") from exc

    return {int(deck_id): data.get("name", str(deck_id)) for deck_id, data in decks_json.items()}


def _read_models(conn: sqlite3.Connection) -> Dict[int, NoteModel]:
    """Return a mapping of model identifiers to their definitions."""

    cursor = conn.execute("SELECT models FROM col LIMIT 1")
    row = cursor.fetchone()
    if row is None:
        raise DeckLoadError("The collection database is missing model metadata")

    try:
        models_json = json.loads(row["models"])
    except (json.JSONDecodeError, KeyError) as exc:
        raise DeckLoadError("Could not parse model metadata") from exc

    models: Dict[int, NoteModel] = {}
    for model_id_str, data in models_json.items():
        try:
            model_id = int(model_id_str)
        except (TypeError, ValueError):
            continue

        field_names = [
            field.get("name", f"Field {index + 1}")
            for index, field in enumerate(data.get("flds", []))
        ]
        templates: List[NoteModelTemplate] = []
        for index, template in enumerate(data.get("tmpls", [])):
            templates.append(
                NoteModelTemplate(
                    name=template.get("name", f"Template {index + 1}"),
                    question_format=template.get("qfmt", ""),
                    answer_format=template.get("afmt", ""),
                )
            )

        models[model_id] = NoteModel(
            model_id=model_id,
            name=data.get("name", str(model_id)),
            fields=field_names,
            templates=templates,
        )
    return models


def _read_cards(
    conn: sqlite3.Connection,
    deck_names: Dict[int, str],
    models: Dict[int, NoteModel],
    media_map: Dict[str, str],
    media_url_path: str,
) -> List[Card]:
    """Read all cards from the collection and return a list of :class:`Card`.

    Parameters
    ----------
    conn:
        Open SQLite connection to the collection database.
    deck_names:
        Mapping from deck identifiers to their display names.
    media_map:
        Mapping of original media filenames to stored filenames.
    media_url_path:
        Base URL prefix used for serving media.

    Returns
    -------
    list[Card]
        Fully populated card instances ready for consumption by the web UI.

    Notes
    -----
    All rows are fetched while the SQLite connection is open so that the
    database file can be safely deleted afterwards.
    """
    query = """
        SELECT
            cards.id AS card_id,
            cards.nid AS note_id,
            cards.did AS deck_id,
            cards.ord AS template_ordinal,
            notes.mid AS model_id,
            notes.flds AS note_fields
        FROM cards
        JOIN notes ON notes.id = cards.nid
        ORDER BY cards.did, cards.due, cards.id
    """
    rows = conn.execute(query).fetchall()
    cards: List[Card] = []
    for row in rows:
        fields = row["note_fields"].split(_FIELD_SEPARATOR)
        model_id = int(row["model_id"]) if row["model_id"] is not None else None
        model = models.get(model_id) if model_id is not None else None

        template_index = int(row["template_ordinal"])
        render_template_index = template_index
        field_map = _build_field_map(fields, model.fields if model else [])

        if model and model.templates:
            if not 0 <= render_template_index < len(model.templates):
                render_template_index = render_template_index % len(model.templates)
            template = model.templates[render_template_index]
            question_source = _render_anki_template(template.question_format, field_map)
            answer_context = dict(field_map)
            answer_context.setdefault("FrontSide", question_source)
            answer_source = _render_anki_template(template.answer_format, answer_context)
        else:
            question_source = fields[0] if fields else ""
            answer_source = fields[1] if len(fields) > 1 else ""

        question = _inline_media(question_source, media_map, media_url_path)
        answer = _inline_media(answer_source, media_map, media_url_path)
        extra_values = fields[2:] if len(fields) > 2 else []
        extra = [_inline_media(value, media_map, media_url_path) for value in extra_values]

        card_preview = SimpleNamespace(
            question=question,
            answer=answer,
            extra_fields=extra,
            question_revealed=None,
        )
        card_type = detect_card_type(card_preview)

        original_question = question
        active_cloze_index = None
        cloze_deletions: List[Dict[str, object]] = []
        question_revealed = None
        if card_type == "cloze" and _CLOZE_PATTERN.search(question):
            cloze_deletions = parse_cloze_deletions(question)
            active_cloze_index = template_index + 1
            rendered_question = _render_cloze(
                question,
                reveal=False,
                active_index=active_cloze_index,
            )
            rendered_answer = _render_cloze(
                question,
                reveal=True,
                active_index=active_cloze_index,
            )
            extra_answer = ""
            if answer.strip():
                without_question = answer.replace(original_question, "", 1)
                if without_question != answer:
                    extra_answer = without_question.strip()
            if extra_answer:
                rendered_answer = f"{rendered_answer}{extra_answer}"
            question, answer = rendered_question, rendered_answer
            question_revealed = rendered_answer
        deck_id = int(row["deck_id"])
        deck_name = deck_names.get(deck_id, str(deck_id))
        cards.append(
            Card(
                card_id=int(row["card_id"]),
                note_id=int(row["note_id"]),
                deck_id=deck_id,
                deck_name=deck_name,
                template_ordinal=render_template_index,
                question=question,
                answer=answer,
                card_type=card_type,
                extra_fields=extra,
                question_revealed=question_revealed,
                raw_question=original_question,
                cloze_deletions=cloze_deletions,
            )
        )
    return cards


def _build_field_map(values: List[str], field_names: List[str]) -> Dict[str, str]:
    """Return a mapping of template field names to the provided values."""

    mapping: Dict[str, str] = {}
    for index, value in enumerate(values):
        if index < len(field_names):
            mapping[field_names[index]] = value
        mapping[f"Field{index + 1}"] = value
    return mapping


def _render_anki_template(template: str, fields: Dict[str, str]) -> str:
    """Render a simplified Anki template using the provided *fields*."""

    if not template:
        return ""

    def render_block(text: str, context: Dict[str, str]) -> str:
        result: List[str] = []
        index = 0
        length = len(text)
        while index < length:
            start = text.find("{{", index)
            if start == -1:
                result.append(text[index:])
                break
            result.append(text[index:start])
            end = text.find("}}", start + 2)
            if end == -1:
                result.append(text[start:])
                break
            token = text[start + 2 : end].strip()
            index = end + 2
            if not token:
                continue

            marker = token[0]
            if marker in "#^":
                key = token[1:].strip()
                section_key = _normalize_template_key(key)
                inner, index = _extract_section(text, section_key, index)
                value = _resolve_template_value(key, context)
                should_render = _is_truthy(value)
                if marker == "^":
                    should_render = not should_render
                if should_render:
                    result.append(render_block(inner, context))
            elif marker == "/":
                # Ignore stray closing tags; they are handled when the opening
                # tag is processed.
                continue
            elif marker == "!":
                # Template comments are discarded.
                continue
            else:
                result.append(_resolve_template_value(token, context))
        return "".join(result)

    return render_block(template, dict(fields))


def _extract_section(template: str, name: str, start: int) -> tuple[str, int]:
    """Return the inner content and end index for a section."""

    depth = 1
    index = start
    while index < len(template):
        open_index = template.find("{{", index)
        if open_index == -1:
            return template[start:], len(template)
        close_index = template.find("}}", open_index + 2)
        if close_index == -1:
            return template[start:], len(template)
        token = template[open_index + 2 : close_index].strip()
        index = close_index + 2
        if not token:
            continue

        marker = token[0]
        if marker in "#^":
            nested_name = _normalize_template_key(token[1:])
            if nested_name == name:
                depth += 1
                continue
        elif marker == "/":
            if _normalize_template_key(token[1:]) == name:
                return template[start:open_index], index
    return template[start:], len(template)


def _normalize_template_key(raw: str) -> str:
    """Return the canonical field name for a template token."""

    key = raw.strip()
    if not key:
        return ""
    parts = [part.strip() for part in key.split(":") if part.strip()]
    if not parts:
        return key
    return parts[-1]


def _resolve_template_value(token: str, context: Dict[str, str]) -> str:
    """Resolve the value for a template token from *context*."""

    key = token.strip()
    if not key:
        return ""
    if key in context:
        return context[key]
    normalized = _normalize_template_key(key)
    if normalized and normalized in context:
        return context[normalized]
    return ""


def _is_truthy(value: object) -> bool:
    """Return truthiness compatible with Anki section rendering."""

    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return bool(value)


def _inline_media(html: str, media_map: Dict[str, str], media_url_path: str) -> str:
    """Replace media references in *html* with served URLs.

    Parameters
    ----------
    html:
        HTML text potentially containing ``<img>`` tags.
    media_map:
        Mapping from original filenames to stored filenames.
    media_url_path:
        Base URL prefix used for served media files.

    Returns
    -------
    str
        HTML string with updated ``src`` attributes.

    Examples
    --------
    >>> _inline_media('<img src="foo.png">', {'foo.png': 'foo.png'}, '/media')
    '<img src="/media/foo.png">'
    """
    if not html or not media_map:
        return html

    def resolve_media_reference(source: str) -> str | None:
        """Return the stored filename for *source* when available."""

        normalized = Path(unquote(source)).name
        if not normalized:
            return None

        return _lookup_media_reference(media_map, normalized)

    def replacement(match: re.Match[str]) -> str:
        prefix, quote, src = match.groups()
        data_uri = resolve_media_reference(src)
        if not data_uri:
            return match.group(0)
        url = _build_media_url(data_uri, media_url_path)
        return f"{prefix}{quote}{url}{quote}"

    html = _IMG_SRC_PATTERN.sub(replacement, html)

    def unquoted_replacement(match: re.Match[str]) -> str:
        prefix, src = match.groups()
        data_uri = resolve_media_reference(src)
        if not data_uri:
            return match.group(0)
        url = _build_media_url(data_uri, media_url_path)
        return f"{prefix}{url}"

    return _UNQUOTED_IMG_SRC_PATTERN.sub(unquoted_replacement, html)


def _lookup_media_reference(media_map: Dict[str, str], filename: str) -> str | None:
    """Return the stored media filename for *filename* using relaxed matching."""

    match = media_map.get(filename)
    if match:
        return match

    filename_lower = filename.lower()
    for key, value in media_map.items():
        if key.lower() == filename_lower:
            return value

    stem_lower = Path(filename).stem.lower()
    if not stem_lower:
        return None

    for key, value in media_map.items():
        if Path(key).stem.lower() == stem_lower:
            return value

    return None


def _build_media_url(stored_name: str, media_url_path: str) -> str:
    """Return the public URL for *stored_name*.

    Parameters
    ----------
    stored_name:
        Filename of the stored media asset.
    media_url_path:
        URL prefix under which the media files are served.

    Returns
    -------
    str
        Absolute URL path to the media file.

    Examples
    --------
    >>> _build_media_url('foo.png', '/media')
    '/media/foo.png'
    """
    base = media_url_path.rstrip("/")
    if not base:
        return stored_name
    return f"{base}/{stored_name}"


def _store_media_file(destination: Path, filename: str, source: Path) -> str | None:
    """Copy a media file into *destination* and return the stored filename.

    Parameters
    ----------
    destination:
        Directory where the file should be stored.
    filename:
        Name of the file inside the original package.
    source:
        Path to the file inside the extracted package directory.

    Returns
    -------
    str | None
        Stored filename or ``None`` if the copy failed.

    Examples
    --------
    >>> import tempfile
    >>> dest = Path(tempfile.mkdtemp())
    >>> src = dest / 'sample.txt'
    >>> _ = src.write_text('hi')
    >>> stored = _store_media_file(dest, 'sample.txt', src)
    >>> stored in {'sample.txt', 'sample_1.txt'}
    True
    """
    safe_name = _sanitize_media_filename(filename)
    if not safe_name:
        return None

    unique_name = _dedupe_filename(destination, safe_name)
    try:
        shutil.copy2(source, destination / unique_name)
    except OSError:
        return None
    return unique_name


def _sanitize_media_filename(filename: str) -> str:
    """Return a filesystem-safe filename derived from *filename*.

    Parameters
    ----------
    filename:
        Raw filename from the Anki media manifest.

    Returns
    -------
    str
        Sanitised filename that is safe to store on disk.

    Examples
    --------
    >>> _sanitize_media_filename(' spaced/file?.png')
    'file_.png'
    """
    name = Path(filename).name
    if not name:
        return "media"
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return sanitized or "media"


def _dedupe_filename(destination: Path, filename: str) -> str:
    """Ensure *filename* is unique within *destination* by appending a counter.

    Parameters
    ----------
    destination:
        Directory to check for existing filenames.
    filename:
        Desired filename.

    Returns
    -------
    str
        Original filename or a suffixed version that does not yet exist.

    Examples
    --------
    >>> import tempfile
    >>> dest = Path(tempfile.mkdtemp())
    >>> (dest / 'name.png').write_text('x')
    1
    >>> _dedupe_filename(dest, 'name.png')
    'name_1.png'
    """
    candidate = filename
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 1
    while (destination / candidate).exists():
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def _prepare_media_directory(destination: Path) -> None:
    """Create *destination* and remove leftover files from previous runs.

    Parameters
    ----------
    destination:
        Directory to prepare before media extraction.

    Examples
    --------
    >>> import tempfile
    >>> dest = Path(tempfile.mkdtemp())
    >>> (dest / 'old.txt').write_text('x')
    1
    >>> _prepare_media_directory(dest)
    >>> (dest / 'old.txt').exists()
    False
    """
    destination.mkdir(parents=True, exist_ok=True)
    for entry in destination.iterdir():
        try:
            if entry.is_file() or entry.is_symlink():
                entry.unlink()
            elif entry.is_dir():
                shutil.rmtree(entry)
        except OSError:
            continue


def _render_cloze(html: str, *, reveal: bool, active_index: int | None = None) -> str:
    """Convert Anki cloze deletions to semantic HTML spans.

    Parameters
    ----------
    html:
        Source HTML containing cloze markers.
    reveal:
        When ``True`` the cloze text is revealed, otherwise placeholders are
        rendered.
    active_index:
        Optional cloze number that should be treated as active. When provided,
        only this cloze is revealed on the back of the card and receives the
        hint text on the front.

    Returns
    -------
    str
        HTML with cloze markers replaced by styled ``<span>`` elements.

    Examples
    --------
    >>> _render_cloze("{{c1::Paris}}", reveal=False, active_index=1)
    '<span class="cloze blank" aria-hidden="true"></span>'
    """

    if active_index is not None and active_index < 1:
        active_index = None

    def replacement(match: re.Match[str]) -> str:
        ordinal_raw, content, hint = match.groups()
        ordinal = int(ordinal_raw)
        is_active = active_index is None or ordinal == active_index

        # Keep content as-is - it's already HTML/text from Anki
        # Don't escape to preserve formatting like <font> tags
        content_html = content
        hint_text = (hint or "").strip()

        if reveal:
            if is_active:
                return f'<mark class="cloze reveal">{content_html}</mark>'
            return content_html

        if is_active:
            if hint_text:
                # Show hint text if provided
                return f'<span class="cloze hint">{hint_text}</span>'
            # Show ellipsis for blank cloze
            return '<span class="cloze blank" aria-label="hidden">[…]</span>'

        return content_html

    return _CLOZE_PATTERN.sub(replacement, html)


__all__ = [
    "Card",
    "Deck",
    "DeckCollection",
    "DeckLoadError",
    "load_collection",
]
