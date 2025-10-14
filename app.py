"""Entrypoint for running the Anki deck viewer web server."""
from __future__ import annotations

from anki_viewer import create_app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=False)
else:
    # Allow ``flask run`` to discover the application via ``FLASK_APP=app``.
    app = create_app()
