"""Local SQLite storage: watch progress and the Continue Watching row.

One row per anime holding its most-recently-watched episode and position --
that's all Continue Watching needs. Per-episode history isn't tracked yet.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

def _data_dir() -> Path:
    """Where the app keeps its database, downloads and dictionary:
    %LOCALAPPDATA%\\AnimePlayer on Windows, ~/.local/share/animeplayer elsewhere."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "AnimePlayer"
    return Path.home() / ".local" / "share" / "animeplayer"


# ANIMEPLAYER_DB_PATH lets development/test runs point at a throwaway database
# instead of the user's real one. Set by the dev test harness only -- never by
# the installed app, which always uses the real default path.
DEFAULT_DB_PATH = Path(os.environ.get("ANIMEPLAYER_DB_PATH", str(_data_dir() / "animeplayer.db")))

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
-- source every time. Only successful lookups are stored -- see
-- save_anidb_mapping for why a miss is deliberately not remembered.
-- Source-specific: see clear_anidb_mappings, called when the backend changes.
CREATE TABLE IF NOT EXISTS anidb_map (
    anilist_id INTEGER PRIMARY KEY,
    slug_id    TEXT,
    numeric_id TEXT,
    title      TEXT,
    poster_url TEXT,
    kind       TEXT
);

-- Per-anime opt-outs. One so far: shows whose progress must never be pushed
-- to AniList, for the rewatch nobody wants on their profile. Keyed by AniList
-- id rather than by source slug because AniList is the thing being opted out
-- of -- an anime with no AniList match has nothing to sync in the first
-- place, and a slug changes when the source renames a show.
CREATE TABLE IF NOT EXISTS anime_prefs (
    anilist_id     INTEGER PRIMARY KEY,
    ignore_anilist INTEGER NOT NULL DEFAULT 0
);

-- Episodes saved to disk for offline playback. Keyed by (episode, audio)
-- rather than by episode alone: the sub and the dub of one episode share an
-- episode_id on the source but are two different files here.
--
-- The row is the record, not the file: a row in 'ready' whose file has been
-- deleted from underneath us is treated as missing (see get_download), so the
-- app never offers to play something that is not there.
CREATE TABLE IF NOT EXISTS downloads (
    episode_id     INTEGER NOT NULL,
    dub            INTEGER NOT NULL DEFAULT 0,
    slug_id        TEXT NOT NULL,
    numeric_id     TEXT,
    anime_title    TEXT NOT NULL,
    poster_url     TEXT,
    episode_number REAL NOT NULL,
    path           TEXT NOT NULL,
    subtitle_path  TEXT,
    status         TEXT NOT NULL,      -- queued | downloading | ready | failed
    bytes          INTEGER NOT NULL DEFAULT 0,
    message        TEXT,               -- why it failed, for the UI to show
    created_at     REAL NOT NULL,
    PRIMARY KEY (episode_id, dub)
);

-- Shows that keep their next few episodes downloaded as you watch (see
-- Backend._top_up_auto_download). Keyed by the source's slug, since that is
-- what episodes and downloads are keyed by.
CREATE TABLE IF NOT EXISTS auto_download (
    slug_id TEXT PRIMARY KEY,
    dub     INTEGER NOT NULL DEFAULT 0
);

-- Per-show choices the user made once and shouldn't have to make again:
-- which audio they watch it in, and whether filler is skipped. Keyed by the
-- source's slug. dub is NULL until they first pick one.
CREATE TABLE IF NOT EXISTS show_prefs (
    slug_id     TEXT PRIMARY KEY,
    dub         INTEGER,
    skip_filler INTEGER NOT NULL DEFAULT 0
);

-- Words saved while watching with Japanese subtitles on: the word, what
-- it means, and the line and moment it came from, so the Words page can
-- play that moment again.
CREATE TABLE IF NOT EXISTS saved_words (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    word        TEXT NOT NULL,     -- dictionary form, as written
    reading     TEXT NOT NULL,     -- hiragana
    meaning     TEXT NOT NULL,
    pos         TEXT NOT NULL DEFAULT '',
    sentence    TEXT NOT NULL,     -- the Japanese line it came from
    translation TEXT NOT NULL DEFAULT '',
    slug_id     TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL DEFAULT '',
    episode     REAL NOT NULL DEFAULT 0,
    position    REAL NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL
);

