from pathlib import Path

from anki_viewer.ratings import RatingsStore


def test_ratings_save_load(tmp_path: Path):
    ds = RatingsStore(tmp_path)
    assert ds.get_all_favorites() == {}

    ds.save(1, {"1": ["favorite", "bad"], "2": {"memorized": True}})
    loaded = ds.load(1)
    assert loaded == {"1": ["bad", "favorite"], "2": ["memorized"]}

    # Only favorites should be returned
    favs = ds.get_all_favorites()
    assert 1 in favs
    assert favs[1] == {"1"}

    # Simulate legacy single-rating format
    ds.get_file(2).write_text('{"3": "favorite", "4": "bad"}', encoding="utf-8")
    loaded_legacy = ds.load(2)
    assert loaded_legacy == {"3": ["favorite"], "4": ["bad"]}
    assert ds.get_all_favorites()[2] == {"3"}


def test_uninitialized_store():
    ds = RatingsStore(None)
    assert ds.load(1) == {}
    ds.save(1, {"1": "favorite"})  # should be a no-op
    assert ds.get_all_favorites() == {}
