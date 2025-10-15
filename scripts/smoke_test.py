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
    """Parse command line arguments for the smoke test script.

    Returns
    -------
    argparse.Namespace
        Namespace containing the ``package`` argument.

    Examples
    --------
    >>> parse_args().package
    'data/MCAT_High_Yield.apkg'
    """
    parser = argparse.ArgumentParser(
        description=(
            "Run a basic smoke test against the Flask application using the bundled"
            " MCAT deck or a user-provided package."
        )
    )
    parser.add_argument(
        "package",
        nargs="?",
        # Use POSIX-style path string for the default so tests that compare
        # the string with forward slashes behave consistently across OSes.
        default=str(DEFAULT_PACKAGE.as_posix()),
        help=(
            "Path to an .apkg file to load. Defaults to %(default)s if present."
        ),
    )
    return parser.parse_args()


def main() -> int:
    """Execute the smoke test.

    Returns
    -------
    int
        Exit status code that mirrors the health of the application.

    Examples
    --------
    >>> main()  # doctest: +SKIP
    0
    """
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
        responses = {
            "index": client.get("/"),
            "deck": client.get(f"/deck/{first_deck_id}"),
        }

        card_list = client.get("/api/cards")
        responses["api_cards"] = card_list

        if card_list.status_code == 200:
            cards_json = card_list.get_json(silent=True) or {}
            for card in cards_json.get("cards", [])[:3]:
                deck_id = card.get("deck_id")
                card_id = card.get("id")
                key = f"card_{deck_id}_{card_id}"
                responses[key] = client.get(f"/deck/{deck_id}/card/{card_id}.json")

    for name, resp in responses.items():
        print(f"{name} status: {resp.status_code}")

    failures = [name for name, resp in responses.items() if resp.status_code != 200]

    if not failures:
        return 0

    for name in failures:
        print(f"Endpoint {name!r} failed the smoke test.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
