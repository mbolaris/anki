"""Persistent storage for card ratings (favorites, bad, unmarked)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


class RatingsStore:
    """Manages card ratings persistence in JSON files."""

    def __init__(self, data_dir: Path | None):
        """Initialize the ratings store.

        Args:
            data_dir: Directory where .ratings/ subdirectory will be created
        """
        self.data_dir = data_dir
        self.ratings_dir = None
        if data_dir:
            self.ratings_dir = data_dir / ".ratings"
            # Ensure parent directories are created as well and ignore if already exists
            self.ratings_dir.mkdir(parents=True, exist_ok=True)

    def get_file(self, deck_id: int) -> Path:
        """Get the ratings file path for a specific deck.

        Args:
            deck_id: The deck identifier

        Returns:
            Path to the JSON file for this deck's ratings
        """
        if not self.ratings_dir:
            raise RuntimeError("Ratings store not initialized with data directory")
        return self.ratings_dir / f"deck_{deck_id}.json"

    def load(self, deck_id: int) -> Dict[str, str]:
        """Load ratings for a specific deck.

        Args:
            deck_id: The deck identifier

        Returns:
            Dictionary mapping card_id (as string) to rating ("favorite" or "bad")
        """
        if not self.ratings_dir:
            return {}
        file = self.get_file(deck_id)
        if not file.exists():
            return {}
        try:
            return json.loads(file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self, deck_id: int, ratings: Dict[str, str]) -> None:
        """Save ratings for a specific deck.

        Args:
            deck_id: The deck identifier
            ratings: Dictionary mapping card_id (as string) to rating
        """
        if not self.ratings_dir:
            return
        file = self.get_file(deck_id)
        file.write_text(json.dumps(ratings, indent=2, sort_keys=True), encoding="utf-8")

    def get_all_favorites(self) -> Dict[int, Dict[str, str]]:
        """Get all favorite cards across all decks.

        Returns:
            Dictionary mapping deck_id to dict of card_id -> rating (favorites only)
        """
        if not self.ratings_dir:
            return {}

        all_favorites = {}
        for ratings_file in self.ratings_dir.glob("deck_*.json"):
            try:
                # Extract deck_id from filename: "deck_123.json" -> 123
                deck_id_str = ratings_file.stem.replace("deck_", "")
                deck_id = int(deck_id_str)

                ratings = json.loads(ratings_file.read_text(encoding="utf-8"))
                # Filter to only favorites
                favorites = {
                    card_id: rating
                    for card_id, rating in ratings.items()
                    if rating == "favorite"
                }
                if favorites:
                    all_favorites[deck_id] = favorites
            except (json.JSONDecodeError, ValueError, OSError):
                continue

        return all_favorites
