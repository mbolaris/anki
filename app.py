"""Entrypoint for running the Anki deck viewer web server."""
from __future__ import annotations

import os

from anki_viewer import create_app


MEDIA_URL_PATH = os.environ.get("ANKI_VIEWER_MEDIA_URL", "/media")

app = create_app(media_url_path=MEDIA_URL_PATH)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
