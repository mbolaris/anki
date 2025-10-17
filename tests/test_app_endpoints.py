import os
from pathlib import Path

import pytest

from anki_viewer import create_app


def make_app_with_media(tmp_path: Path, create_file_name: str = None):
    # create a data_dir; create_app will create data_dir/media
    data_dir = tmp_path
    app = create_app(apkg_path=None, media_url_path="/media", data_dir=data_dir)
    media_dir = data_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    if create_file_name:
        (media_dir / create_file_name).write_text("x")
    return app, media_dir


def test_health_endpoint():
    app, _ = make_app_with_media(Path("./tmp_test_no_media"))
    client = app.test_client()
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json == {"status": "ok"}


def test_media_exact_and_ci_fallback(tmp_path: Path):
    # Exact file
    app, media_dir = make_app_with_media(tmp_path, create_file_name="img.png")
    client = app.test_client()
    r = client.get("/media/img.png")
    assert r.status_code == 200
    assert "X-Media-Fallback" not in r.headers

    # Case-insensitive file name (create different-cased file)
    (media_dir / "IMG2.PNG").write_text("y")
    # Request lower-case name
    r2 = client.get("/media/img2.png")
    assert r2.status_code == 200
    # header should indicate a fallback was used
    assert r2.headers.get("X-Media-Fallback") in ("fs-ci", "map-ci", "map-exact")


def test_dev_media_matches(tmp_path: Path, monkeypatch):
    app, media_dir = make_app_with_media(tmp_path)
    # create a couple of files
    (media_dir / "Glycine.png").write_text("x")
    (media_dir / "glycine.png").write_text("y")

    # enable dev endpoint via env
    monkeypatch.setenv("ANKI_VIEWER_DEV", "1")
    client = app.test_client()
    r = client.get("/dev/media-matches/Glycine.png")
    assert r.status_code == 200
    data = r.json
    assert data["requested"] == "Glycine.png"
    assert isinstance(data.get("matches"), list)


# Ensure tests are robust across case-sensitive vs case-insensitive filesystems
@pytest.mark.parametrize("names", [("a.png", "A.png"), ("unique.png",)])
def test_ambiguous(tmp_path: Path, names):
    app, media_dir = make_app_with_media(tmp_path)
    for n in names:
        (media_dir / n).write_text("z")
    client = app.test_client()
    r = client.get("/media/a.png")
    # Either 404 on ambiguous or 200 if FS collapsed names; assert one of these
    assert r.status_code in (200, 404)
