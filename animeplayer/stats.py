"""Watch statistics, computed from what the app records locally.

Pure functions over plain rows, so the whole thing is testable without a
database or Qt. The rows come from storage/db.py:

- watch_time:   (day "YYYY-MM-DD", slug_id, title, seconds) -- time actually
  spent playing, one row per show per day
- watch_events: (slug_id, title, episode_number, watched_at) -- one per
  episode finished
- meta:         slug_id -> (title, anilist_id, genres)
"""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from typing import Any

# A day with less than this doesn't keep a streak going: opening an episode
# for thirty seconds is not "watched anime today".
STREAK_MINIMUM_SECONDS = 5 * 60


def _hours(seconds: float) -> float:
    return round(seconds / 3600, 1)


def _streak(days_watched: set[str], today: dt.date) -> int:
    """Consecutive days up to today -- or up to yesterday, so a streak isn't
    shown as broken in the morning before today's episode."""
    day = today if today.isoformat() in days_watched else today - dt.timedelta(days=1)
    count = 0
    while day.isoformat() in days_watched:
        count += 1
        day -= dt.timedelta(days=1)
    return count


def compute_watch_stats(
    watch_time: list[tuple[str, str, str, float]],
    watch_events: list[tuple[str, str, float, float]],
    meta: dict[str, tuple[str, int | None, list[str]]],
    today: str,
) -> dict[str, Any]:
    today_date = dt.date.fromisoformat(today)

    per_day: dict[str, float] = defaultdict(float)
    per_show: dict[str, float] = defaultdict(float)
    titles: dict[str, str] = {}
    for day, slug_id, title, seconds in watch_time:
        per_day[day] += seconds
        per_show[slug_id] += seconds
        titles[slug_id] = title

    episodes_per_show: Counter[str] = Counter()
    by_hour = [0] * 24
    for slug_id, title, _number, at in watch_events:
        episodes_per_show[slug_id] += 1
        titles.setdefault(slug_id, title)
        by_hour[dt.datetime.fromtimestamp(at).hour] += 1

    total_seconds = sum(per_day.values())

    # The last 14 days, oldest first, including days with nothing -- a chart
    # with the empty days left out would read as a steadier habit than it is.
    last_days = []
    for back in range(13, -1, -1):
        day = today_date - dt.timedelta(days=back)
        last_days.append({
            "date": day.isoformat(),
            "label": day.strftime("%a"),
            "day": day.day,
            "hours": _hours(per_day.get(day.isoformat(), 0)),
            "minutes": round(per_day.get(day.isoformat(), 0) / 60),
        })

    week_start = today_date - dt.timedelta(days=6)
    this_week = sum(s for d, s in per_day.items() if dt.date.fromisoformat(d) >= week_start)
    prev_week_start = week_start - dt.timedelta(days=7)
    last_week = sum(
        s for d, s in per_day.items() if prev_week_start <= dt.date.fromisoformat(d) < week_start
    )

    shows = sorted(set(per_show) | set(episodes_per_show), key=lambda s: -per_show.get(s, 0))
    top_shows = [
        {
            "slug_id": slug_id,
            "title": titles.get(slug_id) or (meta.get(slug_id) or ("",))[0],
            "hours": _hours(per_show.get(slug_id, 0)),
            "episodes": episodes_per_show.get(slug_id, 0),
        }
        for slug_id in shows[:8]
    ]

    # Every genre a show has gets that show's full time. A show is rarely one
    # thing, and splitting it would make a Romance-Comedy count as half of
    # each -- which is not how anyone thinks about what they watched.
    genre_seconds: dict[str, float] = defaultdict(float)
    for slug_id, seconds in per_show.items():
        for genre in (meta.get(slug_id) or ("", None, []))[2]:
            genre_seconds[genre] += seconds
    top_genres = [
        {"genre": genre, "hours": _hours(seconds),
         "share": round(seconds / total_seconds, 3) if total_seconds else 0}
        for genre, seconds in sorted(genre_seconds.items(), key=lambda kv: -kv[1])[:8]
    ]

    days_watched = {d for d, s in per_day.items() if s >= STREAK_MINIMUM_SECONDS}
    active_days = len([d for d, s in per_day.items() if s > 0])

    return {
        "total_hours": _hours(total_seconds),
        "total_episodes": sum(episodes_per_show.values()),
        "show_count": len(shows),
        "this_week_hours": _hours(this_week),
        "last_week_hours": _hours(last_week),
        "average_minutes_per_active_day": round(total_seconds / 60 / active_days) if active_days else 0,
        "streak_days": _streak(days_watched, today_date),
        "last_days": last_days,
        "top_shows": top_shows,
        "top_genres": top_genres,
        "episodes_by_hour": by_hour,
        "busiest_hour": max(range(24), key=lambda h: by_hour[h]) if any(by_hour) else -1,
    }
