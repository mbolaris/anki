"""Persistent storage for card ratings (favorites, bad, memorized)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, Mapping


VALID_RATINGS = {"favorite", "bad", "memorized"}


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

    def load(self, deck_id: int) -> Dict[str, list[str]]:
        """Load ratings for a specific deck.

        Args:
            deck_id: The deck identifier

        Returns:
            Dictionary mapping card_id (as string) to a list of active ratings.
        """
        if not self.ratings_dir:
            return {}
        file = self.get_file(deck_id)
        if not file.exists():
            return {}
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return self._normalize_ratings_map(data)

    def save(self, deck_id: int, ratings: Mapping[str, Iterable[str]] | Dict[str, str]) -> None:
        """Save ratings for a specific deck.

        Args:
            deck_id: The deck identifier
            ratings: Mapping of card_id (as string) to an iterable of rating labels.
        """
        if not self.ratings_dir:
            return
        normalized = self._normalize_ratings_map(ratings)
        file = self.get_file(deck_id)
        file.write_text(json.dumps(normalized, indent=2, sort_keys=True), encoding="utf-8")

    def get_all_favorites(self) -> Dict[int, set[str]]:
        """Get all favorite cards across all decks.

        Returns:
            Dictionary mapping deck_id to a set of card_ids that are favorited.
        """
        if not self.ratings_dir:
            return {}

        all_favorites: Dict[int, set[str]] = {}
        for ratings_file in self.ratings_dir.glob("deck_*.json"):
            try:
                # Extract deck_id from filename: "deck_123.json" -> 123
                deck_id_str = ratings_file.stem.replace("deck_", "")
                deck_id = int(deck_id_str)

                raw = json.loads(ratings_file.read_text(encoding="utf-8"))
                ratings = self._normalize_ratings_map(raw)
                favorites = {
                    card_id
                    for card_id, labels in ratings.items()
                    if "favorite" in labels
                }
                if favorites:
                    all_favorites[deck_id] = favorites
            except (json.JSONDecodeError, ValueError, OSError):
                continue

        return all_favorites

    def _normalize_ratings_map(
        self, data: Mapping[str, Iterable[str]] | Dict[str, str]
    ) -> Dict[str, list[str]]:
        """Normalize persisted ratings into a canonical dictionary format."""

        normalized: Dict[str, list[str]] = {}
        for card_id, value in data.items():
            labels = sorted(self._normalize_rating_entry(value))
            if labels:
                normalized[str(card_id)] = labels
        return normalized

    @staticmethod
    def _normalize_rating_entry(value: Iterable[str] | Mapping[str, bool] | str) -> set[str]:
        """Normalize a persisted rating entry to a set of valid labels."""

        normalized: set[str] = set()
        if isinstance(value, str):
            if value in VALID_RATINGS:
                normalized.add(value)
        elif isinstance(value, Mapping):
            for label, active in value.items():
                if active and label in VALID_RATINGS:
                    normalized.add(label)
        else:
            try:
                iterator = iter(value)
            except TypeError:
                iterator = None
            if iterator is not None:
                for label in iterator:
                    if isinstance(label, str) and label in VALID_RATINGS:
                        normalized.add(label)
        return normalized
