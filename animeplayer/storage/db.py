"""Local SQLite storage: watch progress and the Continue Watching row.

One row per anime holding its most-recently-watched episode and position --
that's all Continue Watching needs. Per-episode history isn't tracked yet.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

# ANIMEPLAYER_DB_PATH lets development/test runs point at a throwaway database
# instead of the user's real one. Set by the dev test harness only -- never by
# the installed app, which always uses the real default path below.
DEFAULT_DB_PATH = Path(
    os.environ.get("ANIMEPLAYER_DB_PATH", str(Path.home() / ".local" / "share" / "animeplayer" / "animeplayer.db"))
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS progress (
    anime_slug_id     TEXT PRIMARY KEY,
    anime_title       TEXT NOT NULL,
    poster_url        TEXT,
    episode_id        INTEGER NOT NULL,
    episode_number    REAL NOT NULL,
    position_seconds  REAL NOT NULL DEFAULT 0,
    duration_seconds  REAL NOT NULL DEFAULT 0,
    updated_at        REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Caches source title -> AniList media id lookups (matcher.py). anilist_id
-- is nullable: a row with NULL means "looked up, no confident match found",
-- distinct from no row at all ("never looked up").
CREATE TABLE IF NOT EXISTS title_map (
    source_title TEXT PRIMARY KEY,
    anilist_id   INTEGER
);

-- Snapshot of the logged-in user's AniList list, refreshed on login/manual
-- refresh. Replaced wholesale each refresh rather than diffed.
CREATE TABLE IF NOT EXISTS anilist_list (
    anilist_id INTEGER PRIMARY KEY,
    status     TEXT NOT NULL,
    progress   INTEGER NOT NULL,
    score      REAL NOT NULL,
    title      TEXT NOT NULL,
    cover_url  TEXT
);

-- Caches AniList media id -> streaming-source search result (the reverse of
-- title_map), so clicking a Home-page AniList card doesn't re-search the
-- source every time. slug_id NULL means "looked up, no confident match found".
-- Source-specific: see clear_anidb_mappings, called when the backend changes.
CREATE TABLE IF NOT EXISTS anidb_map (
    anilist_id INTEGER PRIMARY KEY,
    slug_id    TEXT,
    numeric_id TEXT,
    title      TEXT,
    poster_url TEXT,
    kind       TEXT
);
"""


@dataclass(frozen=True, slots=True)
class ProgressEntry:
    anime_slug_id: str
    anime_title: str
    poster_url: str | None
    episode_id: int
    episode_number: float
    position_seconds: float
    duration_seconds: float
    updated_at: float


@dataclass(frozen=True, slots=True)
class AniListStatus:
    anilist_id: int
    status: str
    progress: int
    score: float
    title: str
    cover_url: str | None
    genres: tuple[str, ...] = ()
    popularity: int = 0


@dataclass(frozen=True, slots=True)
class AniDBMapping:
    anilist_id: int
    slug_id: str
    numeric_id: str
    title: str
    poster_url: str
    kind: str


