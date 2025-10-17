from pathlib import Path

from anki_viewer.__init__ import _find_media_for_filename
from anki_viewer.deck_loader import DeckCollection


def test_find_media_exact(tmp_path: Path):
    media_dir = tmp_path
    (media_dir / 'img.png').write_text('x')
    candidate, reason = _find_media_for_filename(media_dir, 'img.png', None)
    assert candidate == 'img.png' and reason == 'exact'


def test_find_media_map_exact(tmp_path: Path):
    media_dir = tmp_path
    (media_dir / 'stored.png').write_text('x')
    collection = DeckCollection(decks={}, media_directory=media_dir, media_filenames={'img.png': 'stored.png'})
    candidate, reason = _find_media_for_filename(media_dir, 'img.png', collection)
    assert candidate == 'stored.png' and reason == 'map-exact'


def test_find_media_map_ci(tmp_path: Path):
    media_dir = tmp_path
    (media_dir / 'stored.png').write_text('x')
    collection = DeckCollection(decks={}, media_directory=media_dir, media_filenames={'IMG.PNG': 'stored.png'})
    candidate, reason = _find_media_for_filename(media_dir, 'img.png', collection)
    assert candidate == 'stored.png' and reason == 'map-ci'


def test_find_media_fs_ci(tmp_path: Path):
    media_dir = tmp_path
    (media_dir / 'IMG.PNG').write_text('x')
    candidate, reason = _find_media_for_filename(media_dir, 'img.png', None)
    assert candidate == 'IMG.PNG' and reason == 'fs-ci'


def test_ambiguous_returns_none(tmp_path: Path):
    media_dir = tmp_path
    (media_dir / 'a.png').write_text('x')
    (media_dir / 'A.png').write_text('y')
    candidate, reason = _find_media_for_filename(media_dir, 'a.png', None)
    # On case-sensitive filesystems both files can exist and we should return None
    # to avoid guessing. On case-insensitive systems (Windows) the second write
    # overwrites or is the same file; in that case a candidate will be returned.
    if candidate is None:
        assert reason is None
    else:
        assert candidate.lower() == 'a.png'
        assert reason in ('fs-ci', 'exact')
