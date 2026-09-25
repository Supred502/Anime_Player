import datetime as dt

from animeplayer.alerts import find_new_episodes
from animeplayer.anilist.client import AiringState, MediaSummary
from animeplayer.stats import compute_watch_stats
from animeplayer.storage.db import Database


def _media(media_id: int, title: str = "Show") -> MediaSummary:
    return MediaSummary(
        id=media_id, id_mal=None, title=title, titles=(title,), cover_url=None,
        banner_url=None, country="JP", average_score=None, popularity=0, genres=(),
        format="TV", episodes=None, description=None,
    )


def _airing(media_id: int, latest: int, next_episode: int | None = None) -> AiringState:
    return AiringState(media=_media(media_id), latest_aired=latest,
                       next_episode=next_episode, next_airing_at=None)


# -- new-episode alerts ------------------------------------------------------

def test_a_show_seen_for_the_first_time_is_recorded_but_not_announced() -> None:
    """Otherwise turning alerts on would fire one notification per show."""
    waiting, announce, updates = find_new_episodes([_airing(1, 5, 6)], {1: 3}, seen={})
    assert [n.state.media.id for n in waiting] == [1]
    assert announce == []
    assert updates == {1: 5}


def test_an_episode_aired_since_the_last_check_is_announced_once() -> None:
    _, announce, updates = find_new_episodes([_airing(1, 6, 7)], {1: 5}, seen={1: 5})
    assert [n.state.latest_aired for n in announce] == [6]
    assert updates == {1: 6}
    # Next check, nothing new aired: no second notification.
    _, again, _ = find_new_episodes([_airing(1, 6, 7)], {1: 5}, seen={1: 6})
    assert again == []


def test_nothing_is_announced_when_already_watched() -> None:
    """Watched it on another device the moment it aired: AniList progress
    already covers it, so there's nothing to tell the user."""
    waiting, announce, _ = find_new_episodes([_airing(1, 6, 7)], {1: 6}, seen={1: 5})
    assert waiting == [] and announce == []


def test_a_finished_backlog_is_not_new_episodes_but_a_finale_is_announced() -> None:
    # Stopped halfway through a show that ended years ago: not "new".
    waiting, announce, _ = find_new_episodes([_airing(1, 24, None)], {1: 10}, seen={1: 24})
    assert waiting == [] and announce == []
    # The last episode aired since the last check: announced, even though
    # the show is no longer airing.
    _, announce, _ = find_new_episodes([_airing(2, 12, None)], {2: 11}, seen={2: 11})
    assert [n.state.media.id for n in announce] == [2]


# -- watch statistics ----------------------------------------------------------

def _stamp(day: str, hour: int) -> float:
    return dt.datetime.fromisoformat(f"{day}T{hour:02d}:00:00").timestamp()


def test_stats_add_up_time_episodes_and_genres() -> None:
    watch_time = [
        ("2026-09-24", "frieren-1", "Frieren", 3600.0),
        ("2026-09-25", "frieren-1", "Frieren", 1800.0),
        ("2026-09-25", "dorohedoro-2", "Dorohedoro", 1800.0),
    ]
    events = [
        ("frieren-1", "Frieren", 1.0, _stamp("2026-09-24", 22)),
        ("frieren-1", "Frieren", 2.0, _stamp("2026-09-25", 22)),
        ("dorohedoro-2", "Dorohedoro", 1.0, _stamp("2026-09-25", 9)),
    ]
    meta = {
        "frieren-1": ("Frieren", 1, ["Adventure", "Fantasy"]),
        "dorohedoro-2": ("Dorohedoro", 2, ["Action", "Fantasy"]),
    }
    stats = compute_watch_stats(watch_time, events, meta, today="2026-09-25")

    assert stats["total_hours"] == 2.0
    assert stats["total_episodes"] == 3
    assert stats["show_count"] == 2
    assert stats["top_shows"][0]["title"] == "Frieren"
    assert stats["top_shows"][0]["episodes"] == 2
    # Fantasy covers both shows, so it gets all the time.
    assert stats["top_genres"][0] == {"genre": "Fantasy", "hours": 2.0, "share": 1.0}
    assert stats["busiest_hour"] == 22
    assert stats["streak_days"] == 2


def test_the_chart_keeps_empty_days() -> None:
    """Leaving out days with nothing would draw a steadier habit than it is."""
    stats = compute_watch_stats([("2026-09-20", "a", "A", 600.0)], [], {}, today="2026-09-25")
    assert len(stats["last_days"]) == 14
    assert stats["last_days"][-1]["date"] == "2026-09-25"
    assert sum(1 for d in stats["last_days"] if d["minutes"] > 0) == 1


