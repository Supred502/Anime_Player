"""Continue Watching leaves out a show once it's finished.

Deliberately no Backend() here: it opens the real database and login.
"""

from animeplayer.storage.db import AniListStatus
from animeplayer.ui.backend import _finished


def test_finished_show_leaves_continue_watching() -> None:
    assert _finished(AniListStatus(1, "COMPLETED", 12, 8.5, "Hanako-kun 2", None), 12)
    # An earlier episode of a completed show is a rewatch.
    assert not _finished(AniListStatus(2, "COMPLETED", 28, 9, "Frieren", None), 3)
    assert not _finished(AniListStatus(3, "CURRENT", 5, 0, "Still Going", None), 5)


def test_history_rows_group_runs_of_one_show() -> None:
    from animeplayer.ui.backend import history_rows

    h = 3600
    events = [("a-1", "A", 1, 0), ("a-1", "A", 2, h), ("b-2", "B", 5, 2 * h),
              ("a-1", "A", 3, 3 * h), ("a-1", "A", 4, 20 * h), ("a-1", "A", 4, 21 * h)]
    rows = history_rows(events, {"b-2": ("B", "b.jpg")})
    assert [(r["slug_id"], r["episodes"]) for r in rows] == [
        ("a-1", [4]), ("a-1", [3]), ("b-2", [5]), ("a-1", [1, 2])]
    assert rows[2]["poster_url"] == "b.jpg" and rows[0]["watched_at"] == 21 * h
    assert len(history_rows(events, {}, limit=2)) == 2