class Database:
    """Used from both the GUI thread and QThreadPool worker threads (search
    results and AniList matching are resolved off the GUI thread). SQLite's
    own serialized mode makes a shared connection safe across threads given
    check_same_thread=False, but this lock also serializes multi-statement
    methods (e.g. replace_anilist_list's delete+executemany+commit) so two
    threads can never interleave partway through one."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # busy_timeout + WAL: this lock only protects against concurrent access
        # from within one process. If the app is ever accidentally launched
        # twice, both processes open the same file -- these make that degrade
        # to "briefly wait" instead of an immediate "database is locked" error.
        self._conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        # CREATE TABLE IF NOT EXISTS doesn't touch a table that's already there
        # from an earlier version of _SCHEMA -- there's no migration system yet,
        # so columns added after a table's first release need adding by hand here.
        self._ensure_columns(
            "anilist_list",
            {
                "title": "TEXT NOT NULL DEFAULT ''",
                "cover_url": "TEXT",
                "genres": "TEXT NOT NULL DEFAULT ''",
                "popularity": "INTEGER NOT NULL DEFAULT 0",
            },
        )
        self._conn.commit()

    def _ensure_columns(self, table: str, columns: dict[str, str]) -> None:
        existing = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, decl in columns.items():
            if name not in existing:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    def close(self) -> None:
        self._conn.close()

    def save_progress(
        self,
        anime_slug_id: str,
        anime_title: str,
        poster_url: str | None,
        episode_id: int,
        episode_number: float,
        position_seconds: float,
        duration_seconds: float,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO progress
                    (anime_slug_id, anime_title, poster_url, episode_id, episode_number,
                     position_seconds, duration_seconds, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(anime_slug_id) DO UPDATE SET
                    anime_title=excluded.anime_title,
                    poster_url=excluded.poster_url,
                    episode_id=excluded.episode_id,
                    episode_number=excluded.episode_number,
                    position_seconds=excluded.position_seconds,
                    duration_seconds=excluded.duration_seconds,
                    updated_at=excluded.updated_at
                """,
                (
                    anime_slug_id,
                    anime_title,
                    poster_url,
                    episode_id,
                    episode_number,
                    position_seconds,
                    duration_seconds,
                    time.time(),
                ),
            )
            self._conn.commit()

    def get_progress(self, anime_slug_id: str) -> ProgressEntry | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM progress WHERE anime_slug_id = ?", (anime_slug_id,)
            ).fetchone()
            return ProgressEntry(**dict(row)) if row else None

    def remap_progress_slug(self, old_slug_id: str, new_slug_id: str) -> None:
        """Moves a saved-progress row onto a re-resolved id.

        Without this, an entry carried over from a different streaming
        backend turns into two Continue Watching cards for the same show: the
        stale one that can never be opened again, and the working one saved
        under the new id. The stale row wins on conflict only if nothing is
        already there -- a real row under the new id is newer by definition.
        """
        with self._lock:
            self._conn.execute(
                "UPDATE OR IGNORE progress SET anime_slug_id = ? WHERE anime_slug_id = ?",
                (new_slug_id, old_slug_id),
            )
            self._conn.execute("DELETE FROM progress WHERE anime_slug_id = ?", (old_slug_id,))
            self._conn.commit()

    def continue_watching(self, limit: int = 20) -> list[ProgressEntry]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM progress ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [ProgressEntry(**dict(row)) for row in rows]

    # -- settings ---------------------------------------------------------

    def get_setting(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            self._conn.commit()

    def delete_setting(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            self._conn.commit()

    # -- title_map (source title -> AniList media id) ----------------------

    def has_title_mapping(self, title: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM title_map WHERE source_title = ?", (title,)
            ).fetchone()
            return row is not None

    def get_title_mapping(self, title: str) -> int | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT anilist_id FROM title_map WHERE source_title = ?", (title,)
            ).fetchone()
            return row["anilist_id"] if row else None

    def save_title_mapping(self, title: str, anilist_id: int | None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO title_map (source_title, anilist_id) VALUES (?, ?) "
                "ON CONFLICT(source_title) DO UPDATE SET anilist_id=excluded.anilist_id",
                (title, anilist_id),
            )
            self._conn.commit()

    # -- anilist_list (cached snapshot of the user's AniList list) --------

    @staticmethod
    def _row_to_anilist_status(row: sqlite3.Row) -> AniListStatus:
        data = dict(row)
        genres_csv = data.pop("genres", "") or ""
        data["genres"] = tuple(g for g in genres_csv.split(",") if g)
        return AniListStatus(**data)

    def replace_anilist_list(self, entries: list[AniListStatus]) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM anilist_list")
            self._conn.executemany(
                "INSERT INTO anilist_list "
                "(anilist_id, status, progress, score, title, cover_url, genres, popularity) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        e.anilist_id, e.status, e.progress, e.score, e.title, e.cover_url,
                        ",".join(e.genres), e.popularity,
                    )
                    for e in entries
                ],
            )
            self._conn.commit()

    def get_anilist_status(self, anilist_id: int) -> AniListStatus | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM anilist_list WHERE anilist_id = ?", (anilist_id,)
            ).fetchone()
            return self._row_to_anilist_status(row) if row else None

    def get_anilist_by_status(self, status: str) -> list[AniListStatus]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM anilist_list WHERE status = ? ORDER BY title", (status,)
            ).fetchall()
            return [self._row_to_anilist_status(row) for row in rows]

    def upsert_anilist_status(self, entry: AniListStatus) -> None:
        """Updates the cached status for a single anime, unlike
        replace_anilist_list which wipes and repopulates the whole cache."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO anilist_list "
                "(anilist_id, status, progress, score, title, cover_url, genres, popularity) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(anilist_id) DO UPDATE SET "
                "status=excluded.status, progress=excluded.progress, score=excluded.score, "
                "title=excluded.title, cover_url=excluded.cover_url, "
                "genres=excluded.genres, popularity=excluded.popularity",
                (
                    entry.anilist_id, entry.status, entry.progress, entry.score, entry.title,
                    entry.cover_url, ",".join(entry.genres), entry.popularity,
                ),
            )
            self._conn.commit()

    def clear_anilist_list(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM anilist_list")
            self._conn.commit()

    # -- anidb_map (AniList media id -> anidb.app search result) ----------

    def has_anidb_mapping(self, anilist_id: int) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM anidb_map WHERE anilist_id = ?", (anilist_id,)
            ).fetchone()
            return row is not None

    def get_anidb_mapping(self, anilist_id: int) -> AniDBMapping | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM anidb_map WHERE anilist_id = ?", (anilist_id,)
            ).fetchone()
            if not row or row["slug_id"] is None:
                return None
            return AniDBMapping(**dict(row))

    def clear_anidb_mappings(self) -> None:
        """Drops every cached AniList id -> source result mapping.

        The ids in this table are only meaningful for the streaming source
        that produced them, so they have to go when the app migrates to a
        different backend -- otherwise Home-page cards keep opening ids that
        the new source has never heard of, which surfaces as an empty episode
        list rather than as anything a user could diagnose. Pure cache: it
        refills itself on the next lookup, at no cost beyond one search.
        """
        with self._lock:
            self._conn.execute("DELETE FROM anidb_map")
            self._conn.commit()

    def save_anidb_mapping(self, anilist_id: int, mapping: AniDBMapping | None) -> None:
        with self._lock:
            if mapping is None:
                self._conn.execute(
                    "INSERT INTO anidb_map (anilist_id, slug_id, numeric_id, title, poster_url, kind) "
                    "VALUES (?, NULL, NULL, NULL, NULL, NULL) "
                    "ON CONFLICT(anilist_id) DO UPDATE SET slug_id=NULL",
                    (anilist_id,),
                )
            else:
                self._conn.execute(
                    "INSERT INTO anidb_map (anilist_id, slug_id, numeric_id, title, poster_url, kind) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(anilist_id) DO UPDATE SET "
                    "slug_id=excluded.slug_id, numeric_id=excluded.numeric_id, title=excluded.title, "
                    "poster_url=excluded.poster_url, kind=excluded.kind",
                    (
                        anilist_id,
                        mapping.slug_id,
                        mapping.numeric_id,
                        mapping.title,
                        mapping.poster_url,
                        mapping.kind,
                    ),
                )
            self._conn.commit()