-- Watch statistics. Seconds actually spent playing, bucketed per day and
-- show -- a counter rather than a log, so it stays small however much is
-- watched -- plus one row per episode finished.
CREATE TABLE IF NOT EXISTS watch_time (
    day     TEXT NOT NULL,     -- YYYY-MM-DD, local time
    slug_id TEXT NOT NULL,
    title   TEXT NOT NULL,
    seconds REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (day, slug_id)
);
CREATE TABLE IF NOT EXISTS watch_events (
    slug_id        TEXT NOT NULL,
    title          TEXT NOT NULL,
    episode_number REAL NOT NULL,
    watched_at     REAL NOT NULL
);
-- What a show is, remembered when its page is opened, so stats can say
-- which genres the time went to without asking AniList again.
CREATE TABLE IF NOT EXISTS anime_meta (
    slug_id    TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    anilist_id INTEGER,
    genres     TEXT NOT NULL DEFAULT '[]'
);

-- The newest aired episode already announced per show, so a new-episode
-- alert fires once per episode rather than on every check.
CREATE TABLE IF NOT EXISTS airing_seen (
    anilist_id INTEGER PRIMARY KEY,
    episode    INTEGER NOT NULL
);

-- Library tabs the user makes ("Next 30 days", "With friends"...), and
-- which shows are in each. A show is kept by its source slug, which is what
-- opens its page; the rest is what its card shows.
CREATE TABLE IF NOT EXISTS library_lists (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS library_items (
    list_id     INTEGER NOT NULL,
    slug_id     TEXT NOT NULL,
    numeric_id  TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL,
    poster_url  TEXT NOT NULL DEFAULT '',
    anilist_id  INTEGER NOT NULL DEFAULT 0,
    added_at    REAL NOT NULL,
    PRIMARY KEY (list_id, slug_id)
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
    # Romaji/English/synonyms. Cached alongside the display title because
    # finding a show on the streaming source needs every name AniList knows
    # for it, not just the one shown on the card -- see anilist/matcher.py.
    titles: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DownloadEntry:
    episode_id: int
    dub: bool
    slug_id: str
    numeric_id: str
    anime_title: str
    poster_url: str | None
    episode_number: float
    path: str
    subtitle_path: str | None
    status: str
    bytes: int
    message: str
    created_at: float


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
                "alt_titles": "TEXT NOT NULL DEFAULT ''",
            },
        )
        # Rows recording "looked up, found nothing" were kept forever, so a
        # show the matcher couldn't find once stayed unfindable even after the
        # matcher itself was fixed -- confirmed live: Re:Zero season 3 had been
        # cached as unresolvable and kept reporting "couldn't find a stream"
        # long after searching for it worked again. Nothing is lost by dropping
        # them; each one costs a single search to rebuild.
        self._conn.execute("DELETE FROM anidb_map WHERE slug_id IS NULL")
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

    # -- anime_prefs (per-anime opt-outs) ----------------------------------

    def get_ignore_anilist(self, anilist_id: int) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT ignore_anilist FROM anime_prefs WHERE anilist_id = ?", (anilist_id,)
            ).fetchone()
            return bool(row["ignore_anilist"]) if row else False

    def set_ignore_anilist(self, anilist_id: int, ignore: bool) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO anime_prefs (anilist_id, ignore_anilist) VALUES (?, ?) "
                "ON CONFLICT(anilist_id) DO UPDATE SET ignore_anilist=excluded.ignore_anilist",
                (anilist_id, 1 if ignore else 0),
            )
            self._conn.commit()

    # -- auto-download -----------------------------------------------------

    def get_auto_download(self, slug_id: str) -> bool | None:
        """None when off; otherwise whether it keeps the dub (True) or the
        sub (False) downloaded."""
        with self._lock:
            row = self._conn.execute(
                "SELECT dub FROM auto_download WHERE slug_id = ?", (slug_id,)
            ).fetchone()
        return None if row is None else bool(row["dub"])

    def set_auto_download(self, slug_id: str, enabled: bool, dub: bool = False) -> None:
        with self._lock:
            if enabled:
                self._conn.execute(
                    "INSERT INTO auto_download (slug_id, dub) VALUES (?, ?) "
                    "ON CONFLICT(slug_id) DO UPDATE SET dub=excluded.dub",
                    (slug_id, 1 if dub else 0),
                )
            else:
                self._conn.execute("DELETE FROM auto_download WHERE slug_id = ?", (slug_id,))
            self._conn.commit()

    # -- saved words ------------------------------------------------------

    def save_word(self, fields: dict) -> int:
        """Saving the same word from the same line twice is one save."""
        with self._lock:
            existing = self._conn.execute(
                "SELECT id FROM saved_words WHERE word = ? AND sentence = ?",
                (fields["word"], fields["sentence"]),
            ).fetchone()
            if existing:
                return existing["id"]
            cursor = self._conn.execute(
                "INSERT INTO saved_words (word, reading, meaning, pos, sentence, translation, "
                "slug_id, title, episode, position, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (fields["word"], fields.get("reading", ""), fields.get("meaning", ""),
                 fields.get("pos", ""), fields["sentence"], fields.get("translation", ""),
                 fields.get("slug_id", ""), fields.get("title", ""),
                 float(fields.get("episode") or 0), float(fields.get("position") or 0), time.time()),
            )
            self._conn.commit()
            return cursor.lastrowid

    def saved_words(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM saved_words ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def delete_saved_word(self, word_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM saved_words WHERE id = ?", (word_id,))
            self._conn.commit()

    # -- library -----------------------------------------------------------

    def library_lists(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT l.id, l.name, COUNT(i.slug_id) AS count FROM library_lists l "
                "LEFT JOIN library_items i ON i.list_id = l.id "
                "GROUP BY l.id ORDER BY l.position, l.id").fetchall()
        return [dict(r) for r in rows]

    def create_library_list(self, name: str) -> int:
        with self._lock:
            top = self._conn.execute("SELECT COALESCE(MAX(position), 0) FROM library_lists").fetchone()[0]
            cursor = self._conn.execute(
                "INSERT INTO library_lists (name, position, created_at) VALUES (?, ?, ?)",
                (name, top + 1, time.time()))
            self._conn.commit()
            return cursor.lastrowid

    def rename_library_list(self, list_id: int, name: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE library_lists SET name = ? WHERE id = ?", (name, list_id))
            self._conn.commit()

    def delete_library_list(self, list_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM library_items WHERE list_id = ?", (list_id,))
            self._conn.execute("DELETE FROM library_lists WHERE id = ?", (list_id,))
            self._conn.commit()

    def add_to_library(self, list_id: int, show: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO library_items (list_id, slug_id, numeric_id, title, "
                "poster_url, anilist_id, added_at) VALUES (?,?,?,?,?,?,?)",
                (list_id, show["slug_id"], str(show.get("numeric_id") or ""), show.get("title") or "",
                 show.get("poster_url") or "", int(show.get("anilist_id") or 0), time.time()))
            self._conn.commit()

    def remove_from_library(self, list_id: int, slug_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM library_items WHERE list_id = ? AND slug_id = ?",
                               (list_id, slug_id))
            self._conn.commit()

    def library_items(self, list_id: int) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM library_items WHERE list_id = ? ORDER BY added_at DESC",
                (list_id,)).fetchall()
        return [dict(r) for r in rows]

    def lists_containing(self, slug_id: str) -> list[int]:
        with self._lock:
            rows = self._conn.execute("SELECT list_id FROM library_items WHERE slug_id = ?",
                                      (slug_id,)).fetchall()
        return [r[0] for r in rows]

    # -- per-show preferences ---------------------------------------------

    def get_show_prefs(self, slug_id: str) -> tuple[bool | None, bool]:
        """(dub, skip_filler); dub is None until the user has picked one."""
        with self._lock:
            row = self._conn.execute(
                "SELECT dub, skip_filler FROM show_prefs WHERE slug_id = ?", (slug_id,)
            ).fetchone()
        if row is None:
            return None, False
        return (None if row["dub"] is None else bool(row["dub"])), bool(row["skip_filler"])

    def set_show_dub(self, slug_id: str, dub: bool) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO show_prefs (slug_id, dub) VALUES (?, ?) "
                "ON CONFLICT(slug_id) DO UPDATE SET dub=excluded.dub",
                (slug_id, 1 if dub else 0),
            )
            self._conn.commit()

    def set_skip_filler(self, slug_id: str, skip: bool) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO show_prefs (slug_id, skip_filler) VALUES (?, ?) "
                "ON CONFLICT(slug_id) DO UPDATE SET skip_filler=excluded.skip_filler",
                (slug_id, 1 if skip else 0),
            )
            self._conn.commit()

    # -- watch statistics ---------------------------------------------------

    def add_watch_time(self, day: str, slug_id: str, title: str, seconds: float) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO watch_time (day, slug_id, title, seconds) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(day, slug_id) DO UPDATE SET seconds = seconds + excluded.seconds, "
                "title = excluded.title",
                (day, slug_id, title, seconds),
            )
            self._conn.commit()

    def add_watch_event(self, slug_id: str, title: str, episode_number: float, at: float) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO watch_events (slug_id, title, episode_number, watched_at) "
                "VALUES (?, ?, ?, ?)",
                (slug_id, title, episode_number, at),
            )
            self._conn.commit()

    def watch_time_rows(self) -> list[tuple[str, str, str, float]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT day, slug_id, title, seconds FROM watch_time ORDER BY day"
            ).fetchall()
        return [(r["day"], r["slug_id"], r["title"], r["seconds"]) for r in rows]

    def watch_event_rows(self) -> list[tuple[str, str, float, float]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT slug_id, title, episode_number, watched_at FROM watch_events "
                "ORDER BY watched_at"
            ).fetchall()
        return [(r["slug_id"], r["title"], r["episode_number"], r["watched_at"]) for r in rows]

    def set_anime_meta(self, slug_id: str, title: str, anilist_id: int | None,
                       genres: list[str]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO anime_meta (slug_id, title, anilist_id, genres) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(slug_id) DO UPDATE SET title=excluded.title, "
                "anilist_id=COALESCE(excluded.anilist_id, anime_meta.anilist_id), "
                "genres=excluded.genres",
                (slug_id, title, anilist_id, json.dumps(list(genres))),
            )
            self._conn.commit()

    def anime_meta(self) -> dict[str, tuple[str, int | None, list[str]]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM anime_meta").fetchall()
        out = {}
        for r in rows:
            try:
                genres = json.loads(r["genres"])
            except ValueError:
                genres = []
            out[r["slug_id"]] = (r["title"], r["anilist_id"], genres)
        return out

    # -- new-episode alerts -------------------------------------------------

    def airing_seen(self) -> dict[int, int]:
        with self._lock:
            rows = self._conn.execute("SELECT anilist_id, episode FROM airing_seen").fetchall()
        return {r["anilist_id"]: r["episode"] for r in rows}

    def set_airing_seen(self, anilist_id: int, episode: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO airing_seen (anilist_id, episode) VALUES (?, ?) "
                "ON CONFLICT(anilist_id) DO UPDATE SET episode=MAX(episode, excluded.episode)",
                (anilist_id, episode),
            )
            self._conn.commit()

    # -- downloads ---------------------------------------------------------

    @staticmethod
    def _row_to_download(row: sqlite3.Row) -> DownloadEntry:
        return DownloadEntry(
            episode_id=row["episode_id"],
            dub=bool(row["dub"]),
            slug_id=row["slug_id"],
            numeric_id=row["numeric_id"] or "",
            anime_title=row["anime_title"],
            poster_url=row["poster_url"],
            episode_number=row["episode_number"],
            path=row["path"],
            subtitle_path=row["subtitle_path"],
            status=row["status"],
            bytes=row["bytes"],
            message=row["message"] or "",
            created_at=row["created_at"],
        )

    def upsert_download(self, entry: DownloadEntry) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO downloads (episode_id, dub, slug_id, numeric_id, anime_title, "
                "poster_url, episode_number, path, subtitle_path, status, bytes, message, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(episode_id, dub) DO UPDATE SET "
                "slug_id=excluded.slug_id, numeric_id=excluded.numeric_id, "
                "anime_title=excluded.anime_title, poster_url=excluded.poster_url, "
                "episode_number=excluded.episode_number, path=excluded.path, "
                "subtitle_path=excluded.subtitle_path, status=excluded.status, "
                "bytes=excluded.bytes, message=excluded.message",
                (entry.episode_id, 1 if entry.dub else 0, entry.slug_id, entry.numeric_id,
                 entry.anime_title, entry.poster_url, entry.episode_number, entry.path,
                 entry.subtitle_path, entry.status, entry.bytes, entry.message, entry.created_at),
            )
            self._conn.commit()

    def set_download_status(self, episode_id: int, dub: bool, status: str,
                            *, bytes_written: int = 0, message: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE downloads SET status = ?, bytes = ?, message = ? "
                "WHERE episode_id = ? AND dub = ?",
                (status, bytes_written, message, episode_id, 1 if dub else 0),
            )
            self._conn.commit()

    def get_download(self, episode_id: int, dub: bool) -> DownloadEntry | None:
        """The download for this episode, or None.

        A 'ready' row whose file has since been deleted (by the user, or by a
        cleaned-out home directory) is reported as gone and the stale row
        dropped -- otherwise the app would hand mpv a path to nothing and the
        episode would simply fail to start with no explanation.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM downloads WHERE episode_id = ? AND dub = ?",
                (episode_id, 1 if dub else 0),
            ).fetchone()
        if row is None:
            return None
        entry = self._row_to_download(row)
        if entry.status == "ready" and not Path(entry.path).exists():
            self.delete_download(episode_id, dub)
            return None
        return entry

    def downloads_for(self, slug_id: str) -> list[DownloadEntry]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM downloads WHERE slug_id = ? ORDER BY episode_number",
                (slug_id,),
            ).fetchall()
        return [self._row_to_download(r) for r in rows]

    def all_downloads(self) -> list[DownloadEntry]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM downloads ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_download(r) for r in rows]

    def downloaded_anime(self) -> list[tuple[DownloadEntry, int]]:
        """One row per anime that has at least one episode on disk -- what the
        'Downloaded' listing is built from. The row returned is the most
        recently saved episode of that anime, so the listing can show its
        title and poster without a second query."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT *, COUNT(*) AS episode_count FROM downloads "
                "WHERE status = 'ready' GROUP BY slug_id ORDER BY MAX(created_at) DESC"
            ).fetchall()
        return [(self._row_to_download(r), r["episode_count"]) for r in rows]

    def delete_download(self, episode_id: int, dub: bool) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM downloads WHERE episode_id = ? AND dub = ?",
                (episode_id, 1 if dub else 0),
            )
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
        # Tab-separated, not comma: anime titles contain commas.
        alt_titles = data.pop("alt_titles", "") or ""
        data["titles"] = tuple(t for t in alt_titles.split("\t") if t)
        return AniListStatus(**data)

    def replace_anilist_list(self, entries: list[AniListStatus]) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM anilist_list")
            self._conn.executemany(
                "INSERT INTO anilist_list "
                "(anilist_id, status, progress, score, title, cover_url, genres, popularity, alt_titles) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        e.anilist_id, e.status, e.progress, e.score, e.title, e.cover_url,
                        ",".join(e.genres), e.popularity, "\t".join(e.titles),
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

    def set_anilist_status(self, anilist_id: int, status: str) -> None:
        """Updates the mirrored list after the app itself changed something on
        AniList, so the UI doesn't have to wait for the next full sync to
        agree with the button the user just pressed. An empty status means the
        entry was removed from the list entirely.

        An anime being added for the first time has no mirrored row yet, and
        the only field this knows is the status -- the rest is filled in on the
        next sync.
        """
        with self._lock:
            if not status:
                self._conn.execute(
                    "DELETE FROM anilist_list WHERE anilist_id = ?", (anilist_id,)
                )
                self._conn.commit()
                return
            updated = self._conn.execute(
                "UPDATE anilist_list SET status = ? WHERE anilist_id = ?",
                (status, anilist_id),
            ).rowcount
            if not updated:
                self._conn.execute(
                    "INSERT INTO anilist_list "
                    "(anilist_id, status, progress, score, title, cover_url, genres, "
                    "popularity, alt_titles) VALUES (?, ?, 0, 0, '', '', '', 0, '')",
                    (anilist_id, status),
                )
            self._conn.commit()

    def get_anilist_list(self) -> list[AniListStatus]:
        """The whole mirrored list. Used to badge search/browse results with
        the user's own status without going back to AniList for each one --
        every name AniList knows for an entry is already stored here."""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM anilist_list").fetchall()
            return [self._row_to_anilist_status(row) for row in rows]

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
                "(anilist_id, status, progress, score, title, cover_url, genres, popularity, alt_titles) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(anilist_id) DO UPDATE SET "
                "status=excluded.status, progress=excluded.progress, score=excluded.score, "
                "title=excluded.title, cover_url=excluded.cover_url, "
                "genres=excluded.genres, popularity=excluded.popularity, "
                "alt_titles=excluded.alt_titles",
                (
                    entry.anilist_id, entry.status, entry.progress, entry.score, entry.title,
                    entry.cover_url, ",".join(entry.genres), entry.popularity,
                    "\t".join(entry.titles),
                ),
            )
            self._conn.commit()

    def clear_anilist_list(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM anilist_list")
            self._conn.commit()

    # -- anidb_map (AniList media id -> anidb.app search result) ----------

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
        """Caches a resolved mapping. A None mapping ("searched, found
        nothing") is deliberately NOT stored: a miss is usually the source
        being down, a title the matcher couldn't handle yet, or a show the
        source hadn't listed yet, and all three stop being true later.
        Remembering them meant a show that failed once failed forever, with no
        way for a user to ask again. Re-searching on the next click costs one
        request and is what makes "try it again now" work."""
        if mapping is None:
            return
        with self._lock:
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
