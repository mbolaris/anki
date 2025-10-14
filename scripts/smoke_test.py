"""Utilities to verify the Anki Deck Viewer loads and serves a deck."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure the repository root is on sys.path when executed as a script.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from anki_viewer import create_app
from anki_viewer.deck_loader import load_collection


DEFAULT_PACKAGE = Path("data/MCAT_High_Yield.apkg")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a basic smoke test against the Flask application using the bundled"
            " MCAT deck or a user-provided package."
        )
    )
    parser.add_argument(
        "package",
        nargs="?",
        default=str(DEFAULT_PACKAGE),
        help=(
            "Path to an .apkg file to load. Defaults to %(default)s if present."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    package_path = Path(args.package).expanduser()

    if not package_path.exists():
        print(f"Deck package not found: {package_path}", file=sys.stderr)
        return 1

    collection = load_collection(package_path)
    try:
        first_deck_id = next(iter(collection.decks))
    except StopIteration:
        print("The collection did not contain any decks.", file=sys.stderr)
        return 1

    app = create_app()

    with app.test_client() as client:
        index_resp = client.get("/")
        deck_resp = client.get(f"/deck/{first_deck_id}")

    ok_index = index_resp.status_code == 200
    ok_deck = deck_resp.status_code == 200

    print(f"Index status: {index_resp.status_code}")
    print(f"Deck status: {deck_resp.status_code}")
    print(
        "Subtitle present:",
        "cards available across" in index_resp.get_data(as_text=True),
    )

    if ok_index and ok_deck:
        return 0

    if not ok_index:
        print("Index endpoint failed the smoke test.", file=sys.stderr)
    if not ok_deck:
        print("Deck endpoint failed the smoke test.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
