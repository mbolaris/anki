"""Utilities for determining the type of Anki cards."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Sequence

_CLOZE_PATTERN = re.compile(r"\{\{c(\d+)::(.*?)(?:::(.*?))?\}\}", re.IGNORECASE | re.DOTALL)
_IMAGE_PATTERN = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)


def detect_card_type(card: Any) -> str:
    """Determine the type of an Anki card.

    Parameters
    ----------
    card:
        Any object exposing ``question``, ``answer``, ``extra_fields`` and
        ``question_revealed`` attributes. Only the textual content of these
        attributes is inspected, so lightweight stand-ins such as
        :class:`types.SimpleNamespace` can be used when a full :class:`Card`
        instance is not yet available.

    Returns
    -------
    str
        ``"cloze"`` when the card contains cloze deletions, ``"image"`` when it
        contains embedded images, otherwise ``"basic"``.
    """

    if is_cloze_card(card):
        return "cloze"
    if is_image_card(card):
        return "image"
    return "basic"


def is_cloze_card(card: Any) -> bool:
    """Return ``True`` when the provided card contains cloze deletions."""

    return any(parse_cloze_deletions(text) for text in _iter_card_text(card))


def is_image_card(card: Any) -> bool:
    """Return ``True`` when the provided card contains embedded images."""

    for text in _iter_card_text(card):
        if text and _IMAGE_PATTERN.search(text):
            return True
    return False


def parse_cloze_deletions(text: str) -> List[Dict[str, object]]:
    """Extract cloze deletions from *text*.

    Parameters
    ----------
    text:
        Text that may contain Anki cloze deletion markers.

    Returns
    -------
    list of dict
        A list of dictionaries each containing the cloze ``num`` as an
        integer and the associated ``content`` string. Hints are ignored for
        the purpose of classification but remain part of the returned content.
    """

    deletions: List[Dict[str, object]] = []
    if not text:
        return deletions

    for match in _CLOZE_PATTERN.finditer(text):
        ordinal, content, _hint = match.groups()
        deletions.append({"num": int(ordinal), "content": content})
    return deletions


def _iter_card_text(card: Any) -> Iterable[str]:
    """Yield all textual content stored on *card* relevant to detection."""

    primary_fields: Sequence[str | None] = (
        getattr(card, "question", None),
        getattr(card, "answer", None),
        getattr(card, "question_revealed", None),
    )
    for field in primary_fields:
        if field:
            yield field

    extra_fields = getattr(card, "extra_fields", [])
    for field in extra_fields or []:
        if field:
            yield field


__all__ = [
    "detect_card_type",
    "is_cloze_card",
    "is_image_card",
    "parse_cloze_deletions",
]

