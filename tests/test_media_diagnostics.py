import os
from pathlib import Path

from anki_viewer import create_app


def test_media_lookup_time_header(tmp_path: Path):
    app = create_app(data_dir=tmp_path)
    media_dir = app.config.get("MEDIA_DIRECTORY")
    (media_dir / "diag.png").write_bytes(b"PNG")

    client = app.test_client()
    resp = client.get("/media/diag.png")
    assert resp.status_code == 200
    # header should exist and be an integer string
    assert "X-Media-Lookup-Time-ms" in resp.headers
    val = resp.headers.get("X-Media-Lookup-Time-ms")
    assert val.isdigit()


def test_dev_media_stats_enabled_by_env(tmp_path: Path, monkeypatch):
    # Ensure the dev endpoint is disabled by default
    app = create_app(data_dir=tmp_path)
    client = app.test_client()
    r = client.get("/dev/media-stats")
    assert r.status_code == 404

    # Enable dev endpoints via env and check stats payload
    monkeypatch.setenv("ANKI_VIEWER_DEV", "1")
    app = create_app(data_dir=tmp_path)
    media_dir = app.config.get("MEDIA_DIRECTORY")
    (media_dir / "s1.png").write_bytes(b"1")
    client = app.test_client()

    # trigger a media lookup
    client.get("/media/s1.png")

    r = client.get("/dev/media-stats")
    assert r.status_code == 200
    data = r.get_json()
    assert "count" in data and data["count"] >= 1
    assert "avg_lookup_time_ms" in data