def test_a_streak_survives_the_morning_before_todays_episode() -> None:
    watch_time = [("2026-09-23", "a", "A", 600.0), ("2026-09-24", "a", "A", 600.0)]
    assert compute_watch_stats(watch_time, [], {}, today="2026-09-25")["streak_days"] == 2
    # ...but a couple of minutes doesn't count as a day watched.
    short = [("2026-09-24", "a", "A", 60.0)]
    assert compute_watch_stats(short, [], {}, today="2026-09-25")["streak_days"] == 0


def test_nothing_recorded_is_all_zeros_not_an_error() -> None:
    stats = compute_watch_stats([], [], {}, today="2026-09-25")
    assert stats["total_hours"] == 0 and stats["busiest_hour"] == -1


# -- storage -------------------------------------------------------------------

def test_watch_time_accumulates_per_day_and_show(tmp_path) -> None:
    db = Database(tmp_path / "t.db")
    db.add_watch_time("2026-09-25", "a", "A", 5)
    db.add_watch_time("2026-09-25", "a", "A", 5)
    db.add_watch_time("2026-09-26", "a", "A", 5)
    assert db.watch_time_rows() == [("2026-09-25", "a", "A", 10.0), ("2026-09-26", "a", "A", 5.0)]


def test_airing_seen_only_moves_forward(tmp_path) -> None:
    db = Database(tmp_path / "t.db")
    db.set_airing_seen(1, 5)
    db.set_airing_seen(1, 3)
    assert db.airing_seen() == {1: 5}


def test_auto_download_remembers_the_audio(tmp_path) -> None:
    db = Database(tmp_path / "t.db")
    assert db.get_auto_download("one-piece-100") is None
    db.set_auto_download("one-piece-100", True, dub=True)
    assert db.get_auto_download("one-piece-100") is True
    db.set_auto_download("one-piece-100", False)
    assert db.get_auto_download("one-piece-100") is None


def test_anime_meta_keeps_a_known_anilist_id(tmp_path) -> None:
    db = Database(tmp_path / "t.db")
    db.set_anime_meta("a", "A", 21, ["Action"])
    db.set_anime_meta("a", "A", None, ["Action", "Drama"])
    assert db.anime_meta()["a"] == ("A", 21, ["Action", "Drama"])


# -- AniList history -------------------------------------------------------------

from animeplayer.anilist.client import HistoryEntry, _fuzzy_date  # noqa: E402
from animeplayer.stats import compute_anilist_stats  # noqa: E402


def _history(media_id, status="COMPLETED", progress=12, repeat=0, episodes=12, duration=24,
             completed="", genres=("Action",), score=0.0) -> HistoryEntry:
    return HistoryEntry(media_id=media_id, title=f"Show {media_id}", cover_url=None, status=status,
                        progress=progress, repeat=repeat, score=score, started="",
                        completed=completed, episodes=episodes, duration=duration,
                        genres=genres, format="TV")


def test_a_rewatch_counts_the_whole_show_again() -> None:
    stats = compute_anilist_stats([_history(1, repeat=2)], today="2026-09-25")
    assert stats["episodes_watched"] == 36
    assert stats["hours_watched"] == round(36 * 24 / 60)
    assert stats["rewatch_count"] == 2


def test_planned_shows_add_no_time() -> None:
    stats = compute_anilist_stats([_history(1, status="PLANNING", progress=0)], today="2026-09-25")
    assert stats["episodes_watched"] == 0 and stats["planning"] == 1


def test_finished_per_month_covers_the_last_year_with_empty_months() -> None:
    entries = [_history(1, completed="2026-09-01"), _history(2, completed="2026-01-15"),
               _history(3, completed="2024-01-15"), _history(4, completed="2026")]
    months = compute_anilist_stats(entries, today="2026-09-25")["finished_per_month"]
    assert len(months) == 12
    assert months[-1] == {"month": "2026-09", "label": "Sep", "count": 1}
    assert sum(m["count"] for m in months) == 2  # 2024 is too old; "2026" has no month


def test_partial_dates_keep_their_precision() -> None:
    assert _fuzzy_date({"year": 2024, "month": 3, "day": 9}) == "2024-03-09"
    assert _fuzzy_date({"year": 2024, "month": 3, "day": None}) == "2024-03"
    assert _fuzzy_date({"year": None, "month": None, "day": None}) == ""
