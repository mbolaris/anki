from pathlib import Path

from anki_viewer.ratings import RatingsStore


def test_ratings_save_load(tmp_path: Path):
    ds = RatingsStore(tmp_path)
    assert ds.get_all_favorites() == {}

    ds.save(1, {"1": "favorite", "2": "bad"})
    loaded = ds.load(1)
    assert loaded == {"1": "favorite", "2": "bad"}

    # Only favorites should be returned
    favs = ds.get_all_favorites()
    assert 1 in favs
    assert favs[1] == {"1": "favorite"}


def test_uninitialized_store():
    ds = RatingsStore(None)
    assert ds.load(1) == {}
    ds.save(1, {"1": "favorite"})  # should be a no-op
    assert ds.get_all_favorites() == {}
