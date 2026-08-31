from pathlib import Path
from unittest.mock import MagicMock

from animeplayer.anilist import matcher
from animeplayer.anilist.client import MediaSummary
from animeplayer.sources.anidb_app import SearchResult
from animeplayer.storage.db import Database


def _summary(media_id: int, title: str, **overrides) -> MediaSummary:
    defaults = dict(
        id=media_id, id_mal=None, title=title, titles=(title,), cover_url=None, average_score=None,
        popularity=0, genres=(), format="TV", episodes=None, description=None,
    )
    defaults.update(overrides)
    return MediaSummary(**defaults)


def test_resolve_media_id_picks_best_match(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    client = MagicMock()
    client.search_media.return_value = [
        _summary(2293, "Hunter x Hunter"),
        _summary(2294, "Hunter x Hunter (2011)"),
    ]

    media_id = matcher.resolve_media_id("Hunter x Hunter", client, db)

    assert media_id == 2293
    db.close()


def test_resolve_media_id_caches_result(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    client = MagicMock()
    client.search_media.return_value = [_summary(2293, "Hunter x Hunter")]

    first = matcher.resolve_media_id("Hunter x Hunter", client, db)
    second = matcher.resolve_media_id("Hunter x Hunter", client, db)

    assert first == second == 2293
    client.search_media.assert_called_once()
    db.close()


def test_resolve_media_id_returns_none_when_no_good_match(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    client = MagicMock()
    client.search_media.return_value = [_summary(999, "Completely Unrelated Show")]

    media_id = matcher.resolve_media_id("Hunter x Hunter", client, db)

    assert media_id is None
    assert db.has_title_mapping("Hunter x Hunter")
    db.close()


def test_resolve_media_id_no_candidates(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    client = MagicMock()
    client.search_media.return_value = []

    media_id = matcher.resolve_media_id("Some Obscure Anime", client, db)

    assert media_id is None
    client.search_media.assert_called_once()
    db.close()


def test_resolve_media_summary_picks_best_match(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    client = MagicMock()
    client.search_media.return_value = [
        _summary(2293, "Hunter x Hunter", average_score=90),
        _summary(2294, "Hunter x Hunter (2011)", average_score=85),
    ]

    summary = matcher.resolve_media_summary("Hunter x Hunter", client, db)

    assert summary.id == 2293
    assert summary.average_score == 90
    db.close()


def test_resolve_media_summary_uses_cached_id(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    client = MagicMock()
    client.search_media.return_value = [_summary(2293, "Hunter x Hunter")]
    client.get_media_by_id.return_value = _summary(2293, "Hunter x Hunter", average_score=90)

    matcher.resolve_media_summary("Hunter x Hunter", client, db)  # populates the cache
    summary = matcher.resolve_media_summary("Hunter x Hunter", client, db)  # cache hit

    client.search_media.assert_called_once()
    client.get_media_by_id.assert_called_once_with(2293)
    assert summary.average_score == 90
    db.close()


def test_resolve_media_summary_returns_none_when_no_good_match(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    client = MagicMock()
    client.search_media.return_value = [_summary(999, "Completely Unrelated Show")]

    summary = matcher.resolve_media_summary("Hunter x Hunter", client, db)

    assert summary is None
    db.close()


def _result(slug_id: str, title: str) -> SearchResult:
    return SearchResult(
        slug_id=slug_id, numeric_id=slug_id.rsplit("-", 1)[-1], title=title,
        poster_url="", kind="TV", rating="8.0",
    )


def test_best_anidb_result_picks_closest_title() -> None:
    results = [
        _result("hunter-x-hunter-2293", "Hunter x Hunter"),
        _result("hunter-x-hunter-2011-2294", "Hunter x Hunter (2011)"),
    ]

    best = matcher.best_anidb_result("Hunter x Hunter", results)

    assert best.slug_id == "hunter-x-hunter-2293"


def test_best_anidb_result_returns_none_when_no_good_match() -> None:
    results = [_result("something-else-1", "Completely Unrelated Show")]

    best = matcher.best_anidb_result("Hunter x Hunter", results)

    assert best is None
