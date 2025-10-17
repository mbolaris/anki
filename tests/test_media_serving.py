"""Tests for media file serving to prevent regression."""
from pathlib import Path
import pytest
from anki_viewer import create_app


def test_media_directory_is_absolute(tmp_path):
    """Media directory should always be an absolute path."""
    app = create_app(data_dir=tmp_path)
    media_dir = app.config.get("MEDIA_DIRECTORY")

    assert media_dir is not None, "Media directory not configured"
    assert isinstance(media_dir, Path), f"Media directory should be Path, got {type(media_dir)}"
    assert media_dir.is_absolute(), f"Media directory must be absolute, got: {media_dir}"
    assert media_dir.exists(), f"Media directory must exist: {media_dir}"


def test_media_directory_persists_across_reloads(tmp_path):
    """Media directory should be in data_dir/media."""
    app = create_app(data_dir=tmp_path)
    media_dir = app.config.get("MEDIA_DIRECTORY")

    # Should be data_dir/media
    assert media_dir == (tmp_path / "media").resolve()
    # Should not be creating random temp directories
    assert media_dir.parent == tmp_path.resolve()


def test_media_file_serving(tmp_path):
    """Test that media files can be served correctly."""
    app = create_app(data_dir=tmp_path)
    media_dir = app.config.get("MEDIA_DIRECTORY")

    # Create a test image file in the configured media directory
    test_file = media_dir / "test_image.png"
    test_file.write_bytes(b"fake image data")

    client = app.test_client()

    # Test serving the media file
    response = client.get("/media/test_image.png")
    assert response.status_code == 200, f"Media file should be served, got {response.status_code}"
    assert response.data == b"fake image data", "Media file content should match"


def test_media_file_404_for_missing(tmp_path):
    """Test that missing media files return 404."""
    app = create_app(data_dir=tmp_path)
    client = app.test_client()

    response = client.get("/media/nonexistent.png")
    assert response.status_code == 404, f"Missing file should return 404, got {response.status_code}"
