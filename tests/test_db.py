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


def test_alternate_titles_round_trip(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    db.replace_anilist_list(
        [
            AniListStatus(
                anilist_id=1, status="CURRENT", progress=3, score=0.0,
                title="Re:ZERO -Starting Life in Another World- Season 3",
                cover_url=None,
                # Commas are common inside anime titles, which is why these
                # are not stored comma-separated the way genres are.
                titles=("Re:Zero kara Hajimeru Isekai Seikatsu 3rd Season", "Re:Zero, Season 3"),
            )
        ]
    )

    stored = db.get_anilist_status(1)

    assert stored.titles == (
        "Re:Zero kara Hajimeru Isekai Seikatsu 3rd Season",
        "Re:Zero, Season 3",
    )
    db.close()


def test_a_failed_source_lookup_is_not_remembered(tmp_path: Path) -> None:
    # A miss means the source was down, the title was one the matcher couldn't
    # handle, or the show wasn't listed yet -- all of which stop being true.
    # Caching them meant a show that failed once failed forever.
    db = Database(tmp_path / "test.db")

    db.save_anidb_mapping(163134, None)

    assert db.get_anidb_mapping(163134) is None
    assert db._conn.execute("SELECT COUNT(*) FROM anidb_map").fetchone()[0] == 0
    db.close()


def test_existing_cached_failures_are_dropped_on_open(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    db._conn.execute(
        "INSERT INTO anidb_map (anilist_id, slug_id) VALUES (163134, NULL), (226, 'elfen-lied-1')"
    )
    db._conn.commit()
    db.close()

    reopened = Database(db_path)

    assert reopened.get_anidb_mapping(163134) is None
    assert reopened._conn.execute("SELECT COUNT(*) FROM anidb_map").fetchone()[0] == 1
    reopened.close()


def test_set_anilist_status_adds_moves_and_removes(tmp_path: Path) -> None:
    """The app changes the list itself now (plan-to-watch), so the mirror has
    to be able to follow without waiting for a full re-sync."""
    db = Database(tmp_path / "test.db")

    db.set_anilist_status(123, "PLANNING")
    added = db.get_anilist_status(123)
    assert added is not None and added.status == "PLANNING"

    db.set_anilist_status(123, "CURRENT")
    assert db.get_anilist_status(123).status == "CURRENT"

    db.set_anilist_status(123, "")
    assert db.get_anilist_status(123) is None
    db.close()


def test_set_anilist_status_keeps_the_rest_of_a_mirrored_row(tmp_path: Path) -> None:
    """Moving an entry to Planning must not blank the title and artwork the
    home rows are drawn from."""
    db = Database(tmp_path / "test.db")
    db.replace_anilist_list([
        AniListStatus(anilist_id=7, status="CURRENT", progress=4, score=8.0,
                      title="Shown", cover_url="cover.jpg", titles=("Shown", "Alt")),
    ])

    db.set_anilist_status(7, "PLANNING")

    entry = db.get_anilist_status(7)
    assert entry.status == "PLANNING"
    assert entry.title == "Shown"
    assert entry.progress == 4
    assert entry.titles == ("Shown", "Alt")
    db.close()
