"""Entrypoint for running the Anki deck viewer web server."""
from __future__ import annotations

import os
from pathlib import Path

from anki_viewer import create_app


def _optional_path(raw: str | None) -> Path | None:
    return Path(raw) if raw else None


# Configuration from environment variables
MEDIA_URL_PATH = os.environ.get("ANKI_VIEWER_MEDIA_URL", "/media")
DECK_PATH_STR = os.environ.get("ANKI_DECK_PATH")
DATA_DIR_STR = os.environ.get("ANKI_DATA_DIR", "data")

# Convert to Path objects
apkg_path = _optional_path(DECK_PATH_STR)
data_dir = _optional_path(DATA_DIR_STR)

# Create the Flask application
app = create_app(apkg_path=apkg_path, media_url_path=MEDIA_URL_PATH, data_dir=data_dir)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
