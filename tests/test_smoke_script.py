"""Tests for the smoke test script."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from anki_viewer.deck_loader import Card, Deck, DeckCollection
from scripts import smoke_test


def test_parse_args_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["smoke_test.py"])
    args = smoke_test.parse_args()
    assert args.package.endswith("data/MCAT_High_Yield.apkg")


def test_main_reports_success(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    package = tmp_path / "deck.apkg"
    package.write_text("deck")

    deck = Deck(deck_id=1, name="Deck", cards=[
        Card(
            card_id=1,
            note_id=1,
            deck_id=1,
            deck_name="Deck",
            template_ordinal=0,
            question="Q",
            answer="A",
            card_type="basic",
        )
    ])
    collection = DeckCollection(decks={1: deck})

    class FakeResponse:
        def __init__(self, status_code: int, text: str = "", json: dict | None = None):
            self.status_code = status_code
            self._text = text
            self._json = json or {}

        def get_data(self, as_text: bool = False):
            return self._text if as_text else self._text.encode()

        def get_json(self, silent: bool = False):
            return self._json

    class FakeClient:
        def get(self, path: str) -> FakeResponse:
            if path == "/":
                return FakeResponse(200, "cards available across decks")
            if path == "/deck/1":
                return FakeResponse(200, "Deck page")
            if path == "/api/cards":
                return FakeResponse(200, json={"cards": [{"deck_id": 1, "id": 1}]})
            if path == "/deck/1/card/1.json":
                return FakeResponse(200, json={"id": 1})
            return FakeResponse(404)

    class FakeApp:
        def test_client(self):
            class _Ctx:
                def __enter__(self_inner):
                    return FakeClient()

                def __exit__(self_inner, exc_type, exc, tb):
                    return False

            return _Ctx()

    monkeypatch.setattr(smoke_test, "parse_args", lambda: SimpleNamespace(package=str(package)))
    monkeypatch.setattr(smoke_test, "load_collection", lambda *args, **kwargs: collection)
    monkeypatch.setattr(smoke_test, "create_app", lambda: FakeApp())

    exit_code = smoke_test.main()
    assert exit_code == 0


def test_main_handles_missing_package(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys) -> None:
    missing = tmp_path / "missing.apkg"
    monkeypatch.setattr(smoke_test, "parse_args", lambda: SimpleNamespace(package=str(missing)))
    exit_code = smoke_test.main()
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Deck package not found" in captured.err


def test_main_handles_empty_collection(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys) -> None:
    package = tmp_path / "deck.apkg"
    package.write_text("deck")

    collection = DeckCollection(decks={})

    monkeypatch.setattr(smoke_test, "parse_args", lambda: SimpleNamespace(package=str(package)))
    monkeypatch.setattr(smoke_test, "load_collection", lambda *args, **kwargs: collection)

    exit_code = smoke_test.main()
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "did not contain any decks" in captured.err


def test_main_reports_failures(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys) -> None:
    package = tmp_path / "deck.apkg"
    package.write_text("deck")

    deck = Deck(deck_id=1, name="Deck", cards=[
        Card(
            card_id=1,
            note_id=1,
            deck_id=1,
            deck_name="Deck",
            template_ordinal=0,
            question="Q",
            answer="A",
            card_type="basic",
        )
    ])
    collection = DeckCollection(decks={1: deck})

    class FailingResponse:
        def __init__(self, status_code: int):
            self.status_code = status_code

        def get_data(self, as_text: bool = False):
            return "" if as_text else b""

        def get_json(self, silent: bool = False):
            return {}

    class FailingClient:
        def get(self, path: str) -> FailingResponse:
            return FailingResponse(500 if path == "/" else 200)

    class FailingApp:
        def test_client(self):
            class _Ctx:
                def __enter__(self_inner):
                    return FailingClient()

                def __exit__(self_inner, exc_type, exc, tb):
                    return False

            return _Ctx()

    monkeypatch.setattr(smoke_test, "parse_args", lambda: SimpleNamespace(package=str(package)))
    monkeypatch.setattr(smoke_test, "load_collection", lambda *args, **kwargs: collection)
    monkeypatch.setattr(smoke_test, "create_app", lambda: FailingApp())

    exit_code = smoke_test.main()
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "failed the smoke test" in captured.err
