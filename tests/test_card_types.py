"""Unit tests for card type detection helpers."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from anki_viewer.card_types import (
    detect_card_type,
    is_cloze_card,
    is_image_card,
    parse_cloze_deletions,
)
from anki_viewer import _gather_image_sources


def _make_card(
    *,
    question: str = "",
    answer: str = "",
    extra_fields: list[str] | None = None,
    question_revealed: str | None = None,
) -> SimpleNamespace:
    """Return a lightweight card stub for tests."""

    return SimpleNamespace(
        question=question,
        answer=answer,
        extra_fields=extra_fields or [],
        question_revealed=question_revealed,
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        ("The {{c1::heart}} pumps blood.", [{"num": 1, "content": "heart"}]),
        (
            "{{c1::Earth}} and {{c2::Mars}} are planets.",
            [
                {"num": 1, "content": "Earth"},
                {"num": 2, "content": "Mars"},
            ],
        ),
    ],
)
def test_parse_cloze_deletions_various_inputs(text: str, expected: list[dict[str, object]]) -> None:
    """Cloze parser should return all detected deletions."""

    assert parse_cloze_deletions(text) == expected


def test_parse_cloze_deletions_handles_nested_markers() -> None:
    """Nested cloze markers should not cause the parser to crash."""

    result = parse_cloze_deletions("Nested {{c1::outer {{c2::inner}}}} entries.")
    assert result
    assert result[0]["num"] == 1
    assert "outer" in result[0]["content"]
    assert "{{c2" in result[0]["content"]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "No cloze tags here",
        "{{c1:missing braces",
    ],
)
def test_parse_cloze_deletions_handles_empty_and_malformed(text: str) -> None:
    """Parser should ignore malformed patterns and empty text."""

    assert parse_cloze_deletions(text) == []


@pytest.mark.parametrize(
    "card,expected",
    [
        (_make_card(question="Answer {{c1::hidden}}"), True),
        (_make_card(answer="{{c2::Hint}}"), True),
        (_make_card(extra_fields=["{{c1::extra}}"]), True),
        (_make_card(question="plain text"), False),
    ],
)
def test_is_cloze_card_detects_markers(card: SimpleNamespace, expected: bool) -> None:
    """Cloze detection should inspect all card fields."""

    assert is_cloze_card(card) is expected


@pytest.mark.parametrize(
    "card,expected",
    [
        (_make_card(question='<img src="figure.png">'), True),
        (_make_card(answer='<IMG SRC="diagram.jpg">'), True),
        (_make_card(extra_fields=["<p><img src='/media/img.png'></p>"]), True),
        (_make_card(question="plain text"), False),
    ],
)
def test_is_image_card_detects_html_images(card: SimpleNamespace, expected: bool) -> None:
    """Image detection should be case-insensitive and inspect all fields."""

    assert is_image_card(card) is expected


@pytest.mark.parametrize(
    "card,card_type",
    [
        (_make_card(question="{{c1::hidden}}"), "cloze"),
        (_make_card(answer="<img src='diagram.png'>"), "image"),
        (_make_card(question="plain"), "basic"),
        (
            _make_card(question="plain", extra_fields=["<img src='extra.png'>"]),
            "image",
        ),
    ],
)
def test_detect_card_type_prioritises_specific_types(card: SimpleNamespace, card_type: str) -> None:
    """Card type detection should prioritise cloze before image before basic."""

    assert detect_card_type(card) == card_type


def test_detect_card_type_prefers_cloze_over_image() -> None:
    """A card containing both cloze markers and images is classified as cloze."""

    card = _make_card(question="{{c1::Term}} <img src='img.png'>")
    assert detect_card_type(card) == "cloze"


def test_gather_image_sources_returns_unique_paths() -> None:
    """The helper should only return media-prefixed paths."""

    card = _make_card(
        question='<img src="/media/img1.png"><img src="/assets/out.png">',
        answer='<img src="/media/img2.png">',
        extra_fields=["<img src='/media/img1.png'>"],
    )
    assert _gather_image_sources(card, media_url_path="/media") == [
        "/media/img1.png",
        "/media/img2.png",
    ]


def test_gather_image_sources_returns_empty_for_missing_prefix() -> None:
    """Sources outside the configured prefix should be ignored."""

    card = _make_card(question='<img src="/static/img.png">')
    assert _gather_image_sources(card, media_url_path="/media") == []
