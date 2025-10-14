"""Tests for card type detection utilities."""
from __future__ import annotations

from types import SimpleNamespace

from anki_viewer.card_types import (
    detect_card_type,
    is_cloze_card,
    is_image_card,
    parse_cloze_deletions,
)


def _make_card(
    *,
    question: str = "",
    answer: str = "",
    extra_fields: list[str] | None = None,
    question_revealed: str | None = None,
):
    return SimpleNamespace(
        question=question,
        answer=answer,
        extra_fields=extra_fields or [],
        question_revealed=question_revealed,
    )


def test_parse_cloze_deletions_returns_all_matches() -> None:
    text = "The {{c1::heart}} pumps {{c2::<strong>blood</strong>::Hint}}."
    result = parse_cloze_deletions(text)
    assert result == [
        {"num": 1, "content": "heart"},
        {"num": 2, "content": "<strong>blood</strong>"},
    ]


def test_parse_cloze_deletions_handles_empty_text() -> None:
    assert parse_cloze_deletions("") == []


def test_is_cloze_card_detects_cloze_markers() -> None:
    card = _make_card(question="Name the capital: {{c1::Paris}}")
    assert is_cloze_card(card)


def test_is_cloze_card_handles_absence() -> None:
    card = _make_card(question="Regular question without cloze")
    assert not is_cloze_card(card)


def test_is_image_card_detects_embedded_images() -> None:
    card = _make_card(question='<p><IMG src="figure.png" /></p>')
    assert is_image_card(card)


def test_is_image_card_handles_no_image() -> None:
    card = _make_card(answer="Plain text answer")
    assert not is_image_card(card)


def test_detect_card_type_prioritises_cloze() -> None:
    card = _make_card(question="{{c1::Term}} <img src='img.png'>")
    assert detect_card_type(card) == "cloze"


def test_detect_card_type_considers_extra_fields() -> None:
    card = _make_card(extra_fields=["Supplement {{c2::detail}}"])
    assert detect_card_type(card) == "cloze"


def test_detect_card_type_identifies_image_cards() -> None:
    card = _make_card(answer="<img src='diagram.jpg'>")
    assert detect_card_type(card) == "image"


def test_detect_card_type_detects_image_in_extra_fields() -> None:
    card = _make_card(extra_fields=["<img src='reference.png'>"])
    assert detect_card_type(card) == "image"


def test_detect_card_type_defaults_to_basic() -> None:
    card = _make_card(question="What is the powerhouse of the cell?")
    assert detect_card_type(card) == "basic"

