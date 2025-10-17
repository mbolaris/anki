from pathlib import Path

from anki_viewer import _normalize_media_url_path, _gather_image_sources
from anki_viewer.deck_loader import _sanitize_media_filename, _dedupe_filename


def test_normalize_media_url_path():
    assert _normalize_media_url_path(None) == "/media"
    assert _normalize_media_url_path("") == "/media"
    assert _normalize_media_url_path("assets/") == "/assets"
    assert _normalize_media_url_path("/assets/") == "/assets"
    assert _normalize_media_url_path("media") == "/media"


def test_sanitize_media_filename():
    assert _sanitize_media_filename(' spaced/file?.png') == 'file_.png'
    assert _sanitize_media_filename('') == 'media'
    assert _sanitize_media_filename('normal-name.jpg') == 'normal-name.jpg'


def test_dedupe_filename(tmp_path: Path):
    # Create a file that will collide
    (tmp_path / 'name.png').write_text('x')
    name = _dedupe_filename(tmp_path, 'name.png')
    assert name != 'name.png'
    assert name.startswith('name_')


def test_gather_image_sources():
    sample = type('C', (), {})()
    sample.question = "<img src='/media/a.png'>"
    sample.answer = ""
    sample.question_revealed = None
    assert _gather_image_sources(sample, media_url_path='/media') == ['/media/a.png']
