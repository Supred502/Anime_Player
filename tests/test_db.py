from pathlib import Path

from animeplayer.storage.db import AniListStatus, Database


def test_save_and_read_progress(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")

    db.save_progress(
        anime_slug_id="hunter-x-hunter-2293",
        anime_title="Hunter x Hunter",
        poster_url="https://example.com/poster.jpg",
        episode_id=50877,
        episode_number=1,
        position_seconds=120.5,
        duration_seconds=1400,
    )

    entry = db.get_progress("hunter-x-hunter-2293")
    assert entry is not None
    assert entry.episode_number == 1
    assert entry.position_seconds == 120.5

    db.close()


def test_save_progress_upserts_same_anime(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")

    db.save_progress("slug-1", "Title", None, episode_id=1, episode_number=1, position_seconds=0, duration_seconds=0)
    db.save_progress("slug-1", "Title", None, episode_id=2, episode_number=2, position_seconds=30, duration_seconds=0)

    entries = db.continue_watching()
    assert len(entries) == 1
    assert entries[0].episode_number == 2

    db.close()


def test_continue_watching_orders_most_recent_first(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")

    db.save_progress("slug-a", "A", None, episode_id=1, episode_number=1, position_seconds=0, duration_seconds=0)
    db.save_progress("slug-b", "B", None, episode_id=2, episode_number=1, position_seconds=0, duration_seconds=0)

    entries = db.continue_watching()
    assert [e.anime_slug_id for e in entries] == ["slug-b", "slug-a"]

    db.close()


def test_anilist_status_round_trips_genres_and_popularity(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")

    db.replace_anilist_list(
        [
            AniListStatus(
                anilist_id=1, status="PLANNING", progress=0, score=0.0, title="A",
                cover_url=None, genres=("Action", "Adventure"), popularity=5000,
            )
        ]
    )

    entry = db.get_anilist_status(1)
    assert entry is not None
    assert entry.genres == ("Action", "Adventure")
    assert entry.popularity == 5000

    by_status = db.get_anilist_by_status("PLANNING")
    assert by_status[0].genres == ("Action", "Adventure")

    db.close()


def test_upsert_anilist_status_preserves_genres(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")

    db.upsert_anilist_status(
        AniListStatus(
            anilist_id=1, status="CURRENT", progress=1, score=0.0, title="A",
            cover_url=None, genres=("Comedy",), popularity=100,
        )
    )
    db.upsert_anilist_status(
        AniListStatus(
            anilist_id=1, status="CURRENT", progress=2, score=0.0, title="A",
            cover_url=None, genres=("Comedy",), popularity=100,
        )
    )

    entry = db.get_anilist_status(1)
    assert entry.progress == 2
    assert entry.genres == ("Comedy",)

    db.close()
