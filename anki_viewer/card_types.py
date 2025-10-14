"""Utilities for determining the type of Anki cards.

Each helper in this module focuses on a single responsibility so that the
surrounding code remains easy to test. The functions are pure and only inspect
the data available on the card-like objects that are passed to them.
"""
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

    Examples
    --------
    >>> from types import SimpleNamespace
    >>> card = SimpleNamespace(question="{{c1::Paris}} is the capital", answer="")
    >>> detect_card_type(card)
    'cloze'
    >>> detect_card_type(SimpleNamespace(question="<img src='x.png'>", answer=""))
    'image'
    """

    if is_cloze_card(card):
        return "cloze"
    if is_image_card(card):
        return "image"
    return "basic"


def is_cloze_card(card: Any) -> bool:
    """Return ``True`` when the provided card contains cloze deletions.

    Parameters
    ----------
    card:
        Card-like object to inspect. Only textual fields are examined.

    Returns
    -------
    bool
        ``True`` if any of the card fields contain cloze markers such as
        ``{{c1::...}}``.

    Examples
    --------
    >>> from types import SimpleNamespace
    >>> is_cloze_card(SimpleNamespace(question="{{c1::x}}", answer=""))
    True
    >>> is_cloze_card(SimpleNamespace(question="Plain", answer=""))
    False
    """

    return any(parse_cloze_deletions(text) for text in _iter_card_text(card))


def is_image_card(card: Any) -> bool:
    """Return ``True`` when the provided card contains embedded images.

    Parameters
    ----------
    card:
        Card-like object to inspect.

    Returns
    -------
    bool
        ``True`` if an ``<img>`` tag with a source attribute is present in any
        of the card fields.

    Examples
    --------
    >>> from types import SimpleNamespace
    >>> is_image_card(SimpleNamespace(question="<img src='img.png'>", answer=""))
    True
    >>> is_image_card(SimpleNamespace(question="no image", answer=""))
    False
    """

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

    Examples
    --------
    >>> parse_cloze_deletions("{{c1::heart}} pumps {{c2::blood::hint}}")
    [{'num': 1, 'content': 'heart'}, {'num': 2, 'content': 'blood'}]
    >>> parse_cloze_deletions("No clozes here")
    []
    """

    deletions: List[Dict[str, object]] = []
    if not text:
        return deletions

    for match in _CLOZE_PATTERN.finditer(text):
        ordinal, content, _hint = match.groups()
        deletions.append({"num": int(ordinal), "content": content})
    return deletions


def _iter_card_text(card: Any) -> Iterable[str]:
    """Yield all textual content stored on *card* relevant to detection.

    Parameters
    ----------
    card:
        Card-like object to inspect.

    Yields
    ------
    str
        Each non-empty text field stored on the card in the order they are
        commonly processed (question, answer, revealed question, extra fields).

    Examples
    --------
    >>> from types import SimpleNamespace
    >>> list(_iter_card_text(SimpleNamespace(question="Q", answer="A", extra_fields=["E"])))
    ['Q', 'A', 'E']
    """

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

