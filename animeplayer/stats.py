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


# -- From the AniList list ---------------------------------------------------
#
# AniList keeps far more history than this app ever saw: every show finished
# and when, and every rewatch. Time is worked out the way AniList's own
# profile does it -- episodes watched times episode length, with each full
# rewatch counted again.

# Used when AniList doesn't know an episode's length (rare, mostly very new
# entries). The typical TV episode.
DEFAULT_EPISODE_MINUTES = 24


def _episodes_watched(entry: Any) -> int:
    full_run = entry.episodes or entry.progress
    return entry.progress + entry.repeat * full_run


def compute_anilist_stats(entries: list[Any], today: str) -> dict[str, Any]:
    """`entries` are anilist/client.HistoryEntry."""
    today_date = dt.date.fromisoformat(today)
    watched = [e for e in entries if e.status != "PLANNING"]

    minutes_by_entry = {
        e.media_id: _episodes_watched(e) * (e.duration or DEFAULT_EPISODE_MINUTES) for e in watched
    }
    total_minutes = sum(minutes_by_entry.values())

    statuses = Counter(e.status for e in entries)
    scored = [e.score for e in entries if e.score > 0]

    # Finished per month over the last year, oldest first, empty months kept.
    months = []
    year, month = today_date.year, today_date.month
    for _ in range(12):
        months.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    months.reverse()
    finished_by_month = Counter(e.completed[:7] for e in entries if len(e.completed) >= 7)
    per_month = [
        {"month": m, "label": dt.date(int(m[:4]), int(m[5:]), 1).strftime("%b"),
         "count": finished_by_month.get(m, 0)}
        for m in months
    ]

    recent = sorted((e for e in entries if e.completed), key=lambda e: e.completed, reverse=True)[:8]

    genre_minutes: dict[str, float] = defaultdict(float)
    for e in watched:
        for genre in e.genres:
            genre_minutes[genre] += minutes_by_entry[e.media_id]
    top_genres = [
        {"genre": g, "hours": round(m / 60, 1),
         "share": round(m / total_minutes, 3) if total_minutes else 0}
        for g, m in sorted(genre_minutes.items(), key=lambda kv: -kv[1])[:8]
    ]

    rewatched = sorted((e for e in entries if e.repeat > 0), key=lambda e: -e.repeat)

    return {
        "days_watched": round(total_minutes / 1440, 1),
        "hours_watched": round(total_minutes / 60),
        "episodes_watched": sum(_episodes_watched(e) for e in watched),
        "completed": statuses.get("COMPLETED", 0) + statuses.get("REPEATING", 0),
        "watching": statuses.get("CURRENT", 0),
        "planning": statuses.get("PLANNING", 0),
        "dropped": statuses.get("DROPPED", 0),
        "paused": statuses.get("PAUSED", 0),
        "mean_score": round(sum(scored) / len(scored), 1) if scored else 0,
        "rewatch_count": sum(e.repeat for e in entries),
        "rewatched_shows": len(rewatched),
        "most_rewatched": [{"title": e.title, "times": e.repeat} for e in rewatched[:5]],
        "finished_per_month": per_month,
        "finished_this_year": sum(1 for e in entries if e.completed[:4] == f"{today_date.year:04d}"),
        "recently_finished": [
            {"title": e.title, "date": e.completed, "score": e.score, "repeat": e.repeat,
             "cover_url": e.cover_url or ""}
            for e in recent
        ],
        "top_genres": top_genres,
    }
