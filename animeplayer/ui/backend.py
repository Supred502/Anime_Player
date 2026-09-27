"""QObject bridge exposing the Python services to QML.

Network calls run on QThreadPool workers so the UI thread never blocks; each
worker reports back by emitting a Qt signal, which is safe to do from any
thread (Qt auto-queues delivery to the GUI-thread QML bindings). self._db is
safe to call directly from worker threads too -- see storage/db.py.
"""

from __future__ import annotations

import collections
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Callable

import httpx
import qrcode
from PySide6.QtCore import Property, QCoreApplication, QObject, QProcess, QRunnable, QThreadPool, QTimer, Signal, Slot

from animeplayer import discord_presence, platform_setup, updates
from animeplayer.alerts import find_new_episodes
from animeplayer.version import ANILIST_CLIENT_ID, DISCORD_CLIENT_ID
from animeplayer.anilist import matcher
from animeplayer.anilist.client import (
    AiringState,
    AniListClient,
    ChainEntry,
    MediaSummary,
    build_authorize_url,
)
from animeplayer.aniskip import client as aniskip
from animeplayer.player import downloads as downloads_module
from animeplayer.player.downloads import (
    DownloadRequest,
    Downloader,
    DownloadError,
    delete_files,
    disk_usage,
    download_subtitle,
    ffmpeg_available,
    load_skip_times,
    probe_duration,
    save_skip_times,
    skip_times_path,
    target_path,
)
from animeplayer.player.idle_inhibitor import IdleInhibitor
from animeplayer.remote.server import RemoteServer
from animeplayer.sources import hianime as source
from animeplayer.sources import jikan
from animeplayer.learn import dictionary as jmdict
from animeplayer.learn import jimaku
from animeplayer.stats import compute_anilist_stats, compute_watch_stats
from animeplayer.storage import secrets
from animeplayer.storage.db import DEFAULT_DB_PATH, AniDBMapping, AniListStatus, Database, DownloadEntry

# The Android remote app is a thin WebView shell (see android-remote/) around
# the same page RemoteServer already serves. Also published as a GitHub
# release asset (built by android-remote/build.sh), but that's kept only as
# an off-LAN fallback link now -- a phone browser downloading straight from
# GitHub's release-asset redirect chain reported the download stuck at 100%
# and never installed, confirmed live. RemoteServer serving the same file
# directly (see _apk_path below) is a same-origin, single-hop download that
# doesn't have that problem, and is what the QR code actually points at.
_REMOTE_APK_URL = "https://github.com/Supred502/Anime_Player/releases/download/v1.0-remote/AnimePlayerRemote.apk"
_REMOTE_APK_PATH = Path(__file__).resolve().parent.parent.parent / "android-remote" / "build" / "AnimePlayerRemote.apk"


def _lan_ip() -> str:
    """Best-effort LAN IP for the phone remote's connect URL. Doesn't actually
    send any packets -- connecting a UDP socket just makes the OS pick which
    local interface/address would be used, which is exactly the address
    another device on the LAN needs to reach this machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()

_STATUS_LABELS = {
    "CURRENT": "Watching",
    "PLANNING": "Planning",
    "COMPLETED": "Completed",
    "DROPPED": "Dropped",
    "PAUSED": "Paused",
    "REPEATING": "Rewatching",
}

# The app's accent, from AniList's own profile-colour swatches, so the two
# look like the same product -- the user asked for exactly that.
#
# Only the accent. Backgrounds and text are left to the desktop's own colour
# scheme, and that is a deliberate retreat rather than an oversight: three
# separate mechanisms for imposing a full palette were tried here and all of
# them either reached nothing or reached half of it (see AppTheming.qml for
# what was measured). Half a palette is how a light scheme ends up drawing
# dark text on a dark surface, so this app now changes the one thing it can
# change correctly and follows the system for the rest -- which is also how
# AniList itself splits it: a background scheme, and a profile colour on top.
_THEME_ACCENTS: dict[str, str] = {
    "blue": "#3db4f2",
    "sky": "#02a8ff",
    "purple": "#c063ff",
    "green": "#4cca51",
    "orange": "#ef881a",
    "red": "#e13333",
    "pink": "#fc9dd6",
    "gray": "#677b94",
}

_DEFAULT_ACCENT = "blue"

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _notify_desktop(title: str, body: str) -> None:
    """A desktop notification, through the freedesktop notification service
    every Linux desktop runs. notify-send rather than D-Bus from Python:
    Notify's typed arguments (uint, string array, variant map) don't
    marshal cleanly through PySide. Missing tool, no notification -- the
    home page row still shows it."""
    if platform_setup.notify(title, body):
        return
    if shutil.which("notify-send") is None:
        return
    try:
        subprocess.Popen(
            ["notify-send", "--app-name=Anime Player", "--icon=video-television", title, body],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def _strip_html(text: str) -> str:
    """AniList's description(asHtml: false) still leaves simple tags like <br>
    and <i> in place -- strip them for plain display in QML."""
    return _HTML_TAG_RE.sub(" ", text).strip()


class _Worker(QRunnable):
    def __init__(
        self,
        fn: Callable[[], Any],
        on_result: Callable[[Any], None],
        on_error: Callable[[str], None],
    ) -> None:
        super().__init__()
        self._fn = fn
        self._on_result = on_result
        self._on_error = on_error

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001 -- surfaced to the UI, not swallowed
            self._on_error(str(exc))
            return
        try:
            self._on_result(result)
        except Exception as exc:  # noqa: BLE001 -- a bug in a callback shouldn't vanish silently
            self._on_error(str(exc))


class Backend(QObject):
    searchFinished = Signal(list)
    searchFailed = Signal(str)
    episodesFinished = Signal(list)
    episodesFailed = Signal(str)
    streamReady = Signal(str, str, str)  # (url, referer, subtitle_url) -- see player/mpv_video_item.loadUrl
    streamFailed = Signal(str)
    streamQualitiesAvailable = Signal(list)  # [{label}], best-to-worst; "Auto" is implicit
    continueWatchingChanged = Signal(list)
    # Internal-only: emitted from a worker thread, connected to a slot on this
    # (GUI-thread) object below, so Qt auto-queues delivery back onto the GUI
    # thread. Kept even though self._db is now safe to call from any thread,
    # since it also marshals the subsequent continueWatchingChanged emit.
    _progressReady = Signal(int, float)

    anilistLoggedIn = Signal(str)  # viewer name
    anilistLoggedOut = Signal()
    anilistError = Signal(str)
    anilistListRefreshed = Signal()
    anilistStatusesResolved = Signal(dict)  # {slug_id: {status, label, progress}}
    anilistCurrentStatus = Signal(str, int)  # (label, progress) for the loaded anime; ("", 0) if none
    anilistMediaDetails = Signal(dict)  # rating/genres/description/etc. for the loaded anime
    animeRemapped = Signal(dict)  # {slug_id, numeric_id} -- a stale id was re-resolved by title
    fillerEpisodesUpdated = Signal(list)  # episode numbers, from the Jikan fallback (see _maybe_fetch_filler_fallback)
    anilistPlanningChanged = Signal(list)  # Home page "Planning" row
    anilistAnimeResolved = Signal(dict)  # source result for a Home-page AniList card, ready to push DetailPage
    anilistAnimeResolveFailed = Signal(str)  # title we couldn't find a stream for
    anilistAnimeResolveErrored = Signal(str)  # the lookup itself failed (site down, no network, ...)
    anilistGenresLoaded = Signal(list)
    anilistTagsLoaded = Signal(list)
    tagDescriptionsLoaded = Signal(dict)  # {tag name: what it means}
    anilistStatsReady = Signal("QVariantMap")  # see stats.compute_anilist_stats; {} when unavailable
    audioCountsReady = Signal(str, int, int)  # (slug, subbed, dubbed) from the source's own page
    newEpisodesChanged = Signal(list)  # home row: watched shows with an aired, unwatched episode
    becauseYouWatchedReady = Signal(str, list)  # (seed title, recommendation cards)
    recommendationsFailed = Signal(str)  # recommendations couldn't be built (e.g. not logged in yet)
    # Surprise Me couldn't land on anything. Its own signal because the text is
    # a finished sentence for the user, where anilistAnimeResolveErrored's is a
    # raw failure the UI has to introduce.
    discoverFailed = Signal(str)

    skipTimesReady = Signal(dict)  # {"op": {"start","end"}, "ed": {...}} -- either/both keys may be absent
    nextEpisodeLoading = Signal(int, float)  # (episode_id, episode_number) -- fired before streamReady on auto-next
    noNextEpisode = Signal()  # auto-next requested but the current episode is the last one known

    # Home feed, straight from the streaming source's own rankings. One
    # signal per row rather than one for the whole page: each row is its own
    # request, so emitting them separately lets the page draw immediately and
    # fill in as they land instead of staying blank until the slowest one does.
    homeSpotlightReady = Signal(list)  # [{slug_id, title, banner_url, description, ...}]
    homeRowReady = Signal(str, list)   # (row key, cards)
    homeRowFailed = Signal(str, str)   # (row key, message)
    browseFinished = Signal(dict)      # {key, results, page, hasMore} -- a catalog/filter page
    browseFailed = Signal(str)
    themeChanged = Signal()
    # Everything the detail page shows beside the episode list: the franchise's
    # watch order, related entries, community recommendations and reviews.
    # One signal and one worker, because they all come from the same anime and
    # arrive together.
    animeExtrasReady = Signal(dict)

    remoteServerFailed = Signal(str)  # the phone remote couldn't start; the app itself is fine
    remoteCommand = Signal(str, "QVariant")  # (cmd, args) from the phone remote -- see remote/server.py

    # -- downloads ---------------------------------------------------------
    downloadsChanged = Signal()                 # any row added/removed/finished
    downloadProgress = Signal(int, bool, float, float)  # (episode id, dub, 0..1, bytes)
    downloadFailed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._http = httpx.Client(follow_redirects=True, timeout=15)
        self._pool = QThreadPool.globalInstance()
        self._db = Database()
        self._current_anime: dict[str, Any] | None = None
        self._current_stream_info: source.StreamInfo | None = None
        self._progressReady.connect(self._save_progress_on_gui_thread)
        self._idle_inhibitor = IdleInhibitor()
        self._spotlight_built = False
        self._preview_cache: dict[str, dict[str, Any]] = {}
        self._catalog_lock = threading.Lock()
        self._catalog: dict[int, tuple[str, tuple[str, ...]]] = {}
        self._catalog_complete = False
        self._catalog_next_page = 1
        self._discord = discord_presence.DiscordPresence(DISCORD_CLIENT_ID)
        self._discord.set_enabled(self.getDiscordEnabled())
        self._drop_mappings_from_a_previous_source()

        self._anilist_client: AniListClient | None = None
        self._anilist_user_id: int | None = None
        # Unauthenticated -- genre/tag/catalog browsing is public AniList data
        # and works whether or not the user is logged in (see AniListClient's
        # docstring). self._anilist_client above stays reserved for
        # viewer-specific calls that do need the real login.
        self._anilist_public = AniListClient(self._http)
        self._genre_cache: list[str] | None = None
        self._tag_cache: list[str] | None = None
        self._browse_token = 0
        # Rebuilt lazily; dropped whenever the mirrored list is replaced.
        self._anilist_index: "matcher.TitleIndex[AniListStatus] | None" = None
        # AniList id -> every name AniList knows for it. Finding a show on the
        # streaming source needs all of them, not just the one on the card
        # (see anilist/matcher.py), but a card only carries its display title.
        # Filled in from any MediaSummary that passes through, and backed by
        # the anilist_list table for entries on the user's own list so it
        # survives a restart.
        self._titles_by_anilist_id: dict[int, tuple[str, ...]] = {}
        self._try_restore_anilist_session()
        self._emit_anilist_home_lists()

        # Live playback snapshot for the phone remote's /api/state poll --
        # kept up to date by PlayerPage.qml calling reportPlaybackState()
        # periodically, since Backend has no direct view into mpv itself.
        self._playback_state: dict[str, Any] = {
            "title": None, "episode_number": 0, "position": 0.0, "duration": 0.0, "paused": True,
        }
        self._remote_server: RemoteServer | None = None

        # Downloads run one at a time on their own single-thread pool, not on
        # the shared QThreadPool: an ffmpeg run lasts tens of seconds, and
        # parking one of the shared pool's threads on it for that long starves
        # the searches and catalog loads the user is waiting on.
        self._downloader = Downloader()
        # What the player has on screen right now, for "continue on phone".
        # None when nothing is playing.
        self._now_playing: dict[str, Any] | None = None
        # slug -> (subbed, dubbed), as last read from the source.
        self._audio_counts: dict[str, tuple[int, int]] = {}
        self._playing = False
        downloads_module.set_download_dir(self._db.get_setting("download_dir"))
        self._download_pool = QThreadPool()
        self._download_pool.setMaxThreadCount(1)
        # The line of episodes waiting to download, in the order they'll run,
        # and the one running now. Read and changed from both threads.
        self._download_lock = threading.Lock()
        self._pending_downloads: list[tuple[DownloadRequest, Path]] = []
        self._active_download: DownloadRequest | None = None
        # Anything left mid-flight when the app was last closed is not
        # running any more, whatever the database says.
        for entry in self._db.all_downloads():
            if entry.status in ("queued", "downloading"):
                self._db.set_download_status(entry.episode_id, entry.dub, "failed",
                                             message="Interrupted -- start it again.")
        # Auto-start the phone remote on launch, unless the user explicitly
        # turned it off last time via the Settings Stop button -- requested
        # so "open the anime, then open the phone app" needs zero manual
        # steps in between (no visiting Settings to click Start each time).
        if (self._db.get_setting("remote_enabled") or "true") == "true":
            self.startRemoteServer()

        # New-episode alerts: once shortly after launch, then every half hour.
        # One AniList request per check, however many shows are followed.
        self._new_episodes: list[dict[str, Any]] = []
        self._alert_timer = QTimer(self)
        self._alert_timer.setInterval(self.NEW_EPISODE_CHECK_MS)
        self._alert_timer.timeout.connect(self.checkNewEpisodes)
        self._alert_timer.start()
        QTimer.singleShot(15_000, self.checkNewEpisodes)

        # Updates: a little after launch, then every few hours for copies
        # that stay open for days.
        self._release: updates.Release | None = None
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(self.UPDATE_CHECK_MS)
        self._update_timer.timeout.connect(lambda: self.checkForUpdates(False))
        self._update_timer.start()
        self._updateReadyToRun.connect(self._run_update)

        # The last few things that went wrong, for "Report a problem".
        self._recent_errors: collections.deque[str] = collections.deque(maxlen=15)
        for name, signal in (
            ("Search", self.searchFailed), ("Episodes", self.episodesFailed),
            ("Stream", self.streamFailed), ("AniList", self.anilistError),
            ("Finding show", self.anilistAnimeResolveErrored), ("Browse", self.browseFailed),
            ("Discover", self.discoverFailed), ("Phone remote", self.remoteServerFailed),
            ("Download", self.downloadFailed), ("AniList list", self.listStatusFailed),
            ("Japanese subtitles", self.japaneseSubsFailed), ("Dictionary", self.dictionaryFailed),
            ("Update", self.updateFailed),
        ):
            signal.connect(lambda message, name=name: self.noteError(f"{name}: {message}"))
        QTimer.singleShot(8_000, lambda: self.checkForUpdates(False))
        QTimer.singleShot(2_500, self._maybe_show_whats_new)
        # The title list behind "did you mean" takes a minute to fetch at
        # AniList's pace, so it's fetched in the background well before it's
        # needed (and then kept for a week).
        QTimer.singleShot(45_000, self._warm_title_catalog)

    # Bumped when the title matcher changes in a way that could have saved
    # wrong AniList -> source matches: they're all dropped once, and rebuilt
    # as shows are opened. 2: the word-overlap rule (matcher._word_overlap).
    _MATCHER_VERSION = "2"

    def _drop_mappings_from_a_previous_source(self) -> None:
        """One-time cache reset when the streaming backend changes underneath
        an existing install, or the matcher gets stricter -- see
        Database.clear_anidb_mappings."""
        if (self._db.get_setting("stream_source") == source.BASE_URL
                and self._db.get_setting("matcher_version") == self._MATCHER_VERSION):
            return
        self._db.clear_anidb_mappings()
        self._db.set_setting("stream_source", source.BASE_URL)
        self._db.set_setting("matcher_version", self._MATCHER_VERSION)

    def _remember_titles(self, summaries: list[MediaSummary]) -> None:
        for m in summaries:
            if m.titles:
                self._titles_by_anilist_id[m.id] = m.titles

    def _titles_for(self, anilist_id: int, display_title: str) -> tuple[str, ...]:
        """Every name to try when looking this anime up on the source."""
        known = self._titles_by_anilist_id.get(anilist_id)
        if known is None:
            entry = self._db.get_anilist_status(anilist_id)
            known = entry.titles if entry else ()
        # The display title stays first: it is the one the user just clicked,
        # and it is the only name available at all for a card that came from
        # somewhere with no AniList record behind it.
        return (display_title, *(t for t in known if t != display_title))

    @Slot(bool)
    def setKeepScreenAwake(self, awake: bool) -> None:
        """Driven straight from "is an episode playing right now" -- see
        player/idle_inhibitor.py for why playback alone doesn't keep the
        session awake. Deliberately follows pause as well as page lifetime:
        pausing and walking away should let the screen sleep normally."""
        # Also what downloads read to decide whether to hold back -- see
        # _run_download.
        self._playing = awake
        if awake:
            self._idle_inhibitor.inhibit()
        else:
            self._idle_inhibitor.release()

    def shutdown(self) -> None:
        self._idle_inhibitor.release()
        if self._remote_server is not None:
            self._remote_server.stop()
        self._http.close()
        self._db.close()

    # -- hianime.at search / episodes / playback ---------------------------

    @Slot(str)
    def search(self, query: str) -> None:
        def work() -> list[source.SearchResult]:
            return source.search(query, self._http)

        def done(results: list[source.SearchResult]) -> None:
            self.searchFinished.emit([self._search_result_to_card(r) for r in results])
            if self._anilist_client is not None:
                self._match_anilist_statuses(results)

        self._pool.start(_Worker(work, done, self.searchFailed.emit))

    # Every card the UI shows carries exactly these keys, whether it came from
    # the streaming source's search or from AniList's catalog. The two used to
    # emit different key sets into the same QML ListModel, and a ListModel
    # fixes its roles from the first row it is given: rows from the other
    # producer then had those roles present but unset, which QML reads as
    # `undefined`. That rendered literally, as an "undefined" badge on every
    # card of every genre search and recommendation.
    _CARD_FIELDS: dict[str, Any] = {
        "slug_id": "", "numeric_id": "", "anilist_id": 0, "title": "",
        "poster_url": "", "kind": "", "rating": "", "duration": "",
        "sub_count": 0, "dub_count": 0, "reason": "",
    }

    @classmethod
    def _card(cls, **fields: Any) -> dict[str, Any]:
        return {**cls._CARD_FIELDS, **fields}

    @classmethod
    def _media_summary_to_card(cls, m: MediaSummary, reason: str = "") -> dict[str, Any]:
        return cls._card(
            anilist_id=m.id,
            title=m.title,
            poster_url=m.cover_url or "",
            kind=m.format or "",
            # Empty rather than "0.0" when AniList has no score yet, so the
            # card can leave the star out instead of advertising a zero.
            rating=f"{m.average_score / 10:.1f}" if m.average_score else "",
            reason=reason,
        )

    @classmethod
    def _search_result_to_card(cls, r: source.SearchResult) -> dict[str, Any]:
        return cls._card(**asdict(r))

    @staticmethod
    def _spotlight_to_card(s: source.Spotlight) -> dict[str, Any]:
        # Not run through _card(): a hero is a different shape from a poster
        # card (wide banner, synopsis) and feeds its own model, so forcing it
        # into the card field set would only add nine empty keys.
        return {
            "slug_id": s.slug_id,
            "numeric_id": s.numeric_id,
            "title": s.title,
            "japanese_title": s.japanese_title,
            "banner_url": s.banner_url,
            "description": s.description,
            "kind": s.kind,
            "duration": s.duration,
            "released": s.released,
            "sub_count": s.sub_count,
            "dub_count": s.dub_count,
            "rank": s.rank,
        }

    _NOT_IN_LIST = "NOT_IN_LIST"  # synthetic status for the "not in my list" filter chip

    def _list_status_of(self, anilist_id: int) -> str:
        status = self._db.get_anilist_status(anilist_id)
        return status.status if status is not None else self._NOT_IN_LIST

    def _apply_status_filter(
        self, results: list[MediaSummary], include: list, exclude: list
    ) -> list[MediaSummary]:
        if not include and not exclude:
            return results
        include_set, exclude_set = set(include), set(exclude)
        out = []
        for m in results:
            status = self._list_status_of(m.id)
            if include_set and status not in include_set:
                continue
            if status in exclude_set:
                continue
            out.append(m)
        return out

    # -- AniList catalog ----------------------------------------------------
    #
    # Deliberately separate from the plain title search above: filtering
    # browses AniList's catalog rather than the source's, because only AniList
    # can exclude as well as include and only it knows tags, country of origin
    # and scores. A playable source match is resolved lazily, once a specific
    # result is clicked (openAnilistAnime).

    # AniList's genre list and tag vocabulary are effectively static -- a
    # handful of tags get added a year. Re-fetching them on every launch is
    # two requests per start of the app for data that has not changed, so they
    # are kept on disk and only refreshed once a week. AniList has asked
    # publicly for third-party clients to be lighter on their API; this and
    # the response cache in anilist/client.py are most of this app's answer.
    _STATIC_LIST_MAX_AGE = 7 * 24 * 60 * 60

    def _cached_static_list(self, name: str) -> list[str] | None:
        raw = self._db.get_setting(f"anilist_{name}")
        stamp = self._db.get_setting(f"anilist_{name}_at")
        if not raw or not stamp:
            return None
        try:
            if time.time() - float(stamp) > self._STATIC_LIST_MAX_AGE:
                return None
            values = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            return None
        return values if isinstance(values, list) and values else None

    def _store_static_list(self, name: str, values: list[str]) -> None:
        self._db.set_setting(f"anilist_{name}", json.dumps(values))
        self._db.set_setting(f"anilist_{name}_at", str(time.time()))

    def _fetch_static_list(self, name: str, fetch, signal) -> None:
        cached = getattr(self, f"_{name}_cache")
        if cached is not None:
            signal.emit(cached)
            return
        stored = self._cached_static_list(name)
        if stored is not None:
            setattr(self, f"_{name}_cache", stored)
            signal.emit(stored)
            return

        def done(values: list[str]) -> None:
            ordered = sorted(values)
            setattr(self, f"_{name}_cache", ordered)
            self._store_static_list(name, ordered)
            signal.emit(ordered)

        self._pool.start(_Worker(fetch, done, lambda _msg: None))

    @Slot()
    def fetchAnilistGenres(self) -> None:
        self._fetch_static_list(
            "genre", self._anilist_public.get_genre_collection, self.anilistGenresLoaded
        )

    @Slot()
    def fetchAnilistTags(self) -> None:
        self._fetch_static_list(
            "tag", self._anilist_public.get_tag_collection, self.anilistTagsLoaded
        )

    @Slot()
    def fetchTagDescriptions(self) -> None:
        """Stored beside the tag names and refreshed on the same weekly
        schedule. Emitted as a map rather than threaded through the names
        list, so nothing that already consumes that list has to change."""
        raw = self._db.get_setting("anilist_tag_desc")
        stamp = self._db.get_setting("anilist_tag_desc_at")
        try:
            if raw and stamp and time.time() - float(stamp) <= self._STATIC_LIST_MAX_AGE:
                self.tagDescriptionsLoaded.emit(json.loads(raw))
                return
        except (ValueError, json.JSONDecodeError):
            pass

        def done(values: dict[str, str]) -> None:
            self._db.set_setting("anilist_tag_desc", json.dumps(values))
            self._db.set_setting("anilist_tag_desc_at", str(time.time()))
            self.tagDescriptionsLoaded.emit(values)

        self._pool.start(_Worker(self._anilist_public.get_tag_descriptions, done, lambda _msg: None))

    def _affinity_sorted(self, results: list[MediaSummary]) -> list[MediaSummary]:
        # Same relevance heuristic as the Home page's Planning row: shows
        # sharing genres with what's actually been finished score higher,
        # ties fall back to AniList's own popularity. Degrades gracefully
        # to popularity-only if nothing's marked Completed yet (or the user
        # isn't logged in) -- completed_genres is just empty then.
        completed_genres: set[str] = set()
        for e in self._db.get_anilist_by_status("COMPLETED"):
            completed_genres.update(e.genres)

        def affinity(m: MediaSummary) -> tuple[int, int]:
            return (len(completed_genres & set(m.genres)), m.popularity)

        return sorted(results, key=affinity, reverse=True)

    # -- Theme -------------------------------------------------------------

    @staticmethod
    def _theme_from(db: Database) -> dict[str, Any]:
        accent_name = db.get_setting("theme_accent") or _DEFAULT_ACCENT
        return {
            "accent": _THEME_ACCENTS.get(accent_name, _THEME_ACCENTS[_DEFAULT_ACCENT]),
            "accentName": accent_name,
        }

    @Property("QVariantMap", notify=themeChanged)
    def theme(self) -> dict[str, Any]:
        """The app's accent colour -- see the note above _THEME_ACCENTS for
        why it is only the accent."""
        return self._theme_from(self._db)

    @Slot(result=list)
    def themeAccents(self) -> list[dict[str, str]]:
        return [{"key": key, "color": value} for key, value in _THEME_ACCENTS.items()]

    @Slot(str)
    def setThemeAccent(self, accent: str) -> None:
        if accent in _THEME_ACCENTS:
            self._db.set_setting("theme_accent", accent)
            self.themeChanged.emit()

    # -- My list ------------------------------------------------------------

    listStatusChanged = Signal(int, str)  # (anilist id, new status; "" once removed)
    listStatusFailed = Signal(str)

    @Slot(int, str)
    def setListStatus(self, anilist_id: int, status: str) -> None:
        """Puts an anime on the user's AniList list with `status`, or takes it
        off entirely when `status` is empty.

        The local mirror is updated straight away rather than waiting for the
        next full sync, so the button the user just pressed reflects reality
        without a round trip they'd watch.
        """
        client = self._anilist_client
        if client is None:
            self.listStatusFailed.emit("Log in to AniList in Settings to use your list.")
            return
        if not anilist_id:
            self.listStatusFailed.emit("This anime isn't matched to AniList yet.")
            return
        user_id = self._anilist_user_id

        def work() -> str:
            if status:
                client.set_list_status(anilist_id, status)
            elif user_id is not None:
                client.remove_from_list(anilist_id, user_id)
            return status

        def done(new_status: str) -> None:
            self._db.set_anilist_status(anilist_id, new_status)
            self._anilist_index = None
            self.listStatusChanged.emit(anilist_id, new_status)
            self._emit_anilist_home_lists()

        self._pool.start(_Worker(work, done, self.listStatusFailed.emit))

    @Slot(int, result=str)
    def listStatusOf(self, anilist_id: int) -> str:
        entry = self._db.get_anilist_status(anilist_id) if anilist_id else None
        return entry.status if entry is not None else ""

    # -- Home feed / catalog browsing --------------------------------------
    #
    # All of this reads the streaming source's own rankings rather than
    # AniList's. Deliberate: these rows exist to be clicked straight into
    # playback, and every entry the source ranks is by definition present on
    # the source, so a click here can never land on "couldn't find a stream"
    # the way an AniList-sourced card can.

    # The rows the home page stacks, in order, under the hero and the user's
    # own Continue Watching / Watching rows. Fewer than the source publishes
    # (see hianime.CATALOGS) -- the rest are reachable through Browse, and a
    # home page that scrolls forever is just a catalog with extra steps.
    _HOME_ROWS = ("trending", "top-airing", "most-popular", "recently-updated",
                  "most-favorite", "latest-completed", "top-upcoming")
    # Trending is the one row with no catalog page of its own -- it exists
    # only on the site's home page. So it needs both its own label and a
    # stand-in catalog for "See all" to open, and refreshHomeFeed fills it
    # from the home request instead of starting a catalog worker for it.
    _HOME_ONLY_ROW = "trending"
    _HOME_ROW_LABELS = {"trending": "Trending"}
    # Trending has a preset of its own now, so "See all" lands on the same
    # ranking the row was built from rather than a stand-in.
    _HOME_ROW_CATALOG = {"trending": "trending"}

    @Slot(result=list)
    def homeRows(self) -> list[dict[str, str]]:
        """The home page's row list, so the page doesn't hardcode an order
        the backend also has to know."""
        return [
            {
                "key": key,
                "label": self._HOME_ROW_LABELS.get(key) or source.CATALOGS[key],
                "catalog": self._HOME_ROW_CATALOG.get(key, key),
            }
            for key in self._HOME_ROWS
        ]

    # The ranked catalogs, expressed as filter values rather than as a
    # separate endpoint. Picking one used to switch the page over to the
    # source's own catalog, which silently ignored every other filter -- so
    # "Top Airing" plus "Movies" plus "China" quietly answered only the first
    # of the three. As presets they just fill in filters, and everything
    # composes.
    _CATALOG_PRESETS: dict[str, dict[str, Any]] = {
        "trending": {"label": "Trending", "sort": "TRENDING_DESC"},
        "top-airing": {"label": "Top Airing", "airing": "RELEASING",
                       "sort": "POPULARITY_DESC"},
        "most-popular": {"label": "Most Popular", "sort": "POPULARITY_DESC"},
        "most-favorite": {"label": "Most Favourite", "sort": "FAVOURITES_DESC"},
        "highest-rated": {"label": "Highest Rated", "sort": "SCORE_DESC"},
        "latest-completed": {"label": "Latest Completed", "airing": "FINISHED",
                             "sort": "END_DATE_DESC"},
        "recently-updated": {"label": "Latest Episodes", "sort": "UPDATED_AT_DESC"},
        "new-anime": {"label": "Newly Added", "sort": "ID_DESC"},
        "top-upcoming": {"label": "Top Upcoming", "airing": "NOT_YET_RELEASED",
                         "sort": "POPULARITY_DESC"},
        "movie": {"label": "Movies", "format": "MOVIE", "sort": "POPULARITY_DESC"},
        "tv": {"label": "TV Series", "format": "TV", "sort": "POPULARITY_DESC"},
        "ova": {"label": "OVAs", "format": "OVA", "sort": "POPULARITY_DESC"},
        "ona": {"label": "ONAs", "format": "ONA", "sort": "POPULARITY_DESC"},
        "special": {"label": "Specials", "format": "SPECIAL", "sort": "POPULARITY_DESC"},
    }

    @Slot(result=list)
    def catalogs(self) -> list[dict[str, Any]]:
        """Every preset, for the Browse page's picker."""
        return [{"key": key, **preset} for key, preset in self._CATALOG_PRESETS.items()]

    @Slot()
    def refreshHomeFeed(self) -> None:
        """Kicks off the hero carousel and every home row at once.

        Each row is an independent worker, so a row whose request fails or
        hangs costs only that row -- an earlier single-request design meant
        one slow catalog held the whole page blank.
        """
        def highlights() -> tuple[list[source.Spotlight], list[source.SearchResult]]:
            return source.get_home_highlights(self._http)

        def highlights_done(
            feed: tuple[list[source.Spotlight], list[source.SearchResult]]
        ) -> None:
            spotlight, trending = feed
            # The site's own carousel is only the fallback now -- see
            # _build_spotlight -- so it's shown only if that hasn't landed.
            if not self._spotlight_built:
                self.homeSpotlightReady.emit([self._spotlight_to_card(s) for s in spotlight])
            self.homeRowReady.emit(
                "trending", [self._search_result_to_card(r) for r in trending]
            )

        def highlights_failed(message: str) -> None:
            self.homeRowFailed.emit("trending", message)

        self._pool.start(_Worker(highlights, highlights_done, highlights_failed))
        self._build_spotlight()

        for key in self._HOME_ROWS:
            if key != self._HOME_ONLY_ROW:
                self._start_home_row(key)

    def _start_home_row(self, key: str) -> None:
        # Bound as default arguments rather than closed over: every row shares
        # this one function, and a plain closure over `key` would have all of
        # them report under whichever key the loop finished on.
        def work(category: str = key) -> source.CatalogPage:
            return source.browse(category, 1, self._http)

        def done(page: source.CatalogPage, row: str = key) -> None:
            self.homeRowReady.emit(
                row, [self._search_result_to_card(r) for r in page.results]
            )

        def failed(message: str, row: str = key) -> None:
            self.homeRowFailed.emit(row, message)

        self._pool.start(_Worker(work, done, failed))

    # Browsing is driven by controls the user can change faster than a
    # request round trip: flipping three filters fires three overlapping
    # requests, and whichever the site answers last would otherwise win
    # regardless of which the user actually asked for last. Each request takes
    # a token, and only the newest one is allowed to report back.
    def _begin_browse(self) -> int:
        self._browse_token += 1
        return self._browse_token

    def _browse_failed(self, token: int) -> Callable[[str], None]:
        def failed(message: str) -> None:
            if token == self._browse_token:
                self.browseFailed.emit(message)

        return failed

    @Slot(dict, int)
    def searchByFilters(self, filters: dict[str, Any], page: int) -> None:
        spec = dict(filters or {})

        def as_list(name: str) -> list[str]:
            return [str(v) for v in (spec.get(name) or [])]

        status_include, status_exclude = as_list("statusInclude"), as_list("statusExclude")
        token = self._begin_browse()

        def work() -> tuple[list[MediaSummary], bool]:
            return self._anilist_public.search_by_filters(
                str(spec.get("keyword") or ""),
                as_list("genres"),
                as_list("tags"),
                exclude_genres=as_list("excludeGenres"),
                exclude_tags=as_list("excludeTags"),
                formats=as_list("formats"),
                exclude_formats=as_list("excludeFormats"),
                country=str(spec.get("country") or "") or None,
                min_score=int(spec.get("minScore") or 0) or None,
                season=str(spec.get("season") or "") or None,
                season_year=int(spec.get("seasonYear") or 0) or None,
                statuses=as_list("airingStatus") or None,
                exclude_statuses=as_list("excludeAiringStatus") or None,
                sort=str(spec.get("sort") or "") or None,
                page=page,
            )

        def done(result: tuple[list[MediaSummary], bool]) -> None:
            if token != self._browse_token:
                return
            results, has_more = result
            # Status (Watching/Planning/Completed/... or "not in my list") isn't
            # part of AniList's public catalog filters -- it's this user's own
            # list data, so it's applied locally after the catalog page comes
            # back. This means a page can come back with fewer visible results
            # than 50 after filtering even though has_more is still true --
            # "Load more" just keeps pulling subsequent catalog pages.
            filtered = self._apply_status_filter(results, status_include, status_exclude)
            # AniList can filter *to* a country but has no country_not_in, so
            # excluding one is done on the results. Same page size either way;
            # this only ever removes rows.
            excluded_countries = set(as_list("excludeCountries"))
            if excluded_countries:
                filtered = [m for m in filtered if m.country not in excluded_countries]
            # Only re-rank by affinity when the user hasn't asked for an order
            # and hasn't typed a title. Sorting their chosen "highest scored
            # first" by genre overlap instead is the kind of helpfulness that
            # reads as a bug -- and doing it to a title search is worse, since
            # it pushes the thing they actually typed down the page.
            keep_order = bool(spec.get("sort")) or bool(spec.get("keyword"))
            ranked = filtered if keep_order else self._affinity_sorted(filtered)
            self._remember_titles(ranked)
            self.browseFinished.emit(
                {
                    "key": "anilist",
                    "results": [self._media_summary_to_card(m) for m in ranked],
                    "page": page,
                    "hasMore": has_more,
                }
            )

        self._pool.start(_Worker(work, done, self._browse_failed(token)))

    # How many of the user's own shows to ask AniList about. One request per
    # 50, so this is the knob trading "how much of your taste is considered"
    # against how long the button takes to answer.
    _RECOMMENDATION_SOURCE_LIMIT = 100
    # A sequel to something already finished outranks any community
    # suggestion: "season 2 exists" is the one recommendation that is never a
    # guess. Above AniList's highest real rating counts, which run to a few
    # thousand.
    _SEQUEL_WEIGHT = 1_000_000

    def _anilist_known_ids(self) -> set[int]:
        """Everything already on the user's list in any status -- the things a
        recommendation must never be."""
        known: set[int] = set()
        for status in ("CURRENT", "PLANNING", "COMPLETED", "DROPPED", "PAUSED", "REPEATING"):
            known.update(e.anilist_id for e in self._db.get_anilist_by_status(status))
        return known

    def _recommendation_seed_ids(self) -> list[int]:
        """Which of the user's shows to base suggestions on: everything
        currently being watched (the strongest signal about what they're in
        the mood for), then the most popular of what they've finished, since
        a well-known show has far more community recommendations hanging off
        it than an obscure one."""
        current = self._db.get_anilist_by_status("CURRENT")
        completed = sorted(
            self._db.get_anilist_by_status("COMPLETED"),
            key=lambda e: (e.score, e.popularity),
            reverse=True,
        )
        seeds = [e.anilist_id for e in current]
        for entry in completed:
            if len(seeds) >= self._RECOMMENDATION_SOURCE_LIMIT:
                break
            if entry.anilist_id not in seeds:
                seeds.append(entry.anilist_id)
        return seeds

    @Slot()
    def loadRecommendations(self) -> None:
        """"Recommend me something": what to watch next, based on what's
        already been watched.

        Two signals, blended and labelled so a card says why it's there:
        unwatched sequels of shows already finished, and AniList's community
        "if you liked this, try that" suggestions. This used to be sequels
        only, which meant it could only ever offer more of the same shows --
        and in practice offered mostly their recap episodes and picture
        dramas, since those are sequel-linked too.
        """
        seeds = self._recommendation_seed_ids()
        if not seeds:
            self.recommendationsFailed.emit(
                "Log in to AniList and watch a few shows to see recommendations here."
            )
            return
        known_ids = self._anilist_known_ids()

        def work() -> list[tuple[str, MediaSummary, str, int]]:
            return self._anilist_public.get_recommendation_sources(seeds)

        def done(rows: list[tuple[str, MediaSummary, str, int]]) -> None:
            best: dict[int, tuple[int, MediaSummary, str]] = {}
            for kind, suggestion, because_of, rating in rows:
                if suggestion.id in known_ids:
                    continue
                weight = self._SEQUEL_WEIGHT if kind == "sequel" else rating
                reason = (
                    f"Next season of {because_of}" if kind == "sequel"
                    else f"Because you watched {because_of}"
                )
                # Several watched shows can point at the same suggestion; keep
                # the strongest reason rather than whichever arrived last.
                if suggestion.id not in best or weight > best[suggestion.id][0]:
                    best[suggestion.id] = (weight, suggestion, reason)
            if not best:
                self.recommendationsFailed.emit(
                    "Nothing new to suggest yet -- watch a few more shows and try again."
                )
                return
            ranked = sorted(best.values(), key=lambda row: row[0], reverse=True)
            self._remember_titles([m for _w, m, _r in ranked])
            self.browseFinished.emit(
                {
                    "key": "recommendations",
                    "results": [self._media_summary_to_card(m, reason) for _w, m, reason in ranked],
                    "page": 1,
                    "hasMore": False,
                }
            )

        self._pool.start(_Worker(work, done, self.recommendationsFailed.emit))

    # Picked from the most popular slice of the catalog rather than the whole
    # of it: a uniformly random AniList pick is nearly always a 1970s short or
    # a music video, which is a joke the first time and tedious after that.
    _SURPRISE_POOL_PAGES = 40  # 50 per page -> the top ~2000 anime
    _SURPRISE_FORMATS = ["TV", "MOVIE", "ONA"]
    _SURPRISE_ATTEMPTS = 6

    @Slot()
    def surpriseMe(self) -> None:
        """"Just pick something": opens one random anime, chosen from the
        popular end of AniList's catalog and skipping anything already on the
        user's list.

        Resolves it against the streaming source before answering, and tries
        another pick if that fails, so the button always lands on something
        actually watchable instead of on an apology.
        """
        known_ids = self._anilist_known_ids()

        def work() -> source.SearchResult | None:
            last_page = self._SURPRISE_POOL_PAGES
            for _attempt in range(self._SURPRISE_ATTEMPTS):
                page = random.randint(1, min(self._SURPRISE_POOL_PAGES, last_page))
                candidates, last_page = self._anilist_public.get_popular_page(
                    page, self._SURPRISE_FORMATS
                )
                random.shuffle(candidates)
                for candidate in candidates:
                    if candidate.id in known_ids:
                        continue
                    self._remember_titles([candidate])
                    match = matcher.find_source_result(
                        self._titles_for(candidate.id, candidate.title),
                        lambda q: source.search(q, self._http),
                    )
                    if match is not None:
                        self._db.save_anidb_mapping(
                            candidate.id,
                            AniDBMapping(
                                anilist_id=candidate.id,
                                slug_id=match.slug_id,
                                numeric_id=match.numeric_id,
                                title=match.title,
                                poster_url=match.poster_url,
                                kind=match.kind,
                            ),
                        )
                        return match
            return None

        def done(match: source.SearchResult | None) -> None:
            if match is None:
                self.discoverFailed.emit(
                    "Couldn't find anything to surprise you with just now -- try again."
                )
                return
            self.anilistAnimeResolved.emit(
                {
                    "slug_id": match.slug_id,
                    "numeric_id": match.numeric_id,
                    "title": match.title,
                    "poster_url": match.poster_url,
                    "kind": match.kind,
                }
            )

        def failed(message: str) -> None:
            self.discoverFailed.emit("Couldn't pick an anime: " + message)

        self._pool.start(_Worker(work, done, failed))

    @Slot(str, str, str, str)
    def loadEpisodes(self, slug_id: str, numeric_id: str, title: str, poster_url: str) -> None:
        self._current_anime = {
            "slug_id": slug_id,
            "numeric_id": numeric_id,
            "title": title,
            "poster_url": poster_url,
            "anilist_id": None,
            "episode_count": None,
            "mal_id": None,
            "has_filler_data": None,  # None = not yet known; set once episodes arrive
            "episodes": None,  # full Episode list, used by loadNextEpisode() to find "what's next"
            "current_episode_number": None,  # set by loadStream/loadNextEpisode; used by _maybe_fetch_skip_times
        }

        def work() -> tuple[str, str, list[source.Episode]]:
            episodes = source.get_episodes(slug_id, self._http)
            if episodes:
                return slug_id, numeric_id, episodes
            # An id the source doesn't know: either it was cached from a
            # different backend, or the entry moved. Re-resolve it by title
            # once rather than showing an empty episode list, which reads as
            # "this anime has no episodes" and gives the user nothing to act on.
            # Only the one title here: this path starts from a source slug,
            # not from an AniList entry, so there are no alternate names to
            # try. find_source_result still normalises the query, which is
            # what most of these misses actually needed.
            match = matcher.find_source_result((title,), lambda q: source.search(q, self._http))
            if match is None:
                return slug_id, numeric_id, []
            return match.slug_id, match.numeric_id, source.get_episodes(match.slug_id, self._http)

        def done(resolved: tuple[str, str, list[source.Episode]]) -> None:
            new_slug_id, new_numeric_id, episodes = resolved
            if new_slug_id != slug_id:
                self._db.remap_progress_slug(slug_id, new_slug_id)
                self.animeRemapped.emit({"slug_id": new_slug_id, "numeric_id": new_numeric_id})
                self._emit_continue_watching()
            self.episodesFinished.emit([asdict(e) for e in episodes])
            self._fetch_audio_counts(new_slug_id)
            if self._current_anime is not None and self._current_anime["slug_id"] == slug_id:
                self._current_anime["slug_id"] = new_slug_id
                self._current_anime["numeric_id"] = new_numeric_id
                self._current_anime["episode_count"] = len(episodes)
                self._current_anime["has_filler_data"] = any(e.filler for e in episodes)
                self._current_anime["episodes"] = episodes
                self._maybe_fetch_filler_fallback(new_slug_id)
                # Catch the rolling window up on open, too: episodes may have
                # been watched elsewhere, or a download failed while offline.
                auto_dub = self._db.get_auto_download(new_slug_id)
                progress = self._db.get_progress(new_slug_id)
                if auto_dub is not None and progress is not None:
                    self._top_up_auto_download(after=progress.episode_number - 1e-6, dub=auto_dub)
            # Unconditional: what this fills in is public AniList data (see
            # _resolve_current_anime_status), and gating it on being logged in
            # meant a logged-out detail page showed a title and nothing else.
            self._resolve_current_anime_status(new_slug_id, title)

        self._pool.start(_Worker(work, done, self.episodesFailed.emit))

    def _fetch_audio_counts(self, slug_id: str) -> None:
        """How many episodes are dubbed, for the detail page's dub-only episode
        list. Asked every time rather than trusted from the card that opened
        the page: many ways in (Continue Watching, AniList rows) carry no
        counts at all, and a dub gains episodes weekly."""
        def work() -> tuple[int, int] | None:
            return source.get_audio_counts(slug_id, self._http)

        def done(counts: tuple[int, int] | None) -> None:
            if counts is not None:
                self._audio_counts[slug_id] = counts
                self.audioCountsReady.emit(slug_id, counts[0], counts[1])

        self._pool.start(_Worker(work, done, lambda _msg: None))

    def _maybe_fetch_filler_fallback(self, slug_id: str) -> None:
        """If the source reported no filler episodes for the anime currently
        loaded on DetailPage, and we know its MAL id, try Jikan instead (see
        sources/jikan.py for why). No-ops until both pieces of info are in,
        since episodes and the AniList match resolve on separate async paths
        that can finish in either order."""
        anime = self._current_anime
        if anime is None or anime["slug_id"] != slug_id:
            return
        if anime.get("has_filler_data") is not False:  # None (unknown yet) or True (no fallback needed)
            return
        mal_id = anime.get("mal_id")
        if not mal_id or anime.get("_filler_fallback_started"):
            return
        anime["_filler_fallback_started"] = True

        # Kept for a week: filler is decided once a show airs, and a long
        # show costs a dozen paced requests to learn it.
        key = f"filler_{mal_id}"
        cached = self._db.get_setting(key)
        stamp = self._db.get_setting(key + "_at")
        try:
            if cached is not None and stamp and time.time() - float(stamp) <= self._STATIC_LIST_MAX_AGE:
                numbers = json.loads(cached)
                anime["jikan_filler"] = set(numbers)
                self._db.set_setting(f"filler_slug:{slug_id}", cached)
                if numbers:
                    self.fillerEpisodesUpdated.emit(numbers)
                return
        except (ValueError, json.JSONDecodeError):
            pass

        def work() -> set[int]:
            return jikan.get_filler_episodes(mal_id, self._http)

        def done(filler_numbers: set[int]) -> None:
            numbers = sorted(filler_numbers)
            anime["jikan_filler"] = set(numbers)
            self._db.set_setting(key, json.dumps(numbers))
            # Also by source slug, for the background auto-download, which
            # knows the slug but not the MAL id.
            self._db.set_setting(f"filler_slug:{slug_id}", json.dumps(numbers))
            self._db.set_setting(key + "_at", str(time.time()))
            if numbers:
                self.fillerEpisodesUpdated.emit(numbers)

        self._pool.start(_Worker(work, done, lambda _msg: None))

    @Slot(int, float, bool)
    def loadStream(self, episode_id: int, episode_number: float, dub: bool = False) -> None:
        anime_snapshot = dict(self._current_anime) if self._current_anime else None
        preferred = self.getPreferredQuality()
        if self._current_anime is not None:
            self._current_anime["current_episode_number"] = episode_number

        # A saved copy wins over resolving a stream: it is faster, it is the
        # only thing that works offline, and the stream URL it was built from
        # has very likely expired by now anyway.
        saved = self._db.get_download(episode_id, dub)
        if saved is not None and saved.status == "ready":
            self._progressReady.emit(episode_id, episode_number)
            # AniList hears about it once it's watched (episodeWatched), not
            # when it starts -- starting episode 5 used to mark 5 done.
            self._now_playing = {"kind": "file", "path": saved.path,
                                 "subtitle_path": saved.subtitle_path or ""}
            self.streamReady.emit(
                Path(saved.path).as_uri(),
                "",
                Path(saved.subtitle_path).as_uri() if saved.subtitle_path else "",
            )
            # No variants to choose between in a file that was saved at one
            # quality -- the selector stays empty rather than offering
            # switches that would silently do nothing.
            self.streamQualitiesAvailable.emit([])
            saved_times = load_skip_times(saved.path)
            if saved_times:
                self.skipTimesReady.emit(saved_times)
            else:
                self._maybe_fetch_skip_times(episode_number)
            # A dub saved before downloads kept the English track: add it
            # now, if we're online.
            if dub:
                self._maybe_add_english_to_dub(episode_id, episode_number, saved.subtitle_path, "")
            return

        def finish_up(info: source.StreamInfo) -> None:
            self._progressReady.emit(episode_id, episode_number)
            # AniList hears about it once it's watched (episodeWatched), not
            # when it starts -- starting episode 5 used to mark 5 done.
            # The source hands back the MAL id with the stream, which is often
            # the only place we get one: the AniList path only supplies it when
            # the user is logged in and the title matched. Feeding it back here
            # is what lets ani-skip and the Jikan filler lookup work logged-out.
            self._adopt_mal_id(info.mal_id)
            self._emit_skip_times(info, episode_number)
            if dub:
                self._maybe_add_english_to_dub(episode_id, episode_number, info.subtitle_url, info.referer)

        if preferred and preferred.lower() != "auto":
            # A specific quality is remembered: resolve everything up front (3
            # requests) so there's exactly one mpv.play() call, already at that
            # quality. A previous version of this started fast (Auto) and then
            # silently reloaded once the preference could be applied -- two
            # mpv.play() calls in quick succession, which is what was actually
            # behind episodes getting stuck at 0:00, not the slower request
            # count. One load, even if it takes a little longer to appear, is
            # far more reliable than load-then-immediately-reload.
            def work_specific() -> source.StreamInfo:
                return source.resolve_stream(episode_id, self._http, dub=dub)

            def done_specific(info: source.StreamInfo) -> None:
                self._current_stream_info = info
                chosen = next((v.url for v in info.variants if v.resolution == preferred), info.master_url)
                self._emit_stream(chosen, info)
                self.streamQualitiesAvailable.emit([{"label": v.resolution} for v in info.variants])
                finish_up(info)

            self._pool.start(_Worker(work_specific, done_specific, self.streamFailed.emit))
            return

        # No preference ("Auto"): fast path -- 2 requests, one load. The
        # quality list is still fetched afterward for the selector, but that
        # fetch only ever populates the dropdown -- it must never itself call
        # streamReady, or we're right back to the double-load problem above.
        def work_auto() -> source.StreamInfo:
            return source.resolve_source(episode_id, self._http, dub=dub)

        def done_auto(info: source.StreamInfo) -> None:
            self._current_stream_info = info
            self._emit_stream(info.master_url, info)
            finish_up(info)
            self._fetch_stream_variants(info)

        self._pool.start(_Worker(work_auto, done_auto, self.streamFailed.emit))

    def _emit_stream(self, url: str, info: source.StreamInfo) -> None:
        """Single place that hands a URL to the player, so the referer and
        subtitle track can never be accidentally dropped on one of the paths
        (initial load / quality switch) -- without them the stream either
        403s outright or plays with no subtitles. See sources/hianime.py."""
        self._now_playing = {"kind": "hls", "url": url, "referer": info.referer,
                             "subtitle_url": info.subtitle_url or ""}
        self.streamReady.emit(url, info.referer, info.subtitle_url or "")

    def _adopt_mal_id(self, mal_id: int | None) -> None:
        """Records a MAL id learned from the stream source, if we didn't have
        one, and kicks off the lookups that were waiting on it."""
        anime = self._current_anime
        if anime is None or not mal_id or anime.get("mal_id"):
            return
        anime["mal_id"] = mal_id
        self._maybe_fetch_filler_fallback(anime["slug_id"])

    def _emit_skip_times(self, info: source.StreamInfo, episode_number: float) -> None:
        """The source ships its own intro/outro timings with the stream, at no
        extra request and specific to the exact episode being played, so those
        are used when present. ani-skip stays as the fallback for episodes the
        source has no timings for."""
        times = self._skip_times_of(info)
        if times:
            self.skipTimesReady.emit(times)
            return
        self._maybe_fetch_skip_times(episode_number)

    @staticmethod
    def _skip_times_of(info: source.StreamInfo) -> dict[str, dict[str, float]]:
        times = {}
        if info.skip_intro:
            times["op"] = {"start": info.skip_intro[0], "end": info.skip_intro[1]}
        if info.skip_outro:
            times["ed"] = {"start": info.skip_outro[0], "end": info.skip_outro[1]}
        return times

    def _maybe_fetch_skip_times(self, episode_number: float) -> None:
        """No-ops until mal_id is known -- see _resolve_current_anime_status,
        which also calls this once mal_id first arrives, since that can
        resolve after loadStream() has already started playback (same
        two-async-paths coordination as _maybe_fetch_filler_fallback)."""
        anime = self._current_anime
        if anime is None:
            return
        mal_id = anime.get("mal_id")
        if not mal_id:
            return
        cache_key = (anime.get("slug_id"), episode_number)
        if anime.get("_skip_times_fetched_for") == cache_key:
            return
        anime["_skip_times_fetched_for"] = cache_key

        def work() -> dict[str, aniskip.SkipInterval]:
            return aniskip.get_skip_times(mal_id, episode_number, self._http)

        def done(times: dict[str, aniskip.SkipInterval]) -> None:
            if not times:
                return
            self.skipTimesReady.emit({k: {"start": v.start, "end": v.end} for k, v in times.items()})

        self._pool.start(_Worker(work, done, lambda _msg: None))

    @Slot(float, bool)
    def loadNextEpisode(self, current_episode_number: float, dub: bool = False) -> None:
        """Used for auto-play-next: finds the smallest episode number greater
        than the one just finished, from the episode list already fetched by
        loadEpisodes(), and loads it exactly like a manual episode click
        would. Emits noNextEpisode if there isn't one (last episode, or the
        episode list somehow isn't loaded)."""
        anime = self._current_anime
        episodes = anime.get("episodes") if anime else None
        if not episodes:
            self.noNextEpisode.emit()
            return
        candidates = sorted((e for e in episodes if e.number > current_episode_number), key=lambda e: e.number)
        # Filler is skipped here, on the way to the next episode -- never by
        # hiding it: clicking a filler episode on purpose still plays it.
        if self._skips_filler(anime):
            canon = [e for e in candidates if not self._is_filler(anime, e)]
            candidates = canon or candidates
        if not candidates:
            self.noNextEpisode.emit()
            return
        next_episode = candidates[0]
        self.nextEpisodeLoading.emit(next_episode.episode_id, next_episode.number)
        self.loadStream(next_episode.episode_id, next_episode.number, dub)

    @staticmethod
    def _is_filler(anime: dict[str, Any], episode: source.Episode) -> bool:
        # The source's own flag, or Jikan's list for shows the source leaves
        # unflagged (One Piece among them).
        return episode.filler or int(episode.number) in (anime.get("jikan_filler") or ())

    def _skips_filler(self, anime: dict[str, Any] | None) -> bool:
        return bool(anime) and self._db.get_show_prefs(anime["slug_id"])[1]

    # -- Per-show preferences ---------------------------------------------------

    @Slot(str, result="QVariantMap")
    def showPrefs(self, slug_id: str) -> dict[str, Any]:
        dub, skip_filler = self._db.get_show_prefs(slug_id)
        # -1 for "never chosen": QML has no None to compare a bool against.
        return {"dub": -1 if dub is None else int(dub), "skip_filler": skip_filler}

    @Slot(str, bool)
    def setShowDub(self, slug_id: str, dub: bool) -> None:
        if slug_id:
            self._db.set_show_dub(slug_id, dub)

    @Slot(str, bool)
    def setSkipFiller(self, slug_id: str, skip: bool) -> None:
        if slug_id:
            self._db.set_skip_filler(slug_id, skip)

    @Slot(float, bool)
    def loadPreviousEpisode(self, current_episode_number: float, dub: bool = False) -> None:
        """Mirror of loadNextEpisode, for the remote's Previous button."""
        anime = self._current_anime
        episodes = anime.get("episodes") if anime else None
        if not episodes:
            self.noNextEpisode.emit()
            return
        candidates = sorted(
            (e for e in episodes if e.number < current_episode_number), key=lambda e: e.number, reverse=True
        )
        if not candidates:
            self.noNextEpisode.emit()
            return
        prev_episode = candidates[0]
        self.nextEpisodeLoading.emit(prev_episode.episode_id, prev_episode.number)
        self.loadStream(prev_episode.episode_id, prev_episode.number, dub)

    def _fetch_stream_variants(self, info: source.StreamInfo) -> None:
        """Populates the quality selector only. Deliberately never emits
        streamReady itself -- see the comment in loadStream()."""

        def work() -> tuple[source.StreamVariant, ...]:
            return source.get_stream_variants(info.master_url, self._http, referer=info.referer)

        def done(variants: tuple[source.StreamVariant, ...]) -> None:
            if self._current_stream_info and self._current_stream_info.master_url == info.master_url:
                self._current_stream_info = replace(info, variants=variants)
            self.streamQualitiesAvailable.emit([{"label": v.resolution} for v in variants])

        self._pool.start(_Worker(work, done, lambda _msg: None))

    @Slot(str)
    def selectQuality(self, resolution: str) -> None:
        """Switches to a specific resolution using the variants already fetched
        by loadStream -- no new network round trip. Empty/'Auto' goes back to
        the adaptive master playlist (mpv picks/switches quality itself). Also
        remembered as the preferred quality for future episodes."""
        self._db.set_setting("preferred_quality", resolution or "Auto")
        if self._current_stream_info is None:
            return
        info = self._current_stream_info
        if not resolution or resolution.lower() == "auto":
            self._emit_stream(info.master_url, info)
            return
        for variant in info.variants:
            if variant.resolution == resolution:
                self._emit_stream(variant.url, info)
                return

    @Slot(result=str)
    def getPreferredQuality(self) -> str:
        return self._db.get_setting("preferred_quality") or "Auto"

    # -- playback settings: intro/outro auto-skip, auto-next-episode --------

    @Slot(result=bool)
    def getAutoSkipEnabled(self) -> bool:
        return (self._db.get_setting("auto_skip_enabled") or "true") == "true"

    @Slot(bool)
    def setAutoSkipEnabled(self, value: bool) -> None:
        self._db.set_setting("auto_skip_enabled", "true" if value else "false")

    @Slot(result=bool)
    def getSkipFinalEpisodeEnabled(self) -> bool:
        # Defaults off: watching the true last opening/ending without it being
        # auto-skipped is a deliberate, commonly-wanted exception -- nothing
        # left to spoil once you're on the last episode.
        return (self._db.get_setting("skip_final_episode_enabled") or "false") == "true"

    @Slot(bool)
    def setSkipFinalEpisodeEnabled(self, value: bool) -> None:
        self._db.set_setting("skip_final_episode_enabled", "true" if value else "false")

    # -- English subtitles on dubs ------------------------------------------
    #
    # A dub stream's own subtitle file is often just songs and signs --
    # measured: Frieren's has 55 lines (the opening lyrics and on-screen
    # text), Dorohedoro's has none -- while the subbed version always carries
    # full English dialogue. They are the same video (sub and dub playlists
    # matched to 0.04 s), so the subbed version's English lines up. Its
    # wording follows the Japanese script, not the dub's, so it won't match
    # the spoken English word for word.

    dubEnglishReady = Signal(str)  # subtitle URL to add to the dub playing

    @Slot(result=bool)
    def getDubEnglishEnabled(self) -> bool:
        return (self._db.get_setting("dub_english") or "true") == "true"

    @Slot(bool)
    def setDubEnglishEnabled(self, value: bool) -> None:
        self._db.set_setting("dub_english", "true" if value else "false")

    def _dub_english_url(self, episode_id: int, dub_subtitle: str | None, dub_referer: str) -> str:
        """The subbed version's English track for a dub episode, when the
        dub's own is missing or only a fraction of the lines (songs and
        signs). "" when the dub's own is real dialogue. Blocks: worker
        threads only. dub_subtitle may be a URL or a saved file."""
        from animeplayer.learn import subtitles

        def lines(where: str, referer: str) -> int:
            if Path(where).exists():
                data = Path(where).read_bytes()
            else:
                response = self._http.get(where, timeout=20, headers={"Referer": referer})
                response.raise_for_status()
                data = response.content
            return len(subtitles.parse("s.vtt", data))

        sub_info = source.resolve_source(episode_id, self._http, dub=False)
        if not sub_info.subtitle_url:
            return ""
        if dub_subtitle and lines(dub_subtitle, dub_referer) >= 0.6 * lines(sub_info.subtitle_url, sub_info.referer):
            return ""
        return sub_info.subtitle_url

    def _maybe_add_english_to_dub(self, episode_id: int, episode_number: float,
                                  dub_subtitle: str | None, dub_referer: str) -> None:
        if not self.getDubEnglishEnabled():
            return

        def work() -> str:
            return self._dub_english_url(episode_id, dub_subtitle, dub_referer)

        def done(url: str) -> None:
            current = self._current_anime or {}
            if url and current.get("current_episode_number") == episode_number:
                self.dubEnglishReady.emit(url)

        self._pool.start(_Worker(work, done, lambda _msg: None))

    @Slot(result="QVariantMap")
    def subtitleStyle(self) -> dict[str, Any]:
        """Subtitle size (1.0 = default) and vertical position (100 = bottom
        edge; smaller moves them up), as last chosen."""
        try:
            scale = float(self._db.get_setting("sub_scale") or 1.0)
            position = int(self._db.get_setting("sub_pos") or 100)
        except ValueError:
            scale, position = 1.0, 100
        return {"scale": scale, "position": position}

    @Slot(float, int)
    def setSubtitleStyle(self, scale: float, position: int) -> None:
        self._db.set_setting("sub_scale", f"{scale:.2f}")
        self._db.set_setting("sub_pos", str(int(position)))

    @Slot(result=bool)
    def getAutoNextEnabled(self) -> bool:
        return (self._db.get_setting("auto_next_enabled") or "true") == "true"

    @Slot(bool)
    def setAutoNextEnabled(self, value: bool) -> None:
        self._db.set_setting("auto_next_enabled", "true" if value else "false")

    # -- Downloads ----------------------------------------------------------
    #
    # An episode saved here is played from disk instead of being resolved
    # again, which is both faster and the only thing that works with no
    # network. By default an episode deletes itself once it has been watched
    # (see episodeWatched) -- that is what the feature was asked for.

    def _download_card(self, entry: DownloadEntry, episode_count: int = 0) -> dict[str, Any]:
        return {
            "episode_id": entry.episode_id,
            "dub": entry.dub,
            "slug_id": entry.slug_id,
            "numeric_id": entry.numeric_id,
            "title": entry.anime_title,
            "poster_url": entry.poster_url or "",
            "episode_number": entry.episode_number,
            "status": entry.status,
            "bytes": entry.bytes,
            "message": entry.message,
            "episode_count": episode_count,
        }

    @Slot(result=bool)
    def canDownload(self) -> bool:
        """Whether saving episodes is possible at all. The UI hides its
        download controls when it isn't, rather than offering a button that
        can only ever report the same failure."""
        return ffmpeg_available()

    @Slot(str, result=list)
    def downloadsFor(self, slug_id: str) -> list[dict[str, Any]]:
        return [self._download_card(e) for e in self._db.downloads_for(slug_id)]

    @Slot(result=list)
    def allDownloads(self) -> list[dict[str, Any]]:
        return [self._download_card(e) for e in self._db.all_downloads()]

    # float, not int: Qt's int is 32-bit, and past 2 GB saved the number
    # didn't make it to QML at all ("Error" on the Settings page).
    @Slot(result=float)
    def downloadBytes(self) -> float:
        files: list[str] = []
        for e in self._db.all_downloads():
            if e.status == "ready":
                files += [e.path, *([e.subtitle_path] if e.subtitle_path else [])]
        return disk_usage(files)

    # -- where downloads go --------------------------------------------------

    downloadFolderMoved = Signal(str)  # a message for the Settings page

    @Slot(result=str)
    def downloadFolder(self) -> str:
        return str(downloads_module.DOWNLOAD_DIR)

    @Slot(result=str)
    def downloadFolderUrl(self) -> str:
        from PySide6.QtCore import QUrl
        return QUrl.fromLocalFile(str(downloads_module.DOWNLOAD_DIR)).toString()

    @Slot(result=bool)
    def isDefaultDownloadFolder(self) -> bool:
        return downloads_module.DOWNLOAD_DIR == downloads_module.DEFAULT_DOWNLOAD_DIR

    @Slot(str, bool)
    def setDownloadFolder(self, folder: str, move_existing: bool) -> None:
        """folder: a path or a file:// URL (from the folder picker); "" goes
        back to the default. With move_existing, episodes already saved move
        there too, in the background."""
        if folder.startswith("file:"):
            from PySide6.QtCore import QUrl
            folder = QUrl(folder).toLocalFile()
        target = Path(folder) if folder else downloads_module.DEFAULT_DOWNLOAD_DIR
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".animeplayer-write-test"
            probe.write_text("")
            probe.unlink()
        except OSError as exc:
            self.downloadFolderMoved.emit(f"Can't save there: {exc.strerror or exc}")
            return
        if folder and target != downloads_module.DEFAULT_DOWNLOAD_DIR:
            self._db.set_setting("download_dir", str(target))
        else:
            self._db.delete_setting("download_dir")
        downloads_module.set_download_dir(target)
        if not move_existing:
            self.downloadFolderMoved.emit(f"New downloads go to {target}")
            return

        def work() -> tuple[int, int]:
            moved = failed = 0
            for entry in self._db.all_downloads():
                if entry.status != "ready" or Path(entry.path).parent.parent == target:
                    continue
                try:
                    video, subtitle, _skip = downloads_module.move_episode(
                        [entry.path, entry.subtitle_path, str(skip_times_path(entry.path))], target)
                    self._db.upsert_download(replace(entry, path=video, subtitle_path=subtitle))
                    moved += 1
                except OSError:
                    failed += 1
            return moved, failed

        def done(result: tuple[int, int]) -> None:
            moved, failed = result
            text = (f"Moved {moved} episode{'s' if moved != 1 else ''} to {target}" if moved
                    else f"Everything saved is already in {target}")
            if failed:
                text += f" ({failed} couldn't be moved and stayed where they were)"
            self.downloadFolderMoved.emit(text)
            self.downloadsChanged.emit()

        self.downloadFolderMoved.emit("Moving your saved episodes...")
        self._pool.start(_Worker(work, done, self.downloadFolderMoved.emit))

    @Slot()
    def openDownloadFolder(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        downloads_module.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(downloads_module.DOWNLOAD_DIR)))

    @Slot(int, bool, result=bool)
    def isDownloaded(self, episode_id: int, dub: bool) -> bool:
        entry = self._db.get_download(episode_id, dub)
        return entry is not None and entry.status == "ready"

    @Slot(dict)
    def downloadEpisode(self, spec: dict[str, Any]) -> None:
        """Queues one episode. spec carries what the detail page already knows
        about it, so the worker never has to re-resolve the anime itself."""
        self._queue_download(spec)
        self.downloadsChanged.emit()

    @Slot(list)
    def downloadEpisodes(self, specs: list[Any]) -> None:
        """Queues a whole season at once. Each is an independent job, so one
        episode failing doesn't take the rest of the season with it."""
        for spec in specs:
            self._queue_download(dict(spec))
        self.downloadsChanged.emit()

    def _queue_download(self, spec: dict[str, Any]) -> None:
        request = DownloadRequest(
            episode_id=int(spec.get("episode_id") or 0),
            dub=bool(spec.get("dub")),
            slug_id=str(spec.get("slug_id") or ""),
            numeric_id=str(spec.get("numeric_id") or ""),
            anime_title=str(spec.get("title") or "Unknown"),
            poster_url=str(spec.get("poster_url") or ""),
            episode_number=float(spec.get("episode_number") or 0),
        )
        if not request.episode_id:
            return
        existing = self._db.get_download(request.episode_id, request.dub)
        if existing is not None and existing.status in ("ready", "queued", "downloading"):
            return

        self._downloader.clear_cancelled(request.episode_id, request.dub)
        destination = target_path(request)
        self._db.upsert_download(
            DownloadEntry(
                episode_id=request.episode_id, dub=request.dub, slug_id=request.slug_id,
                numeric_id=request.numeric_id, anime_title=request.anime_title,
                poster_url=request.poster_url, episode_number=request.episode_number,
                path=str(destination), subtitle_path=None, status="queued",
                bytes=0, message="", created_at=time.time(),
            )
        )
        with self._download_lock:
            self._pending_downloads.append((request, destination))
        # One "run whatever is first in line" job per queued episode, rather
        # than a job bound to this episode: that is what lets the queue be
        # reordered after the fact (see moveDownload).
        self._download_pool.start(_Worker(self._run_next_download, self._download_finished,
                                          lambda _msg: self.downloadsChanged.emit()))

    def _run_next_download(self) -> tuple[DownloadRequest, str] | None:
        """On the download thread. Returns (request, error or "")."""
        with self._download_lock:
            if not self._pending_downloads:
                return None
            request, destination = self._pending_downloads.pop(0)
            self._active_download = request
        try:
            # Twice more on failure, each with a fresh link after a pause:
            # most failures are a CDN hiccup or an expired link, and a
            # queue of ten shouldn't need babysitting because of one.
            for attempt in range(3):
                try:
                    self._run_download(request, destination)
                    return request, ""
                except Exception as exc:  # noqa: BLE001 -- reported per episode below
                    if str(exc) == "cancelled" or attempt == 2 \
                            or self._downloader.is_cancelled(request.episode_id, request.dub):
                        return request, str(exc)
                    time.sleep(5 * (attempt + 1))
            return request, "failed"
        finally:
            with self._download_lock:
                self._active_download = None

    def _download_finished(self, result: tuple[DownloadRequest, str] | None) -> None:
        if result is not None:
            request, error = result
            # "cancelled" is the user's own doing, not something to report at
            # them -- the row is already gone by the time this runs.
            if error and error != "cancelled":
                self._db.set_download_status(request.episode_id, request.dub, "failed",
                                             message=error)
                self.downloadFailed.emit(f"{request.anime_title} episode "
                                         f"{request.episode_number:g}: {error}")
        self.downloadsChanged.emit()

    @Slot(result=list)
    def downloadQueue(self) -> list[dict[str, Any]]:
        """What's downloading now, then what's waiting, in the order they'll run."""
        with self._download_lock:
            order = ([self._active_download] if self._active_download else []) \
                + [r for r, _ in self._pending_downloads]
        cards = []
        for request in order:
            entry = self._db.get_download(request.episode_id, request.dub)
            if entry is not None:
                cards.append(self._download_card(entry))
        return cards

    @Slot(int, bool, int)
    def moveDownload(self, episode_id: int, dub: bool, to_index: int) -> None:
        """Moves a waiting episode to position to_index in the line (0 = next)."""
        with self._download_lock:
            index = next((i for i, (r, _) in enumerate(self._pending_downloads)
                          if r.episode_id == episode_id and r.dub == dub), None)
            if index is None:
                return
            item = self._pending_downloads.pop(index)
            to_index = max(0, min(to_index, len(self._pending_downloads)))
            self._pending_downloads.insert(to_index, item)
        self.downloadsChanged.emit()

    @Slot(int, bool)
    def retryDownload(self, episode_id: int, dub: bool) -> None:
        entry = self._db.get_download(episode_id, dub)
        if entry is None or entry.status != "failed":
            return
        self._db.delete_download(episode_id, dub)
        self.downloadEpisode({
            "episode_id": entry.episode_id, "dub": entry.dub, "slug_id": entry.slug_id,
            "numeric_id": entry.numeric_id, "title": entry.anime_title,
            "poster_url": entry.poster_url, "episode_number": entry.episode_number,
        })

    DOWNLOAD_READRATE_WHILE_PLAYING = 3.0

    def _run_download(self, request: DownloadRequest, destination: Path) -> None:
        """Runs on the download thread. Raises to report failure -- _Worker
        turns that into the failed() callback above."""
        if self._downloader.is_cancelled(request.episode_id, request.dub):
            raise DownloadError("cancelled")

        self._db.set_download_status(request.episode_id, request.dub, "downloading")
        self.downloadsChanged.emit()

        info = source.resolve_stream(request.episode_id, self._http, dub=request.dub)
        # Save the best single rendition rather than the adaptive master: an
        # mp4 built from a master playlist ends up with every variant's tracks
        # muxed in, which is three times the size for one watchable video.
        url = info.variants[0].url if info.variants else info.master_url
        duration = probe_duration(url, info.referer)

        # The subtitle and the skip times first: small, and fetched from the
        # same resolve as the video, so they shouldn't wait behind a download
        # that can take ten minutes on a slow CDN day.
        destination.parent.mkdir(parents=True, exist_ok=True)
        subtitle_url, subtitle_referer = info.subtitle_url, info.referer
        # A dub's own track is often only the songs, or nothing: keep the
        # subbed version's English instead, as playback would show.
        if request.dub and self.getDubEnglishEnabled():
            try:
                english = self._dub_english_url(request.episode_id, info.subtitle_url, info.referer)
            except Exception:  # noqa: BLE001 -- the dub's own track still goes in
                english = ""
            if english:
                subtitle_url = english
        subtitle_path = None
        if subtitle_url:
            subtitle_path = download_subtitle(
                subtitle_url, destination.with_suffix(".vtt"), self._http,
                referer=subtitle_referer,
            )
        save_skip_times(destination, self._skip_times_of(info))

        def on_progress(fraction: float, written: int) -> None:
            # Already throttled to roughly one call per percent by the
            # downloader -- see the note in Downloader.fetch.
            self.downloadProgress.emit(request.episode_id, request.dub, fraction, written)

        # Held to a few times playback speed while an episode is playing, so
        # a queue of background downloads never starves the stream being
        # watched. Still far faster than watching -- a 24-minute episode
        # takes about eight -- and unthrottled the moment nothing is playing.
        readrate = self.DOWNLOAD_READRATE_WHILE_PLAYING if self._playing else 0.0
        try:
            self._downloader.fetch(url, info.referer, destination, duration, on_progress,
                                   readrate=readrate)
        except DownloadError:
            delete_files(subtitle_path, skip_times_path(destination))
            raise

        self._db.upsert_download(
            DownloadEntry(
                episode_id=request.episode_id, dub=request.dub, slug_id=request.slug_id,
                numeric_id=request.numeric_id, anime_title=request.anime_title,
                poster_url=request.poster_url, episode_number=request.episode_number,
                path=str(destination), subtitle_path=str(subtitle_path) if subtitle_path else None,
                status="ready", bytes=destination.stat().st_size, message="",
                created_at=time.time(),
            )
        )

    @Slot(int, bool)
    def cancelDownload(self, episode_id: int, dub: bool) -> None:
        self._downloader.cancel(episode_id, dub)
        self.removeDownload(episode_id, dub)

    @Slot(int, bool)
    def removeDownload(self, episode_id: int, dub: bool) -> None:
        entry = self._db.get_download(episode_id, dub)
        if entry is not None and entry.status in ("queued", "downloading"):
            # Still in line or running: take it out of the line too, or it
            # would download anyway into a row that no longer exists.
            self._downloader.cancel(episode_id, dub)
            with self._download_lock:
                self._pending_downloads = [(r, d) for r, d in self._pending_downloads
                                           if not (r.episode_id == episode_id and r.dub == dub)]
        if entry is not None:
            delete_files(entry.path, entry.subtitle_path,
                         str(Path(entry.path).with_suffix(".part.mp4")),
                         skip_times_path(entry.path))
        self._db.delete_download(episode_id, dub)
        self.downloadsChanged.emit()

    @Slot(str)
    def removeDownloadsFor(self, slug_id: str) -> None:
        for entry in self._db.downloads_for(slug_id):
            self.removeDownload(entry.episode_id, entry.dub)

    @Slot(result=bool)
    def getDeleteAfterWatchingEnabled(self) -> bool:
        return (self._db.get_setting("delete_after_watching") or "true") == "true"

    @Slot(bool)
    def setDeleteAfterWatchingEnabled(self, value: bool) -> None:
        self._db.set_setting("delete_after_watching", "true" if value else "false")

    @Slot(int, bool)
    def episodeWatched(self, episode_id: int, dub: bool) -> None:
        """Called by the player once an episode has actually been watched
        through.

        Deletes saved episodes *older than the previous one*, rather than the
        one just finished: watch 3 and episode 1 goes, while 2 and 3 stay for
        a quick rewind or a rewatch of the ending. Streamed episodes count
        too -- watching 3 online still clears a saved 1.

        Then, for a show with auto-download on, tops the queue back up."""
        anime = self._current_anime
        episodes = (anime or {}).get("episodes") or []
        watched = next((e for e in episodes if e.episode_id == episode_id), None)
        if anime is None or watched is None:
            # Nothing to reason about neighbours with; fall back to this one.
            if self.getDeleteAfterWatchingEnabled() and self._db.get_download(episode_id, dub):
                self.removeDownload(episode_id, dub)
            return

        slug_id = anime["slug_id"]
        self._record_watch_event(slug_id, anime.get("title") or "", watched.number)
        # Now it counts on AniList. If the AniList match hasn't arrived yet,
        # it's remembered and sent when it does (_resolve_current_anime_status).
        anime["_watched_number"] = watched.number
        if self._anilist_client is not None and anime.get("anilist_id"):
            self._push_anilist_progress(dict(anime), watched.number)
        self._maybe_ask_for_rating(anime, watched.number)

        if self.getDeleteAfterWatchingEnabled():
            earlier = sorted(e.number for e in episodes if e.number < watched.number)
            keep_from = earlier[-1] if earlier else watched.number
            for entry in self._db.downloads_for(slug_id):
                if entry.dub == dub and entry.status == "ready" and entry.episode_number < keep_from:
                    self.removeDownload(entry.episode_id, entry.dub)

        auto_dub = self._db.get_auto_download(slug_id)
        if auto_dub is not None:
            self._top_up_auto_download(after=watched.number, dub=auto_dub)

    # -- New-episode alerts -------------------------------------------------
    #
    # Follows everything in Continue Watching -- local progress and the
    # AniList Watching list alike -- and asks AniList how far each has aired.
    # A show with an aired episode you haven't watched goes in a row on the
    # home page; one that aired since the last check also gets a desktop
    # notification. AniList's schedule is the sub's: it has no dub data.

    NEW_EPISODE_CHECK_MS = 30 * 60 * 1000

    @Slot(result=bool)
    def getNewEpisodeAlertsEnabled(self) -> bool:
        return (self._db.get_setting("new_episode_alerts") or "true") == "true"

    @Slot(bool)
    def setNewEpisodeAlertsEnabled(self, value: bool) -> None:
        self._db.set_setting("new_episode_alerts", "true" if value else "false")
        if not value:
            self._new_episodes = []
            self.newEpisodesChanged.emit([])
        else:
            self.checkNewEpisodes()

    @Slot(result=list)
    def newEpisodes(self) -> list[dict[str, Any]]:
        return self._new_episodes

    def _followed_shows(self) -> dict[int, tuple[int, str, str]]:
        """anilist id -> (episodes watched, source slug or "", title as shown
        in Continue Watching), for everything there that can be tied to an
        AniList entry."""
        meta = self._db.anime_meta()
        followed: dict[int, tuple[int, str, str]] = {}
        for row in self._continue_watching_rows():
            anilist_id = row["anilist_id"] or (meta.get(row["slug_id"]) or ("", None))[1]
            if not anilist_id:
                continue
            number = row["episode_number"]
            # Local progress points at the episode being watched: it counts
            # as seen only once it's nearly over.
            if row["slug_id"] and not (row["duration_seconds"] > 0
                                       and row["position_seconds"] >= row["duration_seconds"] * 0.9):
                number -= 1
            watched = int(max(0, number))
            previous = followed.get(anilist_id)
            if previous is None or watched > previous[0]:
                followed[anilist_id] = (watched, row["slug_id"] or (previous[1] if previous else ""),
                                        row["title"])
        return followed

    @Slot()
    def checkNewEpisodes(self) -> None:
        if not self.getNewEpisodeAlertsEnabled():
            return
        followed = self._followed_shows()
        if not followed:
            return

        def work() -> list[AiringState]:
            return self._anilist_public.get_airing(list(followed))

        def done(airing: list[AiringState]) -> None:
            watched = {media_id: entry[0] for media_id, entry in followed.items()}
            waiting, announce, updates = find_new_episodes(airing, watched, self._db.airing_seen())
            for media_id, episode in updates.items():
                self._db.set_airing_seen(media_id, episode)
            self._new_episodes = [
                self._card(
                    anilist_id=n.state.media.id,
                    slug_id=followed[n.state.media.id][1],
                    numeric_id=followed[n.state.media.id][1].rsplit("-", 1)[-1]
                    if followed[n.state.media.id][1] else "",
                    # The name it has in Continue Watching, not AniList's:
                    # the same show under two spellings reads as two shows.
                    title=followed[n.state.media.id][2] or n.state.media.title,
                    poster_url=n.state.media.cover_url or "",
                    reason=(f"Episode {n.state.latest_aired} is out" if n.unwatched == 1
                            else f"Ep {n.state.latest_aired} out · {n.unwatched} to catch up"),
                    # For the card's countdown to the next one.
                    next_episode=n.state.next_episode or 0,
                    next_airing_at=n.state.next_airing_at or 0,
                )
                for n in waiting
            ]
            self.newEpisodesChanged.emit(self._new_episodes)
            self._check_source_side(followed)
            for n in announce:
                _notify_desktop(
                    followed[n.state.media.id][2] or n.state.media.title,
                    f"Episode {n.state.latest_aired} is out"
                    + (f" · {n.unwatched} to catch up on" if n.unwatched > 1 else ""),
                )

        self._pool.start(_Worker(work, done, lambda _msg: None))

    def _check_source_side(self, followed: dict[int, tuple[int, str, str]]) -> None:
        """The half of the new-episode check that asks the streaming source
        rather than AniList: how many episodes are dubbed (AniList doesn't
        know), and -- for shows with auto-download on -- the fresh episode
        list, so an episode that just aired is queued without anyone opening
        the show. One or two small requests per followed show, every half
        hour."""
        shows = []
        for anilist_id, (watched, slug_id, title) in followed.items():
            if not slug_id:
                # AniList-only rows (never played here) still have a source
                # match cached from when they were last opened.
                mapping = self._db.get_anidb_mapping(anilist_id)
                slug_id = mapping.slug_id if mapping is not None else ""
            if slug_id:
                shows.append((slug_id, title, watched, self._db.get_auto_download(slug_id)))
        if not shows:
            return

        def work() -> list[tuple[str, str, int, bool | None, tuple[int, int] | None, list]]:
            out = []
            for slug_id, title, watched, auto_dub in shows:
                try:
                    counts = source.get_audio_counts(slug_id, self._http)
                    episodes = (source.get_episodes(slug_id, self._http)
                                if auto_dub is not None else [])
                except httpx.HTTPError:
                    continue
                out.append((slug_id, title, watched, auto_dub, counts, episodes))
            return out

        def done(results: list) -> None:
            for slug_id, title, watched, auto_dub, counts, episodes in results:
                if counts is not None:
                    self._audio_counts[slug_id] = counts
                    self._maybe_announce_dub(slug_id, title, watched, counts[1])
                if auto_dub is not None and episodes:
                    meta = self._db.anime_meta().get(slug_id)
                    progress = self._db.get_progress(slug_id)
                    anime = {
                        "slug_id": slug_id,
                        "numeric_id": slug_id.rsplit("-", 1)[-1],
                        "title": (progress.anime_title if progress else "") or title
                                 or (meta[0] if meta else ""),
                        "poster_url": (progress.poster_url if progress else "") or "",
                        "episodes": episodes,
                        "jikan_filler": set(json.loads(
                            self._db.get_setting(f"filler_slug:{slug_id}") or "[]")),
                    }
                    after = progress.episode_number - 1e-6 if progress else float(watched)
                    self._top_up_auto_download(after=after, dub=auto_dub, anime=anime)

        self._pool.start(_Worker(work, done, lambda _msg: None))

    def _maybe_announce_dub(self, slug_id: str, title: str, watched: int, dubbed: int) -> None:
        """A dub alert: only when the dub count went up since the last check,
        and only for an episode not already watched -- a new dub of something
        seen in sub is not news."""
        key = f"dub_seen:{slug_id}"
        previous = self._db.get_setting(key)
        self._db.set_setting(key, str(dubbed))
        if previous is None or not previous.isdigit():
            return  # first sighting: record, don't announce
        if dubbed > int(previous) and dubbed > watched:
            _notify_desktop(title, f"Episode {dubbed} dub is out")

    # -- "Because you watched" ------------------------------------------------

    @Slot()
    def refreshBecauseYouWatched(self) -> None:
        """AniList's community recommendations for the show most recently
        played, minus anything already on the user's list. One request,
        cached like every other AniList read."""
        meta = self._db.anime_meta()
        seed = None
        for row in self._continue_watching_rows():
            anilist_id = row["anilist_id"] or (meta.get(row["slug_id"]) or ("", None))[1]
            if anilist_id:
                seed = (anilist_id, row["title"])
                break
        if seed is None:
            self.becauseYouWatchedReady.emit("", [])
            return
        seed_id, seed_title = seed
        known = self._anilist_known_ids() | {seed_id}

        def work() -> list[MediaSummary]:
            return list(self._anilist_public.get_media_extras(seed_id).recommendations)

        def done(recommendations: list[MediaSummary]) -> None:
            cards = [self._media_summary_to_card(m) for m in recommendations if m.id not in known]
            self.becauseYouWatchedReady.emit(seed_title, cards)

        self._pool.start(_Worker(work, done, lambda _msg: None))

    # -- Saving a poster ------------------------------------------------------

    posterSaved = Signal(str)  # the path it was saved to, or "" on failure

    @staticmethod
    def full_size_cover(url: str) -> str:
        """AniList serves each cover at three sizes and the app shows the
        middle one; this is the biggest, for the enlarged view and saving."""
        return url.replace("/cover/medium/", "/cover/large/").replace("/cover/small/", "/cover/large/")

    @Slot(str, result=str)
    def fullSizeCover(self, url: str) -> str:
        return self.full_size_cover(url)

    @Slot(str, str)
    def savePoster(self, url: str, title: str) -> None:
        """Into ~/Pictures/Anime Player, named after the show. The folder is
        the user's own, unlike downloads: a poster saved on purpose is theirs
        to keep."""
        folder = Path.home() / "Pictures" / "Anime Player"
        url = self.full_size_cover(url)

        def work() -> str:
            response = self._http.get(url, timeout=30)
            response.raise_for_status()
            suffix = Path(url.split("?")[0]).suffix or ".jpg"
            name = re.sub(r'[\\/:*?"<>|]+', " ", title).strip() or "poster"
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"{name}{suffix}"
            n = 2
            while target.exists():
                target = folder / f"{name} ({n}){suffix}"
                n += 1
            target.write_bytes(response.content)
            return str(target)

        self._pool.start(_Worker(work, self.posterSaved.emit, lambda _m: self.posterSaved.emit("")))

    # -- Watch statistics -----------------------------------------------------
    #
    # Two things are recorded, both locally and nowhere else: seconds spent
    # actually playing (reported by the player every few seconds while it
    # plays -- paused time is not watching), and each episode finished.

    def _record_watch_event(self, slug_id: str, title: str, number: float) -> None:
        self._db.add_watch_event(slug_id, title, number, time.time())

    @Slot(float)
    def addWatchTime(self, seconds: float) -> None:
        anime = self._current_anime
        if anime is None or seconds <= 0:
            return
        day = time.strftime("%Y-%m-%d")
        self._db.add_watch_time(day, anime["slug_id"], anime.get("title") or "", seconds)

    @Slot(result="QVariantMap")
    def watchStats(self) -> dict[str, Any]:
        return compute_watch_stats(
            self._db.watch_time_rows(), self._db.watch_event_rows(), self._db.anime_meta(),
            today=time.strftime("%Y-%m-%d"),
        )

    @Slot()
    def loadAnilistStats(self) -> None:
        """Stats from the AniList list itself: every finish date and rewatch
        AniList has, going back long before this app existed."""
        client, user_id = self._anilist_client, self._anilist_user_id
        if client is None or user_id is None:
            self.anilistStatsReady.emit({})
            return

        def work() -> dict[str, Any]:
            return compute_anilist_stats(client.get_watch_history(user_id),
                                         today=time.strftime("%Y-%m-%d"))

        def failed(_message: str) -> None:
            self.anilistStatsReady.emit({})

        self._pool.start(_Worker(work, self.anilistStatsReady.emit, failed))

    # -- Learn Japanese ------------------------------------------------------
    #
    # Japanese subtitles from Jimaku, split into words with readings and
    # romaji (learn/japanese.py), and a JMdict dictionary for hovering a word
    # (learn/dictionary.py). Everything is cached under the app's data folder:
    # parsed subtitles per episode, the built dictionary once.

    japaneseSubsReady = Signal("QVariantMap")   # {episode, file, cues: [{start, end, text, tokens, romaji}]}
    japaneseSubsFailed = Signal(str)
    dictionaryProgress = Signal(float)          # 0..1 while downloading; 1 while building
    dictionaryReady = Signal()
    dictionaryFailed = Signal(str)
    savedWordsChanged = Signal()

    _LEARN_DIR = DEFAULT_DB_PATH.parent / "learn"

    @property
    def _dictionary(self) -> jmdict.Dictionary:
        if getattr(self, "_jmdict", None) is None:
            self._jmdict = jmdict.Dictionary(self._LEARN_DIR / "jmdict.db")
        return self._jmdict

    @Slot(result=bool)
    def hasJimakuKey(self) -> bool:
        return bool(secrets.load_jimaku_key())

    @Slot(str)
    def setJimakuKey(self, key: str) -> None:
        secrets.save_jimaku_key(key)

    @Slot(result=str)
    def dictionaryState(self) -> str:
        if self._dictionary.ready:
            return "ready"
        return "building" if getattr(self, "_dictionary_building", False) else "missing"

    @Slot()
    def prepareDictionary(self) -> None:
        """Downloads JMdict (~10 MB) and builds the lookup database (~5 s),
        once. Everything after that is offline."""
        if self._dictionary.ready or getattr(self, "_dictionary_building", False):
            if self._dictionary.ready:
                self.dictionaryReady.emit()
            return
        self._dictionary_building = True
        folder = self._LEARN_DIR

        def work() -> None:
            folder.mkdir(parents=True, exist_ok=True)
            gz = folder / "JMdict_e.gz"
            jmdict.download(gz, self._http, on_progress=lambda f: self.dictionaryProgress.emit(min(f, 0.99)))
            self.dictionaryProgress.emit(1.0)
            jmdict.build(gz, folder / "jmdict.db")
            gz.unlink(missing_ok=True)

        def done(_result: None) -> None:
            self._dictionary_building = False
            self.dictionaryReady.emit()

        def failed(message: str) -> None:
            self._dictionary_building = False
            self.dictionaryFailed.emit("Couldn't set up the dictionary: " + message)

        self._pool.start(_Worker(work, done, failed))

    @Slot(str, str, str, result=list)
    def lookupWord(self, lemma: str, surface: str, reading: str) -> list[dict[str, Any]]:
        """Up to three entries: the dictionary form first (食べる for 食べ),
        then the word as written. The reading only when neither is found:
        looked up by sound, 誰 ("who") also brought in unrelated words that
        happen to be read だれ."""
        results = self._dictionary.lookup(lemma, surface) or self._dictionary.lookup(reading)
        return [
            {
                "word": d.kanji[0] if d.kanji else d.readings[0],
                "reading": d.readings[0] if d.readings else "",
                "common": d.common,
                "senses": [{"pos": ", ".join(pos[:2]), "glosses": "; ".join(glosses[:4])}
                           for pos, glosses in d.senses[:4]],
            }
            for d in results
        ]

    @Slot(float)
    def loadJapaneseSubs(self, episode_number: float) -> None:
        """For the episode playing now. Needs the show's AniList id, which
        can land after playback starts -- if it isn't known yet, this waits
        for _resolve_current_anime_status to call it again."""
        anime = self._current_anime
        if anime is None:
            return
        anime["_want_japanese_subs"] = episode_number
        anilist_id = anime.get("anilist_id")
        if not anilist_id:
            return
        key = secrets.load_jimaku_key()
        episode = int(episode_number)
        cache = self._LEARN_DIR / "subs" / f"{anilist_id}-{episode}.json"

        def work() -> dict[str, Any]:
            payload = json.loads(cache.read_text()) if cache.exists() else fetch()
            # Not cached with the subtitles: it depends on which release is
            # streaming, and that can change between two viewings.
            payload["offset"] = self._offset_against_english([c["start"] for c in payload["cues"]])
            return payload

        def fetch() -> dict[str, Any]:
            name, cues = jimaku.fetch_episode(self._http, key, anilist_id, episode)
            from animeplayer.learn import japanese
            payload = {
                "episode": episode_number,
                "file": name,
                "cues": [{"start": c.start, "end": c.end, "text": c.text, **japanese.analyse(c.text)}
                         for c in cues],
            }
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(payload, ensure_ascii=False))
            return payload

        def done(payload: dict[str, Any]) -> None:
            # Dropped only if a *different* episode is known to be playing
            # by now. A cached file is back before the player has even
            # registered the episode it's starting, and treating "not known
            # yet" as a mismatch silently threw that answer away.
            playing = (self._current_anime or {}).get("current_episode_number")
            if playing is None or playing == episode_number:
                self.japaneseSubsReady.emit(payload)

        def failed(message: str) -> None:
            self.japaneseSubsFailed.emit(message)

        self._pool.start(_Worker(work, done, failed))

    def _offset_against_english(self, jp_starts: list[float]) -> float | None:
        """Runs on a worker thread. How far to shift the Japanese lines to
        match the English subtitles of the stream actually playing (see
        learn/sync.py). Waits briefly for the stream to be known: the
        Japanese file can be back before the stream has resolved."""
        from animeplayer.learn import subtitles, sync
        playing = None
        for _ in range(60):
            playing = self._now_playing
            if playing is not None:
                break
            time.sleep(0.25)
        if playing is None:
            return None
        try:
            if playing.get("subtitle_path"):
                data = Path(playing["subtitle_path"]).read_bytes()
            elif playing.get("subtitle_url"):
                response = self._http.get(playing["subtitle_url"], timeout=20,
                                          headers={"Referer": playing.get("referer") or ""})
                response.raise_for_status()
                data = response.content
            else:
                return None
        except (httpx.HTTPError, OSError):
            return None
        english = subtitles.parse("english.vtt", data)
        return sync.best_offset(jp_starts, [c.start for c in english])

    @Slot("QVariantMap")
    def saveWord(self, fields: dict[str, Any]) -> None:
        anime = self._current_anime or {}
        self._db.save_word({**fields,
                            "slug_id": anime.get("slug_id") or "",
                            "title": anime.get("title") or "",
                            "episode": anime.get("current_episode_number") or 0})
        self.savedWordsChanged.emit()

    @Slot(result=list)
    def savedWords(self) -> list[dict[str, Any]]:
        return self._db.saved_words()

    @Slot(int)
    def removeSavedWord(self, word_id: int) -> None:
        self._db.delete_saved_word(word_id)
        self.savedWordsChanged.emit()

    @Slot(result=bool)
    def getLearnMode(self) -> bool:
        return self._db.get_setting("learn_mode") == "true"

    @Slot(bool)
    def setLearnMode(self, on: bool) -> None:
        self._db.set_setting("learn_mode", "true" if on else "false")

    @Slot(str, result=str)
    def learnOption(self, name: str) -> str:
        return self._db.get_setting(f"learn_{name}") or ""

    @Slot(str, str)
    def setLearnOption(self, name: str, value: str) -> None:
        self._db.set_setting(f"learn_{name}", value)

    # -- Rating -------------------------------------------------------------------

    askForRating = Signal(int, str, float)   # (anilist id, title, current score out of 10)
    listScoreChanged = Signal(int, float)    # (anilist id, new score out of 10)

    def _maybe_ask_for_rating(self, anime: dict[str, Any], number: float) -> None:
        """Just finished the final episode of a show that has finished airing
        -- the natural moment to rate it. Not for a show still airing (its
        newest episode isn't its last), not when logged out, and not when the
        user opted this show out of AniList."""
        media_id, total = anime.get("anilist_id"), anime.get("total_episodes")
        if (self._anilist_client is None or not media_id or not total or number < total
                or self._db.get_ignore_anilist(media_id)):
            return
        existing = self._db.get_anilist_status(media_id)
        self.askForRating.emit(media_id, anime.get("title") or "",
                               float(existing.score) if existing else 0.0)

    @Slot(int, result=float)
    def listScore(self, anilist_id: int) -> float:
        existing = self._db.get_anilist_status(anilist_id)
        return float(existing.score) if existing else 0.0

    @Slot(int, float)
    def setListScore(self, anilist_id: int, score: float) -> None:
        client = self._anilist_client
        if client is None or not anilist_id:
            self.listStatusFailed.emit("Log in to AniList in Settings to rate shows.")
            return

        def work() -> float:
            client.set_score(anilist_id, score)
            return score

        def done(new_score: float) -> None:
            existing = self._db.get_anilist_status(anilist_id)
            if existing is not None:
                self._db.upsert_anilist_status(replace(existing, score=new_score))
            self.listScoreChanged.emit(anilist_id, new_score)

        self._pool.start(_Worker(work, done, self.listStatusFailed.emit))

    # -- Auto-download --------------------------------------------------------
    #
    # For long shows: rather than saving all 1,100 episodes of One Piece,
    # keep the next few on disk and add one each time one is watched. Watch 3
    # and episode 13 is queued (with 1 deleted, see episodeWatched) -- so the
    # disk always holds the previous episode, the current one and ten ahead.

    AUTO_DOWNLOAD_AHEAD = 10

    @Slot(str, result=bool)
    def isAutoDownload(self, slug_id: str) -> bool:
        return self._db.get_auto_download(slug_id) is not None

    @Slot(str, result=bool)
    def autoDownloadDub(self, slug_id: str) -> bool:
        """Which audio the auto-download saves -- fixed when it was switched
        on, whatever the Sub/Dub toggle says now."""
        return bool(self._db.get_auto_download(slug_id))

    @Slot(str, bool, bool, float)
    def setAutoDownload(self, slug_id: str, enabled: bool, dub: bool, from_number: float) -> None:
        """from_number is where to start: the episode the user is up to."""
        self._db.set_auto_download(slug_id, enabled, dub)
        if enabled:
            self._top_up_auto_download(after=from_number - 1e-6, dub=dub)
        self.downloadsChanged.emit()

    def _top_up_auto_download(self, after: float, dub: bool,
                              anime: dict[str, Any] | None = None) -> None:
        """Queues the next AUTO_DOWNLOAD_AHEAD episodes after `after` that
        aren't already saved or queued -- nearest first, so the one you'll
        watch next is always the first to be ready.

        `anime` defaults to the show open on screen; the new-episode check
        passes one it fetched itself, for shows nobody has open."""
        anime = anime if anime is not None else self._current_anime
        episodes = (anime or {}).get("episodes") or []
        if anime is None or not episodes or not ffmpeg_available():
            return
        ahead = sorted((e for e in episodes if e.number > after), key=lambda e: e.number)
        # A dub trails the sub. Episodes past the dub count would only fail
        # ("no dubbed version") and sit in the list as errors.
        counts = self._audio_counts.get(anime["slug_id"])
        if dub and counts is not None:
            ahead = ahead[: max(0, counts[1] - sum(1 for e in episodes if e.number <= after))]
        if self._skips_filler(anime):
            ahead = [e for e in ahead if not self._is_filler(anime, e)]
        for episode in ahead[: self.AUTO_DOWNLOAD_AHEAD]:
            self._queue_download({
                "episode_id": episode.episode_id,
                "dub": dub,
                "slug_id": anime["slug_id"],
                "numeric_id": anime.get("numeric_id") or "",
                "title": anime.get("title") or "",
                "poster_url": anime.get("poster_url") or "",
                "episode_number": episode.number,
            })
        self.downloadsChanged.emit()

    # Listings built from this machine rather than from a catalog. They can't
    # be expressed as AniList filters -- "what I have on disk" and "what I was
    # part-way through" are facts about this install -- so Browse asks for
    # them by name and the filter controls don't apply while one is showing.
    _LOCAL_PRESETS: dict[str, str] = {
        "continue": "Continue Watching",
        "downloaded": "Downloaded",
    }

    @Slot(result=list)
    def localCatalogs(self) -> list[dict[str, str]]:
        return [{"key": key, "label": label} for key, label in self._LOCAL_PRESETS.items()]

    @Slot(str)
    def browseLocal(self, key: str) -> None:
        """Answers on the same signal a catalog page does, so Browse renders
        these exactly like any other listing."""
        token = self._begin_browse()
        if key == "downloaded":
            cards = [
                self._card(
                    slug_id=entry.slug_id,
                    numeric_id=entry.numeric_id,
                    title=entry.anime_title,
                    poster_url=entry.poster_url or "",
                    reason=f"{count} episode{'s' if count != 1 else ''} saved",
                )
                for entry, count in self._db.downloaded_anime()
            ]
        else:
            cards = [
                self._card(
                    slug_id=row["slug_id"],
                    numeric_id=row["numeric_id"],
                    anilist_id=row["anilist_id"],
                    title=row["title"],
                    poster_url=row["poster_url"],
                    reason=(f"Episode {row['episode_number']:g}"
                            if row["episode_number"] else ""),
                )
                for row in self._continue_watching_rows()
            ]
        if token != self._browse_token:
            return
        self.browseFinished.emit(
            {"key": key, "results": cards, "page": 1, "hasMore": False}
        )

    # -- Remembered browse state -------------------------------------------
    #
    # Browse used to open on Top Airing every time, throwing away whatever was
    # last set up. The filters are what the user was actually working with, so
    # they are what gets restored.

    @Slot(result="QVariantMap")
    def browseState(self) -> dict[str, Any]:
        raw = self._db.get_setting("browse_state")
        if not raw:
            return {}
        try:
            saved = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return saved if isinstance(saved, dict) else {}

    @Slot(dict)
    def saveBrowseState(self, state: dict[str, Any]) -> None:
        self._db.set_setting("browse_state", json.dumps(dict(state or {})))

    @Slot()
    def clearBrowseState(self) -> None:
        self._db.delete_setting("browse_state")

    # Named filter sets the user saved themselves ("Short romcoms"). Stored
    # as the same state dict Browse already saves and restores, so a preset
    # is exactly "put the page back like this".

    @Slot(result=list)
    def filterPresets(self) -> list[dict[str, Any]]:
        raw = self._db.get_setting("filter_presets")
        try:
            saved = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            return []
        return [p for p in saved if isinstance(p, dict) and p.get("name")] if isinstance(saved, list) else []

    @Slot(str, dict)
    def saveFilterPreset(self, name: str, state: dict[str, Any]) -> None:
        name = name.strip()
        if not name:
            return
        # Saving under an existing name updates it in place, keeping its spot.
        presets = self.filterPresets()
        entry = {"name": name, "state": dict(state or {})}
        for i, preset in enumerate(presets):
            if preset["name"].lower() == name.lower():
                presets[i] = entry
                break
        else:
            presets.append(entry)
        self._db.set_setting("filter_presets", json.dumps(presets))

    @Slot(str)
    def deleteFilterPreset(self, name: str) -> None:
        presets = [p for p in self.filterPresets() if p["name"] != name]
        self._db.set_setting("filter_presets", json.dumps(presets))

    # -- Window geometry ----------------------------------------------------
    #
    # Size and maximised state only, deliberately. A Wayland client cannot
    # place itself on screen at all -- there is no API for it, which is the
    # same reason dragging the window goes through the compositor (see
    # ui/window_chrome.py) -- so a saved x/y could be stored but never
    # honoured, and storing it would only suggest otherwise.

    @Slot(result="QVariantMap")
    def windowGeometry(self) -> dict[str, Any]:
        raw = self._db.get_setting("window_geometry")
        if not raw:
            return {}
        try:
            saved = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        # Clamped to something usable: a window restored at 40x30 because of a
        # bad write is one the user cannot get hold of to fix.
        width = max(800, int(saved.get("width") or 0))
        height = max(600, int(saved.get("height") or 0))
        return {"width": width, "height": height, "maximised": bool(saved.get("maximised"))}

    @Slot(int, int, bool)
    def saveWindowGeometry(self, width: int, height: int, maximised: bool) -> None:
        # A maximised window reports the screen's size; saving that as the
        # restored size means unmaximising gives back a full-screen-sized
        # "normal" window. Only the flag is updated in that case.
        current = self.windowGeometry()
        if maximised:
            width = int(current.get("width") or width)
            height = int(current.get("height") or height)
        self._db.set_setting(
            "window_geometry",
            json.dumps({"width": int(width), "height": int(height), "maximised": bool(maximised)}),
        )

    @Slot(result=bool)
    def getAutoFullscreenEnabled(self) -> bool:
        return (self._db.get_setting("auto_fullscreen_enabled") or "true") == "true"

    @Slot(bool)
    def setAutoFullscreenEnabled(self, value: bool) -> None:
        self._db.set_setting("auto_fullscreen_enabled", "true" if value else "false")

    # -- Per-anime AniList opt-out -----------------------------------------
    #
    # Only automatic syncing is suppressed. The buttons on the detail page
    # still work when this is on: pressing Plan to Watch is an explicit
    # instruction, and silently ignoring it would be a bug rather than a
    # setting. What this stops is a rewatch quietly rewriting the user's
    # progress on their profile.

    @Slot(int, result=bool)
    def isAnilistIgnored(self, anilist_id: int) -> bool:
        return self._db.get_ignore_anilist(anilist_id) if anilist_id else False

    @Slot(int, bool)
    def setAnilistIgnored(self, anilist_id: int, ignore: bool) -> None:
        if anilist_id:
            self._db.set_ignore_anilist(anilist_id, ignore)

    @Slot(result=int)
    def getCurrentEpisodeCount(self) -> int:
        anime = self._current_anime
        return int(anime.get("episode_count") or 0) if anime else 0

    @Slot(result=float)
    def getFirstEpisodeNumber(self) -> float:
        """The lowest episode number this anime actually has, so the player's
        Previous button can be disabled on it. Not simply 1: some entries
        start at 0, and specials come through as fractional numbers."""
        anime = self._current_anime
        episodes = anime.get("episodes") if anime else None
        return float(min(e.number for e in episodes)) if episodes else 1.0

    # -- phone remote ---------------------------------------------------------
    # See remote/server.py's module docstring for the (deliberately simple,
    # LAN-only) pairing/security model.

    @Slot(float, float, bool)
    def reportPlaybackState(self, position: float, duration: float, paused: bool) -> None:
        """Called periodically by PlayerPage.qml -- Backend has no direct view
        into mpv itself, so this is how the remote's /api/state poll finds out
        what's actually playing right now."""
        self._playback_state["position"] = position
        self._playback_state["duration"] = duration
        self._playback_state["paused"] = paused
        anime = self._current_anime or {}
        if anime.get("title") and duration > 0:
            self._discord.update(discord_presence.activity_for(
                anime["title"], float(anime.get("current_episode_number") or 0), position, duration,
                paused, anime.get("poster_url") or ""))

    def _remote_state(self) -> dict[str, Any]:
        anime = self._current_anime
        state = dict(self._playback_state)
        if anime is not None:
            state["title"] = anime.get("title")
            state["episode_number"] = anime.get("current_episode_number") or 0
        home: list[dict[str, Any]] = []
        for e in self._db.continue_watching(limit=8):
            home.append(
                {
                    "open_cmd": "open_continue_watching",
                    "open_arg": e.anime_slug_id,
                    "title": e.anime_title,
                    "poster_url": e.poster_url or "",
                    "subtitle": f"Episode {e.episode_number}",
                }
            )
        for e in self._db.get_anilist_by_status("CURRENT")[:8]:
            home.append(
                {
                    "open_cmd": "open_anime",
                    "open_arg": e.anilist_id,
                    "title": e.title,
                    "poster_url": e.cover_url or "",
                    "subtitle": f"Watching · Episode {e.progress}",
                }
            )
        for e in self._db.get_anilist_by_status("PLANNING")[:8]:
            home.append(
                {
                    "open_cmd": "open_anime",
                    "open_arg": e.anilist_id,
                    "title": e.title,
                    "poster_url": e.cover_url or "",
                    "subtitle": "Planning",
                }
            )
        state["home"] = home
        return state

    def _remote_command(self, cmd: str, args: Any) -> None:
        # Runs on the HTTP server's own background thread -- emit(), not a
        # direct call, so Qt queues delivery onto the GUI thread like every
        # other cross-thread signal in this file. cmd is either "open_anime"
        # (args: anilist_id, for Watching/Planning entries) or
        # "open_continue_watching" (args: slug_id) -- see _remote_state()'s
        # two different home-list item shapes and Main.qml's handler.
        self.remoteCommand.emit(cmd, args)

    # -- The phone as a second screen ------------------------------------------
    #
    # These three run on the remote server's own threads. They only read:
    # plain attribute reads, the locked database, and network lookups with
    # the shared (thread-safe) httpx client.

    @Slot()
    def playerClosed(self) -> None:
        self._now_playing = None
        self._discord.update(None)

    def _phone_stream(self) -> dict[str, Any] | None:
        playing = self._now_playing
        if playing is None:
            return None
        anime = self._current_anime or {}
        return {**playing,
                "position": self._playback_state.get("position", 0),
                "title": anime.get("title") or "",
                "episode": anime.get("current_episode_number") or 0}

    def _phone_search(self, query: str) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        return [
            {"slug_id": r.slug_id, "numeric_id": r.numeric_id, "title": r.title,
             "poster_url": r.poster_url or "", "kind": r.kind or "",
             "sub_count": r.sub_count, "dub_count": r.dub_count}
            for r in source.search(query, self._http)[:30]
        ]

    def _phone_episodes(self, slug_id: str) -> dict[str, Any]:
        episodes = source.get_episodes(slug_id, self._http) if slug_id else []
        try:
            counts = source.get_audio_counts(slug_id, self._http) if slug_id else None
        except httpx.HTTPError:
            counts = None
        progress = self._db.get_progress(slug_id) if slug_id else None
        prefer_dub, _skip = self._db.get_show_prefs(slug_id) if slug_id else (None, False)
        return {
            "episodes": [{"id": e.episode_id, "number": e.number, "title": e.title,
                          "filler": e.filler} for e in episodes],
            "sub": counts[0] if counts else len(episodes),
            "dub": counts[1] if counts else 0,
            "resume": progress.episode_number if progress else 0,
            "prefer_dub": bool(prefer_dub),
        }

    def _load_remote_tokens(self) -> set[str]:
        raw = self._db.get_setting("remote_tokens")
        if not raw:
            return set()
        try:
            return set(json.loads(raw))
        except ValueError:
            return set()

    def _persist_remote_token(self, token: str) -> None:
        # Called from RemoteServer's HTTP thread (a pairing request), so this
        # must only touch self._db, which is safe from any thread -- see the
        # module docstring. Kept as a full replace-the-list write rather than
        # append-in-SQL since the settings table is a plain string blob.
        tokens = self._load_remote_tokens()
        tokens.add(token)
        self._db.set_setting("remote_tokens", json.dumps(sorted(tokens)))

    @Slot(result=bool)
    def isRemoteServerRunning(self) -> bool:
        return self._remote_server is not None and self._remote_server.running

    @Slot()
    def startRemoteServer(self) -> None:
        if self._remote_server is None:
            apk_path = _REMOTE_APK_PATH if _REMOTE_APK_PATH.is_file() else None
            self._remote_server = RemoteServer(
                self._remote_state,
                self._remote_command,
                apk_path=apk_path,
                initial_tokens=self._load_remote_tokens(),
                on_new_token=self._persist_remote_token,
                stream_provider=self._phone_stream,
                search_provider=self._phone_search,
                episodes_provider=self._phone_episodes,
            )
        try:
            self._remote_server.start()
        except OSError as exc:
            # The remote server auto-starts on launch, so a port that's
            # already taken (most often: the app is already running) used to
            # take the whole app down with an unhandled OSError before the
            # window ever appeared. The phone remote is an optional extra --
            # losing it must not cost the user the player itself.
            self.remoteServerFailed.emit(str(exc))
            return
        self._db.set_setting("remote_enabled", "true")

    @Slot()
    def stopRemoteServer(self) -> None:
        if self._remote_server is not None:
            self._remote_server.stop()
        self._db.set_setting("remote_enabled", "false")

    @Slot(result=str)
    def getRemotePin(self) -> str:
        return self._remote_server.pin if self._remote_server is not None else ""

    @Slot(result=str)
    def getRemoteUrl(self) -> str:
        if self._remote_server is None:
            return ""
        return f"http://{_lan_ip()}:{self._remote_server.port}"

    @Slot(result=str)
    def getRemoteApkQrPath(self) -> str:
        """A QR code pointing at the Android remote app -- scan it to
        download+install the APK directly, no typing needed. Prefers this
        machine's own LAN download (see RemoteServer's /app.apk and the
        comment on _REMOTE_APK_PATH above) over the GitHub release link,
        which a phone browser reported as downloading but never installing.
        The LAN link needs the remote server running and its content depends
        on this machine's IP, so it's regenerated on every call rather than
        cached like the old GitHub-URL version was -- QR generation is cheap."""
        if self._remote_server is not None and self._remote_server.running and _REMOTE_APK_PATH.is_file():
            url = f"http://{_lan_ip()}:{self._remote_server.port}/app.apk"
        else:
            url = _REMOTE_APK_URL
        path = Path(tempfile.gettempdir()) / "animeplayer_remote_apk_qr.png"
        qrcode.make(url).save(str(path))
        return path.as_uri()

    @Slot(str)
    def openContinueWatching(self, slug_id: str) -> None:
        """Remote-control equivalent of clicking a Continue Watching card --
        reuses the same anilistAnimeResolved signal shape/handler pages
        already have for openAnilistAnime, since a Continue Watching entry
        already has everything DetailPage needs without a network lookup."""
        entry = self._db.get_progress(slug_id)
        if entry is None:
            return
        self.anilistAnimeResolved.emit(
            {
                "slug_id": entry.anime_slug_id,
                "numeric_id": entry.anime_slug_id.rsplit("-", 1)[-1],
                "title": entry.anime_title,
                "poster_url": entry.poster_url or "",
                "kind": "",
            }
        )

    @Slot(str, result="QVariant")
    def getLocalProgress(self, slug_id: str) -> dict[str, float] | None:
        entry = self._db.get_progress(slug_id)
        if entry is None:
            return None
        return {"episode_number": entry.episode_number, "position_seconds": entry.position_seconds,
                "duration_seconds": entry.duration_seconds}

    @Slot(int, float)
    def _save_progress_on_gui_thread(self, episode_id: int, episode_number: float) -> None:
        if not self._current_anime:
            return
        self._db.save_progress(
            anime_slug_id=self._current_anime["slug_id"],
            anime_title=self._current_anime["title"],
            poster_url=self._current_anime["poster_url"],
            episode_id=episode_id,
            episode_number=episode_number,
            position_seconds=0,
            duration_seconds=0,
        )
        self._emit_continue_watching()

    # With the episode's length too: without it, "stopped at 12:03" and
    # "finished it" looked the same, so Continue couldn't resume at the
    # right second -- or know to move on to the next episode.
    @Slot(int, float, float, float)
    def savePlaybackPosition(self, episode_id: int, episode_number: float, position_seconds: float,
                             duration_seconds: float = 0.0) -> None:
        if not self._current_anime:
            return
        self._db.save_progress(
            anime_slug_id=self._current_anime["slug_id"],
            anime_title=self._current_anime["title"],
            poster_url=self._current_anime["poster_url"],
            episode_id=episode_id,
            episode_number=episode_number,
            position_seconds=position_seconds,
            duration_seconds=duration_seconds,
        )

    @Slot("QVariantMap", int, float, float)
    def saveProgressFor(self, anime: dict[str, Any], episode_id: int, episode_number: float,
                        position_seconds: float) -> None:
        """savePlaybackPosition for a show named explicitly -- the mini
        player's, which keeps playing while other shows' pages are opened
        (each of which changes the "current" show)."""
        if not anime.get("slug_id"):
            return
        self._db.save_progress(
            anime_slug_id=anime["slug_id"], anime_title=anime.get("title") or "",
            poster_url=anime.get("poster_url") or "", episode_id=episode_id,
            episode_number=episode_number, position_seconds=position_seconds, duration_seconds=0,
        )

    @Slot()
    def refreshContinueWatching(self) -> None:
        self._emit_continue_watching()

    def _emit_continue_watching(self) -> None:
        """One "Continue Watching" row, from two sources that used to be two.

        The page had both a Continue Watching row (this machine's own playback
        progress) and a Watching row (the AniList list's CURRENT entries).
        They overlap almost entirely and the difference is invisible from the
        outside, so they are merged: anything with local progress comes first
        and in most-recent order, then anything AniList says is in progress
        that hasn't been played here.
        """
        self.continueWatchingChanged.emit(self._continue_watching_rows())

    def _continue_watching_rows(self, limit: int = 20) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        local_ids: set[int] = set()
        index = self._anilist_title_index()

        for e in self._db.continue_watching(limit=limit):
            match = index.match(e.anime_title) if index is not None else None
            if match is not None:
                local_ids.add(match.anilist_id)
            rows.append(
                {
                    "slug_id": e.anime_slug_id,
                    "numeric_id": e.anime_slug_id.rsplit("-", 1)[-1],
                    "anilist_id": match.anilist_id if match is not None else 0,
                    "title": e.anime_title,
                    "poster_url": e.poster_url or "",
                    "episode_number": e.episode_number,
                    "position_seconds": e.position_seconds,
                    "duration_seconds": e.duration_seconds,  # lets the card draw a real resume bar
                }
            )

        for entry in self._db.get_anilist_by_status("CURRENT"):
            if entry.anilist_id in local_ids:
                continue
            rows.append(
                {
                    # No source slug: these open by being matched to the
                    # source on click, the same as any other AniList card.
                    "slug_id": "",
                    "numeric_id": "",
                    "anilist_id": entry.anilist_id,
                    "title": entry.title,
                    "poster_url": entry.cover_url or "",
                    "episode_number": entry.progress,
                    "position_seconds": 0.0,
                    "duration_seconds": 0.0,
                }
            )

        return rows

    # -- AniList: settings ---------------------------------------------------

    @Slot(result=str)
    def anilistClientId(self) -> str:
        return self._db.get_setting("anilist_client_id") or ANILIST_CLIENT_ID

    @Slot(result=str)
    def builtInAnilistClientId(self) -> str:
        return ANILIST_CLIENT_ID

    @Slot(str)
    def setAnilistClientId(self, value: str) -> None:
        # Empty means the built-in one again.
        if value.strip() and value.strip() != ANILIST_CLIENT_ID:
            self._db.set_setting("anilist_client_id", value.strip())
        else:
            self._db.delete_setting("anilist_client_id")

    @Slot(result=bool)
    def isAnilistLoggedIn(self) -> bool:
        return self._anilist_client is not None

    @Slot(result=str)
    def anilistViewerName(self) -> str:
        return self._db.get_setting("anilist_viewer_name") or ""

    # -- AniList: login/logout ------------------------------------------------

    @Slot()
    def startAnilistLogin(self) -> None:
        client_id = self.anilistClientId()
        if not client_id:
            self.anilistError.emit("Set an AniList Client ID first.")
            return
        webbrowser.open(build_authorize_url(client_id))

    @Slot(str)
    def confirmAnilistLogin(self, token: str) -> None:
        token = token.strip()
        if not token:
            self.anilistError.emit("Paste the access token from the AniList page first.")
            return

        def work() -> tuple[AniListClient, Any]:
            client = AniListClient(self._http, token)
            viewer = client.get_viewer()
            return client, viewer

        def done(result: tuple[AniListClient, Any]) -> None:
            client, viewer = result
            self._anilist_client = client
            self._anilist_user_id = viewer.id
            secrets.save_token(token)
            self._db.set_setting("anilist_viewer_name", viewer.name)
            self._db.set_setting("anilist_user_id", str(viewer.id))
            self.anilistLoggedIn.emit(viewer.name)
            self.refreshAnilistList()

        self._pool.start(_Worker(work, done, self.anilistError.emit))

    @Slot()
    def logoutAnilist(self) -> None:
        self._anilist_client = None
        self._anilist_user_id = None
        secrets.clear_token()
        self._db.delete_setting("anilist_viewer_name")
        self._db.delete_setting("anilist_user_id")
        self._db.clear_anilist_list()
        self.anilistLoggedOut.emit()
        self._emit_anilist_home_lists()

    def _try_restore_anilist_session(self) -> None:
        token = secrets.load_token()
        if not token:
            return

        def work() -> tuple[AniListClient, Any]:
            client = AniListClient(self._http, token)
            viewer = client.get_viewer()
            return client, viewer

        def done(result: tuple[AniListClient, Any]) -> None:
            client, viewer = result
            self._anilist_client = client
            self._anilist_user_id = viewer.id
            self._db.set_setting("anilist_viewer_name", viewer.name)
            self.anilistLoggedIn.emit(viewer.name)
            self.refreshAnilistList()

        def fail(_message: str) -> None:
            # Saved token is expired/invalid -- drop it silently rather than
            # nagging the user with an error for something they didn't just do.
            secrets.clear_token()

        self._pool.start(_Worker(work, done, fail))

    # -- AniList: list sync ---------------------------------------------------

    @Slot()
    def refreshAnilistHomeLists(self) -> None:
        """Re-emits the Watching/Planning rows from the local cache -- no
        network call. HomePage.qml must call this itself on every load (like
        refreshContinueWatching()): Qt signals aren't replayed for a QML page
        that didn't exist yet when they were first emitted, so a freshly
        (re)pushed HomePage otherwise starts with empty Watching/Planning rows
        until the next unrelated event happens to trigger a fresh emit."""
        self._emit_anilist_home_lists()

    @Slot()
    def refreshAnilistList(self) -> None:
        if self._anilist_client is None or self._anilist_user_id is None:
            return
        client = self._anilist_client
        user_id = self._anilist_user_id

        def work() -> list:
            return client.get_list_collection(user_id)

        def done(entries: list) -> None:
            self._db.replace_anilist_list(
                [
                    AniListStatus(
                        anilist_id=e.media_id,
                        status=e.status,
                        progress=e.progress,
                        score=e.score,
                        title=e.title,
                        cover_url=e.cover_url,
                        genres=e.genres,
                        popularity=e.popularity,
                        titles=e.titles,
                    )
                    for e in entries
                ]
            )
            self._anilist_index = None
            self.anilistListRefreshed.emit()
            self._emit_anilist_home_lists()

        self._pool.start(_Worker(work, done, self.anilistError.emit))

    def _emit_anilist_home_lists(self) -> None:
        def as_dicts(entries: list[AniListStatus]) -> list[dict[str, Any]]:
            return [
                {
                    "anilist_id": e.anilist_id,
                    "title": e.title,
                    "poster_url": e.cover_url or "",
                    "progress": e.progress,
                }
                for e in entries
            ]

        # Watching is folded into Continue Watching now -- see
        # _emit_continue_watching -- so refreshing the list has to refresh
        # that row, not a row of its own.
        self._emit_continue_watching()

        # Planning list ordered by relevance instead of alphabetically: shows
        # sharing genres with what's actually been finished score higher, tied
        # entries fall back to AniList's own popularity. A simple heuristic,
        # not real recommendations, but a lot more useful than A-Z.
        completed_genres: set[str] = set()
        for e in self._db.get_anilist_by_status("COMPLETED"):
            completed_genres.update(e.genres)

        def affinity(entry: AniListStatus) -> tuple[int, int]:
            shared = len(completed_genres & set(entry.genres))
            return (shared, entry.popularity)

        planning = sorted(self._db.get_anilist_by_status("PLANNING"), key=affinity, reverse=True)
        self.anilistPlanningChanged.emit(as_dicts(planning))

    @Slot(int, str)
    def openAnilistAnime(self, anilist_id: int, title: str) -> None:
        """Resolves an AniList list entry to a source result so it can be
        pushed onto DetailPage -- the reverse of the search-page status-badge
        matching. Cached after the first lookup per anilist_id."""
        cached = self._db.get_anidb_mapping(anilist_id)
        if cached is not None:
            self.anilistAnimeResolved.emit(
                {
                    "slug_id": cached.slug_id,
                    "numeric_id": cached.numeric_id,
                    "title": cached.title,
                    "poster_url": cached.poster_url,
                    "kind": cached.kind,
                }
            )
            return

        titles = self._titles_for(anilist_id, title)

        def work() -> source.SearchResult | None:
            return matcher.find_source_result(titles, lambda q: source.search(q, self._http))

        def done(result: source.SearchResult | None) -> None:
            if result is None:
                self._db.save_anidb_mapping(anilist_id, None)
                self.anilistAnimeResolveFailed.emit(title)
                return
            self._db.save_anidb_mapping(
                anilist_id,
                AniDBMapping(
                    anilist_id=anilist_id,
                    slug_id=result.slug_id,
                    numeric_id=result.numeric_id,
                    title=result.title,
                    poster_url=result.poster_url,
                    kind=result.kind,
                ),
            )
            self.anilistAnimeResolved.emit(
                {
                    "slug_id": result.slug_id,
                    "numeric_id": result.numeric_id,
                    "title": result.title,
                    "poster_url": result.poster_url,
                    "kind": result.kind,
                }
            )

        # Deliberately a different signal from the not-found one above: they
        # were the same, so a network/site failure rendered as
        # 'Couldn't find a stream for "Server error 503 ..."' -- the exception
        # text pasted in where a title belongs. Two causes, two messages.
        self._pool.start(_Worker(work, done, self.anilistAnimeResolveErrored.emit))

    # How far behind counts as "not watched". Anything with no progress at
    # all, or stopped short of the end, is worth warning about; an entry the
    # user is one episode from finishing is not.
    _PREQUEL_DONE_FRACTION = 0.9

    def _watch_progress(self, entry: "ChainEntry") -> tuple[str, int, bool]:
        """(status label, episodes watched, has the user effectively seen it)."""
        status = self._db.get_anilist_status(entry.id)
        if status is None:
            return ("", 0, False)
        if status.status in ("COMPLETED", "REPEATING"):
            return (_STATUS_LABELS.get(status.status, status.status), status.progress, True)
        total = entry.episodes or 0
        watched_enough = bool(
            total and status.progress >= total * self._PREQUEL_DONE_FRACTION
        )
        return (
            _STATUS_LABELS.get(status.status, status.status),
            status.progress,
            watched_enough,
        )

    def _fetch_anime_extras(self, anilist_id: int, slug_id: str) -> None:
        def work() -> dict[str, Any]:
            client = self._anilist_public
            extras = client.get_media_extras(anilist_id)
            order = client.get_watch_order(anilist_id)

            chain: list[dict[str, Any]] = []
            unwatched: list[dict[str, Any]] = []
            reached_current = False
            for entry in order:
                label, progress, done = self._watch_progress(entry)
                is_current = entry.id == anilist_id
                reached_current = reached_current or is_current
                row = {
                    "anilist_id": entry.id,
                    "title": entry.title,
                    "poster_url": entry.cover_url or "",
                    "kind": entry.format or "",
                    "episodes": entry.episodes or 0,
                    "year": entry.year or 0,
                    "current": is_current,
                    "statusLabel": label,
                    "progress": progress,
                    "watched": done,
                }
                chain.append(row)
                # Only what comes *before* this entry can be a spoiler risk or
                # a missing prerequisite -- later seasons are simply unwatched.
                if not reached_current and not done:
                    unwatched.append(row)

            # SOURCE/ADAPTATION edges point at the manga, and CHARACTER edges
            # at unrelated shows sharing a cast; neither belongs on a page
            # about what else there is to watch.
            related = [
                self._media_summary_to_card(
                    r.media, reason=r.relation_type.replace("_", " ").title()
                )
                for r in extras.relations
                if r.relation_type not in ("SOURCE", "ADAPTATION", "CHARACTER", "OTHER")
            ]
            self._remember_titles([r.media for r in extras.relations])
            self._remember_titles(list(extras.recommendations))

            return {
                "slug_id": slug_id,
                # The Japanese broadcast of the next episode. Named for what
                # it is rather than "next episode": AniList publishes no dub
                # schedule, so the UI must not let this read as one.
                "airingStatus": extras.status,
                "nextEpisode": extras.next_episode or 0,
                "nextAiringAt": extras.next_airing_at or 0,
                "watchOrder": chain,
                "unwatchedPrequels": unwatched,
                # {"12": {"title", "thumbnail"}} -- string keys: QML maps are keyed by string.
                "episodeArt": {str(n): {"title": t, "thumbnail": u} for n, (t, u) in extras.episode_art.items()},
                "related": related,
                "recommendations": [
                    self._media_summary_to_card(m) for m in extras.recommendations
                ],
                "reviews": [
                    {
                        "id": r.id,
                        "summary": r.summary,
                        "score": r.score or 0,
                        "user": r.user,
                        "helpful": r.rating,
                        "url": f"https://anilist.co/review/{r.id}",
                    }
                    for r in extras.reviews
                ],
            }

        def done(payload: dict[str, Any]) -> None:
            # The user may have navigated on while this was in flight; a page
            # that has already been replaced must not be handed another
            # anime's relations.
            if self._current_anime is not None and self._current_anime["slug_id"] == slug_id:
                self.animeExtrasReady.emit(payload)

        self._pool.start(_Worker(work, done, lambda _msg: None))

    def _anilist_title_index(self) -> "matcher.TitleIndex[AniListStatus] | None":
        """The user's list, indexed for matching. Built once and kept: the
        list only changes when it is re-synced, and rebuilding it per page of
        results is most of the cost of badging them."""
        if self._anilist_index is None:
            entries = self._db.get_anilist_list()
            if not entries:
                return None
            self._anilist_index = matcher.TitleIndex(
                [(e, e.titles or (e.title,)) for e in entries]
            )
        return self._anilist_index

    def _match_anilist_statuses(self, results: list[source.SearchResult]) -> None:
        """Badges a page of results with the user's own list status.

        Matched against the *local* mirror of their list, not against AniList.
        This used to call AniList once per result to resolve its id -- thirty
        GraphQL searches for one page of browse results, against an API that
        rate-limits, which is what made changing a filter take many seconds to
        settle. The mirror already holds every name AniList knows for each
        entry (see AniListStatus.titles), which is exactly what matching needs,
        so the whole thing is now local and immediate.
        """
        if self._anilist_client is None:
            return

        def work() -> dict[str, dict[str, Any]]:
            index = self._anilist_title_index()
            if index is None:
                return {}
            matches: dict[str, dict[str, Any]] = {}
            for result in results:
                entry = index.match(result.title)
                if entry is None:
                    continue
                matches[result.slug_id] = {
                    "status": entry.status,
                    "label": _STATUS_LABELS.get(entry.status, entry.status),
                    "progress": entry.progress,
                }
            return matches

        def done(matches: dict[str, dict[str, Any]]) -> None:
            if matches:
                self.anilistStatusesResolved.emit(matches)

        self._pool.start(_Worker(work, done, lambda _msg: None))

    def _resolve_current_anime_status(self, slug_id: str, title: str) -> None:
        # The unauthenticated client, deliberately. Everything this feeds --
        # the score, genres, synopsis and key art on the detail page, plus the
        # MAL id the filler and skip-time lookups need -- is public AniList
        # data. This used to return early when nobody was logged in, which
        # left a logged-out user staring at a bare title and a grid of episode
        # numbers. Only the user's *own* list status needs the login, and that
        # comes from the local mirror of their list below.
        def work() -> tuple[MediaSummary | None, AniListStatus | None]:
            summary = matcher.resolve_media_summary(title, self._anilist_public, self._db)
            status = self._db.get_anilist_status(summary.id) if summary is not None else None
            return summary, status

        def done(result: tuple[MediaSummary | None, AniListStatus | None]) -> None:
            summary, status = result
            media_id = summary.id if summary is not None else None
            if self._current_anime is not None and self._current_anime["slug_id"] == slug_id:
                self._current_anime["anilist_id"] = media_id
                self._current_anime["mal_id"] = summary.id_mal if summary is not None else None
                self._current_anime["total_episodes"] = summary.episodes if summary is not None else None
                self._maybe_fetch_filler_fallback(slug_id)
                current_episode_number = self._current_anime.get("current_episode_number")
                if current_episode_number is not None:
                    self._maybe_fetch_skip_times(current_episode_number)
                    if self._current_anime.get("_want_japanese_subs") is not None:
                        self.loadJapaneseSubs(self._current_anime["_want_japanese_subs"])
                    # An episode watched before the AniList match came back
                    # -- one picked from the phone opens the player straight
                    # away -- went unsynced. Catch it up now.
                    watched = self._current_anime.get("_watched_number")
                    if (media_id is not None and self._anilist_client is not None and watched is not None
                            and self._current_anime.get("_progress_pushed") != watched):
                        self._push_anilist_progress(dict(self._current_anime), watched)
            if status is not None:
                self.anilistCurrentStatus.emit(
                    _STATUS_LABELS.get(status.status, status.status), status.progress
                )
            else:
                self.anilistCurrentStatus.emit("", 0)
            if summary is not None:
                self._fetch_anime_extras(summary.id, slug_id)
                # Remembered for watch stats (genres) and the "Because you
                # watched" row (the AniList id to ask for recommendations).
                self._db.set_anime_meta(slug_id, title, summary.id, list(summary.genres))
                self.anilistMediaDetails.emit(
                    {
                        "average_score": summary.average_score or 0,
                        "genres": list(summary.genres),
                        "format": summary.format or "",
                        "episodes": summary.episodes or 0,
                        "description": _strip_html(summary.description or ""),
                        "cover_url": summary.cover_url or "",
                        "banner_url": summary.banner_url or "",
                        # The detail page needs the id to act on the list.
                        "anilist_id": summary.id,
                    }
                )

        self._pool.start(_Worker(work, done, lambda _msg: None))

    def _push_anilist_progress(self, anime_snapshot: dict[str, Any], episode_number: float) -> None:
        client = self._anilist_client
        media_id = anime_snapshot.get("anilist_id")
        if media_id is not None:
            self._push_guest_progress(media_id, anime_snapshot.get("total_episodes"), episode_number)
        if client is None or media_id is None:
            return
        # Marked on the live record, so the catch-up in
        # _resolve_current_anime_status doesn't push the same episode twice.
        if self._current_anime is not None and self._current_anime.get("slug_id") == anime_snapshot.get("slug_id"):
            self._current_anime["_progress_pushed"] = episode_number
        # Opted out on the detail page -- watch it without it showing up on
        # the profile. See isAnilistIgnored.
        if self._db.get_ignore_anilist(media_id):
            return
        # AniList's own total, not the source's episode count: for a show
        # still airing the source's count is just the newest episode, and
        # watching that marked the whole show Completed. No total (still
        # airing, or unknown) means it can't be finished yet.
        total = anime_snapshot.get("total_episodes")
        status = "COMPLETED" if total and episode_number >= total else "CURRENT"
        progress = int(episode_number)

        def work() -> None:
            client.save_progress(media_id, status, progress)

        def done(_result: None) -> None:
            existing = self._db.get_anilist_status(media_id)
            self._db.upsert_anilist_status(
                AniListStatus(
                    anilist_id=media_id,
                    status=status,
                    progress=progress,
                    score=existing.score if existing else 0.0,
                    title=existing.title if existing else anime_snapshot["title"],
                    cover_url=existing.cover_url if existing else anime_snapshot.get("poster_url"),
                    # Carried over rather than defaulted: this row is written
                    # after every episode, and dropping them here would quietly
                    # strip the genres the recommendation ranking reads and the
                    # titles the source matcher needs from whatever the user
                    # actually watches most.
                    genres=existing.genres if existing else (),
                    popularity=existing.popularity if existing else 0,
                    titles=existing.titles if existing else (),
                )
            )
            self._emit_anilist_home_lists()
            # The show's page, if it's still the one open, shows it watched.
            current = self._current_anime or {}
            if current.get("anilist_id") == media_id:
                self.anilistCurrentStatus.emit(_STATUS_LABELS.get(status, status), progress)

        self._pool.start(_Worker(work, done, self.anilistError.emit))

    # -- updates -------------------------------------------------------------
    # See updates.py. The window shows a bar when updateAvailable fires; the
    # Settings page has the manual check.

    UPDATE_CHECK_MS = 6 * 60 * 60 * 1000

    updateAvailable = Signal(str, str, str)  # (version, notes, how: installer | git | page)
    updateStatus = Signal(str)               # answer to a manual check: "You're up to date", errors
    updateProgress = Signal(float)           # installer download, 0..1
    updateFailed = Signal(str)

    @Slot(result=str)
    def appVersion(self) -> str:
        return updates.VERSION

    @Slot(result=bool)
    def getUpdateChecksEnabled(self) -> bool:
        return (self._db.get_setting("update_checks") or "true") == "true"

    @Slot(bool)
    def setUpdateChecksEnabled(self, value: bool) -> None:
        self._db.set_setting("update_checks", "true" if value else "false")

    @Slot(bool)
    def checkForUpdates(self, manual: bool) -> None:
        """manual: from the Settings button, which wants an answer either
        way, and which ignores both the off switch and "Later"."""
        if not manual and (not self.getUpdateChecksEnabled() or os.environ.get("ANIMEPLAYER_DB_PATH")):
            return

        def work() -> updates.Release | None:
            return updates.latest_release(self._http)

        def done(release: updates.Release | None) -> None:
            if release is None or not updates.is_newer(release.version):
                if manual:
                    self.updateStatus.emit(f"You're up to date (version {updates.VERSION}).")
                return
            if not manual and self._db.get_setting("update_dismissed") == release.version:
                return
            self._release = release
            how = updates.how_to_install()
            if how == "installer" and not release.installer_url:
                how = "page"
            self.updateAvailable.emit(release.version, release.notes, how)

        def failed(message: str) -> None:
            if manual:
                self.updateStatus.emit(message)

        self._pool.start(_Worker(work, done, failed))

    @Slot()
    def dismissUpdate(self) -> None:
        """"Later": not asked again about this version until the next one,
        though Settings can still install it."""
        if self._release is not None:
            self._db.set_setting("update_dismissed", self._release.version)

    @Slot()
    def installUpdate(self) -> None:
        release = self._release
        if release is None:
            return
        how = updates.how_to_install()
        if how == "installer" and release.installer_url:
            def work() -> Path:
                return updates.download_installer(
                    self._http, release, Path(tempfile.gettempdir()) / "AnimePlayer-update",
                    self.updateProgress.emit)

            def done(path: Path) -> None:
                self._updateReadyToRun.emit(str(path))

            self._pool.start(_Worker(work, done, self.updateFailed.emit))
        elif how == "git":
            root = updates.source_checkout()

            def work() -> str:
                return updates.git_pull(root) if root else "Not a git checkout."

            def done(error: str) -> None:
                if error:
                    self.updateFailed.emit(error)
                else:
                    self._updateReadyToRun.emit("")

            self._pool.start(_Worker(work, done, self.updateFailed.emit))
        else:
            webbrowser.open(release.page_url)

    @Slot(result=str)
    def releasePageUrl(self) -> str:
        return self._release.page_url if self._release else f"https://github.com/{updates.REPO}/releases"

    # Emitted from the worker, handled on the GUI thread: starting another
    # process and quitting Qt both belong there.
    _updateReadyToRun = Signal(str)

    def _run_update(self, installer: str) -> None:
        if installer:
            try:
                updates.run_installer(Path(installer))
            except OSError as exc:
                self.updateFailed.emit(f"Couldn't start the installer: {exc}")
                return
        else:
            # A fresh copy of the updated code, started the same way this one was.
            QProcess.startDetached(sys.executable, ["-m", "animeplayer", *sys.argv[1:]],
                                   str(updates.source_checkout() or Path.cwd()))
        QCoreApplication.quit()

    # -- reporting problems --------------------------------------------------
    # For testers: one click opens a GitHub issue with what the app knows --
    # its version, the OS and the last errors -- filled in. Nothing is sent
    # by the app itself; the person sees the report before submitting it.

    @Slot(str)
    def noteError(self, message: str) -> None:
        self._recent_errors.append(f"{time.strftime('%H:%M:%S')}  {message.strip()}")

    @Slot(result=str)
    def problemReport(self) -> str:
        import platform
        errors = "\n".join(self._recent_errors) or "(none this session)"
        return (
            f"**Version:** {updates.VERSION}\n"
            f"**System:** {platform.system()} {platform.release()} ({platform.machine()})\n\n"
            "**What happened:**\n\n\n"
            "**What you expected:**\n\n\n"
            f"**Recent errors:**\n```\n{errors}\n```\n"
        )

    @Slot(str, result=str)
    def problemReportUrl(self, title: str) -> str:
        from urllib.parse import urlencode
        body = self.problemReport()
        # Browsers and GitHub cap URL length; the oldest errors go first.
        while len(body) > 6000 and self._recent_errors:
            self._recent_errors.popleft()
            body = self.problemReport()
        query = urlencode({"title": title or "Problem report", "body": body})
        return f"https://github.com/{updates.REPO}/issues/new?{query}"

    # -- library -------------------------------------------------------------
    # Tabs of shows. Two are built in -- what's downloaded, and the AniList
    # Planning list -- and the rest are the user's own, kept on this PC.

    libraryChanged = Signal()

    @Slot(result=list)
    def libraryLists(self) -> list[dict[str, Any]]:
        return self._db.library_lists()

    @Slot(str, result=int)
    def createLibraryList(self, name: str) -> int:
        name = name.strip()
        if not name:
            return 0
        list_id = self._db.create_library_list(name)
        self.libraryChanged.emit()
        return list_id

    @Slot(int, str)
    def renameLibraryList(self, list_id: int, name: str) -> None:
        if name.strip():
            self._db.rename_library_list(list_id, name.strip())
            self.libraryChanged.emit()

    @Slot(int)
    def deleteLibraryList(self, list_id: int) -> None:
        self._db.delete_library_list(list_id)
        self.libraryChanged.emit()

    @Slot(int, "QVariantMap")
    def addToLibrary(self, list_id: int, show: dict[str, Any]) -> None:
        if not show.get("slug_id"):
            return
        self._db.add_to_library(list_id, show)
        self.libraryChanged.emit()

    @Slot(int, str)
    def removeFromLibrary(self, list_id: int, slug_id: str) -> None:
        self._db.remove_from_library(list_id, slug_id)
        self.libraryChanged.emit()

    @Slot(str, result=list)
    def libraryListsFor(self, slug_id: str) -> list[int]:
        return self._db.lists_containing(slug_id)

    @Slot(int, result=list)
    def libraryItems(self, list_id: int) -> list[dict[str, Any]]:
        return self._db.library_items(list_id)

    @Slot(result=list)
    def downloadedShows(self) -> list[dict[str, Any]]:
        """Every show with saved episodes, newest first, with how many and how big."""
        shows: dict[str, dict[str, Any]] = {}
        for entry in self._db.all_downloads():
            if entry.status != "ready":
                continue
            show = shows.setdefault(entry.slug_id, {
                "slug_id": entry.slug_id, "numeric_id": entry.numeric_id,
                "title": entry.anime_title, "poster_url": entry.poster_url or "",
                "count": 0, "bytes": 0, "latest": 0.0,
            })
            show["count"] += 1
            show["bytes"] += entry.bytes
            show["latest"] = max(show["latest"], entry.created_at)
        return sorted(shows.values(), key=lambda s: s["latest"], reverse=True)

    @Slot(result=list)
    def planningShows(self) -> list[dict[str, Any]]:
        return [{"anilist_id": e.anilist_id, "title": e.title, "poster_url": e.cover_url or ""}
                for e in self._db.get_anilist_by_status("PLANNING")]

    # -- airing schedule -----------------------------------------------------

    scheduleReady = Signal(list)
    scheduleFailed = Signal(str)

    @Slot()
    def loadSchedule(self) -> None:
        """The next seven days of airing episodes, from AniList. Shows being
        watched (Continue Watching) or on the Planning list are marked, so
        the page can show just those."""
        followed = set(self._followed_shows())
        planning = {e.anilist_id for e in self._db.get_anilist_by_status("PLANNING")}
        watching = {e.anilist_id for e in self._db.get_anilist_by_status("CURRENT")}

        def work() -> list[dict[str, Any]]:
            now = int(time.time())
            # From the start of today, so this morning's episodes still show.
            start = int(time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1)))
            items = self._anilist_public.get_schedule(start, start + 7 * 86400)
            self._remember_titles([i.media for i in items])
            return [{
                "anilist_id": i.media.id,
                "title": i.media.title,
                "poster_url": i.media.cover_url or "",
                "episode": i.episode,
                "airing_at": i.airing_at,
                "following": i.media.id in followed or i.media.id in watching,
                "planning": i.media.id in planning,
            } for i in items]

        self._pool.start(_Worker(work, self.scheduleReady.emit, self.scheduleFailed.emit))

    # -- Discord status ------------------------------------------------------

    @Slot(result=bool)
    def discordAvailable(self) -> bool:
        return bool(DISCORD_CLIENT_ID)

    @Slot(result=bool)
    def getDiscordEnabled(self) -> bool:
        return (self._db.get_setting("discord_status") or "true") == "true"

    @Slot(bool)
    def setDiscordEnabled(self, value: bool) -> None:
        self._db.set_setting("discord_status", "true" if value else "false")
        self._discord.set_enabled(value)

    # -- watch together --------------------------------------------------------
    # A friend watching with you logs into their own AniList for one show;
    # every episode finished then counts on their account as well as yours.
    # Their login lives in the keyring only while it's needed: it is deleted
    # when the show is finished, or when either of you ends it.

    watchTogetherChanged = Signal()
    watchTogetherNotice = Signal(str)

    def _watch_together(self) -> dict[str, Any] | None:
        raw = self._db.get_setting("watch_together")
        return json.loads(raw) if raw else None

    @Slot(result="QVariantMap")
    def watchTogether(self) -> dict[str, Any]:
        """{anilist_id, title, name} of the session running, or {}."""
        return self._watch_together() or {}

    @Slot(result=str)
    def watchTogetherLoginUrl(self) -> str:
        client_id = self.anilistClientId()
        return build_authorize_url(client_id) if client_id else ""

    @Slot(int, str, str)
    def startWatchTogether(self, anilist_id: int, title: str, token: str) -> None:
        token = token.strip()
        if not token or not anilist_id:
            self.watchTogetherNotice.emit("Paste your friend's AniList token first.")
            return

        def work() -> Any:
            return AniListClient(self._http, token).get_viewer()

        def done(viewer: Any) -> None:
            if self._anilist_user_id is not None and viewer.id == self._anilist_user_id:
                self.watchTogetherNotice.emit(
                    "That's your own AniList account -- the login page used the account your browser "
                    "is signed in to. Open the link in a private window and have your friend log in there.")
                return
            secrets.save_guest_token(token)
            self._db.set_setting("watch_together", json.dumps(
                {"anilist_id": anilist_id, "title": title, "name": viewer.name, "user_id": viewer.id}))
            self.watchTogetherChanged.emit()

        self._pool.start(_Worker(work, done, self.watchTogetherNotice.emit))

    @Slot()
    def endWatchTogether(self) -> None:
        secrets.clear_guest_token()
        self._db.delete_setting("watch_together")
        self.watchTogetherChanged.emit()

    def _push_guest_progress(self, media_id: int, total: int | None, episode_number: float) -> None:
        session = self._watch_together()
        if not session or session.get("anilist_id") != media_id:
            return
        token = secrets.load_guest_token()
        if not token:
            self.endWatchTogether()
            return
        finished = bool(total) and episode_number >= total
        status = "COMPLETED" if finished else "CURRENT"

        def work() -> None:
            AniListClient(self._http, token).save_progress(media_id, status, int(episode_number))

        def done(_result: None) -> None:
            if finished:
                # The show is done, and so is the reason to keep their login.
                self.endWatchTogether()
                self.watchTogetherNotice.emit(
                    f"Finished {session['title']} -- {session['name']}'s AniList is up to date, "
                    "and their login has been removed from this PC.")

        self._pool.start(_Worker(work, done, lambda message: self.watchTogetherNotice.emit(
            f"Couldn't update {session['name']}'s AniList: {message}")))

    # -- the Continue page ---------------------------------------------------

    @Slot(result=list)
    def continueWatchingAll(self) -> list[dict[str, Any]]:
        """Everything in progress: this PC's, then AniList's Watching list.
        The home row shows the first twenty; the Continue page shows it all."""
        return self._continue_watching_rows(limit=500)

    @Slot(str)
    def removeFromContinueWatching(self, slug_id: str) -> None:
        """Forgets where you were in a show on this PC. Its AniList entry
        (if any) is left alone."""
        if slug_id:
            self._db.delete_progress(slug_id)
            self._emit_continue_watching()



    # -- the home page's spotlight -------------------------------------------
    # It used to be the streaming site's own carousel, which hardly changes
    # and leans old. Now it's a fresh mix every launch, each with the reason
    # it's there: what's trending, this season's big shows, something from
    # your Planning list, and a hidden gem. The site's carousel stays as the
    # fallback if AniList can't be reached.

    _SEQUEL_RE = re.compile(
        r"\b(season|part|cour)\s*\d|\b\d+(st|nd|rd|th)\s+season|\b(ii|iii|iv)\b|\bmovie\b|"
        r"\bfinal\b|\bspecial\b|\s[2-9]$|:\s.*\barc\b", re.IGNORECASE)

    @staticmethod
    def _current_season() -> tuple[str, int]:
        t = time.localtime()
        return ("WINTER", "WINTER", "SPRING", "SPRING", "SPRING", "SUMMER", "SUMMER", "SUMMER",
                "FALL", "FALL", "FALL", "WINTER")[t.tm_mon - 1], t.tm_year + (1 if t.tm_mon == 12 else 0)

    def _build_spotlight(self) -> None:
        seen_statuses = {e.anilist_id for status in ("COMPLETED", "DROPPED")
                         for e in self._db.get_anilist_by_status(status)}
        planning_ids = [e.anilist_id for e in self._db.get_anilist_by_status("PLANNING")]
        client = self._anilist_public

        def work() -> list[dict[str, Any]]:
            season, year = self._current_season()
            pools: list[tuple[str, list]] = [
                ("Trending now", client.get_spotlight_pool("trending")),
                (f"Popular this {season.title()}", client.get_spotlight_pool("season", season=season, year=year)),
            ]
            if planning_ids:
                picks = random.sample(planning_ids, min(20, len(planning_ids)))
                pools.append(("On your Planning list", client.get_spotlight_pool("ids", ids=picks)))
            # Series and films only: a special or an OVA isn't where anyone
            # starts a show.
            gems = [g for g in client.get_spotlight_pool("gems", year=year)
                    if g.media.format in ("TV", "MOVIE")
                    and not any(self._SEQUEL_RE.search(t) for t in g.media.titles)]
            pools.append(("Hidden gem", gems))

            wanted = {"Trending now": 3, "On your Planning list": 2, "Hidden gem": 2}
            chosen: list[tuple[str, Any]] = []
            used: set[int] = set()
            for reason, pool in pools:
                candidates = [m for m in pool
                              if m.media.id not in used and m.media.id not in seen_statuses
                              and m.media.description]
                # From the top of each list, but not always its very top.
                candidates = candidates[:15]
                random.shuffle(candidates)
                for m in candidates[:wanted.get(reason, 2)]:
                    used.add(m.media.id)
                    chosen.append((reason, m))
            random.shuffle(chosen)
            self._remember_titles([m.media for _r, m in chosen])
            return [self._spotlight_card(reason, m, i + 1) for i, (reason, m) in enumerate(chosen[:10])]

        def done(cards: list[dict[str, Any]]) -> None:
            if cards:
                self._spotlight_built = True
                self.homeSpotlightReady.emit(cards)

        self._pool.start(_Worker(work, done, lambda _msg: None))

    @staticmethod
    def _spotlight_card(reason: str, m: Any, rank: int) -> dict[str, Any]:
        media = m.media
        description = _strip_html(media.description or "").replace("\n", " ")
        # AniList synopses often end "(Source: Crunchyroll)": credit that
        # reads as clutter in a hero banner.
        description = re.sub(r"\s*[\(\[]\s*(Source|Written by)[^\)\]]*[\)\]]\s*$", "", description, flags=re.I).strip()
        if len(description) > 420:
            description = description[:420].rsplit(" ", 1)[0] + "…"
        return {
            "slug_id": "", "numeric_id": "", "anilist_id": media.id,
            "title": media.title, "japanese_title": "",
            "banner_url": media.banner_url or media.cover_url or "",
            "description": description,
            "kind": {"TV_SHORT": "TV Short"}.get(media.format or "", media.format or ""),
            "duration": f"{m.duration}m" if m.duration else "",
            "released": f"{m.season.title()} {m.season_year}" if m.season and m.season_year else "",
            "sub_count": 0, "dub_count": 0,
            "score": media.average_score or 0,
            "rank": rank,
            "reason": reason,
        }

    # -- the Seasonal page -----------------------------------------------------

    seasonReady = Signal(str, int, list)   # (season, year, cards)
    seasonFailed = Signal(str)

    @Slot(result="QVariantMap")
    def currentSeason(self) -> dict[str, Any]:
        season, year = self._current_season()
        return {"season": season, "year": year}

    @Slot(str, int)
    def loadSeason(self, season: str, year: int) -> None:
        statuses = {e.anilist_id: e.status for status in ("CURRENT", "PLANNING", "COMPLETED", "PAUSED", "DROPPED")
                    for e in self._db.get_anilist_by_status(status)}

        def work() -> list[dict[str, Any]]:
            entries = self._anilist_public.get_season(season, year)
            self._remember_titles([e.media for e in entries])
            return [{
                "anilist_id": e.media.id,
                "title": e.media.title,
                "poster_url": e.media.cover_url or "",
                "format": e.media.format or "",
                "genres": list(e.media.genres[:3]),
                "score": e.media.average_score or 0,
                "episodes": e.media.episodes or 0,
                "status": e.status,
                "next_episode": e.next_episode or 0,
                "next_airing_at": e.next_airing_at or 0,
                "list_status": statuses.get(e.media.id, ""),
            } for e in entries]

        self._pool.start(_Worker(work, lambda cards: self.seasonReady.emit(season, year, cards),
                                 self.seasonFailed.emit))

    # -- search history and "did you mean" -------------------------------------

    _HISTORY_KEEP = 30

    @Slot(result=list)
    def searchHistory(self) -> list[str]:
        raw = self._db.get_setting("search_history")
        return json.loads(raw) if raw else []

    @Slot(str)
    def addSearchHistory(self, query: str) -> None:
        query = " ".join(query.split())
        if not query:
            return
        history = [q for q in self.searchHistory() if q.lower() != query.lower()]
        self._db.set_setting("search_history", json.dumps([query, *history][:self._HISTORY_KEEP]))

    @Slot(str)
    def removeSearchHistory(self, query: str) -> None:
        self._db.set_setting("search_history",
                             json.dumps([q for q in self.searchHistory() if q != query]))

    @Slot()
    def clearSearchHistory(self) -> None:
        self._db.delete_setting("search_history")

    searchSuggestion = Signal(str, str)  # (the search that found nothing, what it probably meant)

    _TITLE_CATALOG_PAGES = 30   # 1,500 most popular shows
    _TITLE_CATALOG_MAX_AGE = 7 * 86400

    def _catalog_path(self) -> Path:
        return DEFAULT_DB_PATH.parent / "title-catalog.json"

    def _catalog_load(self) -> None:
        """From disk, if a fresh copy is there. Caller holds the lock."""
        if self._catalog_complete or self._catalog:
            return
        try:
            path = self._catalog_path()
            if time.time() - path.stat().st_mtime < self._TITLE_CATALOG_MAX_AGE:
                self._catalog = {int(k): (v[0], tuple(v[1])) for k, v in json.loads(path.read_text()).items()}
                self._catalog_complete = True
        except (OSError, ValueError):
            pass

    def _catalog_step(self) -> bool:
        """Fetches the next page of popular titles (on a worker thread).
        Returns False once the list is complete. One fetch at a time: a
        suggestion and the background warm-up share the same pages."""
        with self._catalog_lock:
            self._catalog_load()
            if self._catalog_complete:
                return False
            media, more = self._anilist_public.get_popular_titles(self._catalog_next_page)
            for m in media:
                self._catalog[m.id] = (m.title, tuple(m.titles) or (m.title,))
            self._catalog_next_page += 1
            if not more or self._catalog_next_page > self._TITLE_CATALOG_PAGES:
                self._catalog_complete = True
                try:
                    self._catalog_path().write_text(
                        json.dumps({k: [v[0], list(v[1])] for k, v in self._catalog.items()}))
                except OSError:
                    pass
            return not self._catalog_complete

    def _title_catalog(self) -> list[tuple[str, tuple[str, ...]]]:
        """(display title, every name) for the most popular shows fetched so
        far (the whole list is kept on disk for a week), plus every show the
        app has come across."""
        with self._catalog_lock:
            self._catalog_load()
            entries = dict(self._catalog)
        for anilist_id, titles in list(self._titles_by_anilist_id.items()):
            if anilist_id not in entries and titles:
                entries[anilist_id] = (titles[0], tuple(titles))
        return list(entries.values())

    def _warm_title_catalog(self) -> None:
        if os.environ.get("ANIMEPLAYER_DB_PATH"):
            return

        def work() -> None:
            while self._catalog_step():
                pass

        self._pool.start(_Worker(work, lambda _n: None, lambda _m: None))

    @Slot(str)
    def suggestSearch(self, query: str) -> None:
        from animeplayer.suggest import closest_title

        def work() -> str:
            # What's known already; then, if the list is still being built,
            # a page at a time -- the most popular shows come first, and
            # they're what people misspell.
            while True:
                title = closest_title(query, self._title_catalog())
                if title or not self._catalog_step():
                    return title or ""

        self._pool.start(_Worker(work, lambda title: self.searchSuggestion.emit(query, title),
                                 lambda _msg: None))

    # -- hover previews ----------------------------------------------------------
    # Resting the pointer on a poster shows a small card beside it: score,
    # format, genres and the start of the synopsis. Looked up once per show
    # and kept for the session.

    previewReady = Signal(str, "QVariantMap")   # (key the card asked with, details)

    @Slot(result=bool)
    def getHoverPreviewEnabled(self) -> bool:
        return (self._db.get_setting("hover_preview") or "true") == "true"

    @Slot(bool)
    def setHoverPreviewEnabled(self, value: bool) -> None:
        self._db.set_setting("hover_preview", "true" if value else "false")

    @Slot(str, int, str)
    def requestPreview(self, key: str, anilist_id: int, title: str) -> None:
        cache = self._preview_cache
        if key in cache:
            self.previewReady.emit(key, cache[key])
            return
        client = self._anilist_public

        def work() -> dict[str, Any]:
            media = None
            if anilist_id:
                media = client.get_media_by_id(anilist_id)
            elif title:
                found = client.search_media(title)
                wanted = title.casefold()
                media = next((m for m in found if any(t.casefold() == wanted for t in m.titles)),
                             found[0] if found else None)
            if media is None:
                return {}
            description = _strip_html(media.description or "").replace("\n", " ")
            if len(description) > 260:
                description = description[:260].rsplit(" ", 1)[0] + "…"
            status = self._db.get_anilist_status(media.id)
            return {
                "title": media.title,
                "score": media.average_score or 0,
                "format": {"TV_SHORT": "TV Short"}.get(media.format or "", media.format or ""),
                "episodes": media.episodes or 0,
                "genres": list(media.genres[:4]),
                "description": description,
                "list_status": status.status if status else "",
            }

        def done(info: dict[str, Any]) -> None:
            cache[key] = info
            self.previewReady.emit(key, info)

        self._pool.start(_Worker(work, done, lambda _msg: None))

    # -- Anki export -------------------------------------------------------------

    ankiProgress = Signal(int, int)    # (clips done, clips wanted)
    ankiExported = Signal(str, int)    # (file, cards)
    ankiFailed = Signal(str)

    @Slot(str, bool)
    def exportAnki(self, file_url: str, include_audio: bool) -> None:
        """Every saved word as an Anki deck at `file_url` (a path or file://
        URL). With include_audio, each card gets its line's sound, cut from
        the saved episode if there is one, from the stream if not."""
        from PySide6.QtCore import QUrl
        from animeplayer.learn import anki
        from animeplayer.player.downloads import cut_audio

        path = Path(QUrl(file_url).toLocalFile() if file_url.startswith("file:") else file_url)
        if path.suffix.lower() != ".apkg":
            path = path.with_suffix(".apkg")
        words = self.savedWords()

        def work() -> tuple[str, int]:
            clips: dict[int, Path] = {}
            if include_audio:
                folder = Path(tempfile.mkdtemp(prefix="animeplayer-anki-"))
                streams: dict[tuple[str, float], tuple[str, str] | None] = {}
                wanted = [w for w in words if w.get("slug_id") and w.get("episode")]
                for done, w in enumerate(wanted, 1):
                    key = (w["slug_id"], float(w["episode"]))
                    if key not in streams:
                        streams[key] = self._episode_media(*key)
                    media = streams[key]
                    if media is not None:
                        clip = folder / f"animeplayer-{w['id']}.mp3"
                        if cut_audio(media[0], media[1], float(w["position"]) - 0.3, 4.5, clip):
                            clips[w["id"]] = clip
                    self.ankiProgress.emit(done, len(wanted))
            count = anki.build_deck(words, path, clips)
            return str(path), count

        self._pool.start(_Worker(work, lambda r: self.ankiExported.emit(*r), self.ankiFailed.emit))

    def _episode_media(self, slug_id: str, episode_number: float) -> tuple[str, str] | None:
        """(file or stream URL, referer) for an episode: the saved copy if
        there is one, otherwise a fresh stream. None if it can't be had."""
        for entry in self._db.downloads_for(slug_id):
            if entry.status == "ready" and entry.episode_number == episode_number and Path(entry.path).exists():
                return entry.path, ""
        try:
            episodes = source.get_episodes(slug_id, self._http)
            match = next((e for e in episodes if e.number == episode_number), None)
            if match is None:
                return None
            info = source.resolve_source(match.episode_id, self._http)
            return info.master_url, info.referer
        except Exception:  # noqa: BLE001 -- no clip for this one, the card still goes in
            return None

    # -- "What's new" after an update ------------------------------------------

    whatsNew = Signal(str, str)   # (version, release notes)

    def _maybe_show_whats_new(self) -> None:
        """Once, on the first launch of a new version: that version's notes.
        Not on a fresh install -- there's nothing it's new compared to."""
        last = self._db.get_setting("last_run_version")
        self._db.set_setting("last_run_version", updates.VERSION)
        if not last or not updates.is_newer(updates.VERSION, last) or os.environ.get("ANIMEPLAYER_DB_PATH"):
            return
        version = updates.VERSION

        def work() -> str:
            return updates.release_notes(self._http, version)

        def done(notes: str) -> None:
            if notes:
                self.whatsNew.emit(version, notes)

        self._pool.start(_Worker(work, done, lambda _msg: None))

    # -- quick actions from any card or the spotlight ------------------------------
    # Plan to Watch and "add to a Library tab" without opening the show. A
    # card may only know its AniList id (the spotlight, AniList rows) or only
    # its place on the streaming source (search results); each is looked up
    # from the other as needed, with the same cached matching that opening a
    # show uses.

    quickActionDone = Signal(str)   # a sentence for the passive notification

    @Slot(int, str)
    def quickAddToPlanning(self, anilist_id: int, title: str) -> None:
        if self._anilist_client is None:
            self.quickActionDone.emit("Log in to AniList (Settings) to use Plan to Watch.")
            return
        if anilist_id:
            self.setListStatus(anilist_id, "PLANNING")
            self.quickActionDone.emit(f"Added {title} to Planning")
            return
        client = self._anilist_public

        def work() -> int:
            found = client.search_media(title)
            wanted = title.casefold()
            media = next((m for m in found if any(t.casefold() == wanted for t in m.titles)),
                         found[0] if found else None)
            return media.id if media else 0

        def done(media_id: int) -> None:
            if not media_id:
                self.quickActionDone.emit(f"Couldn't find {title} on AniList")
                return
            self.setListStatus(media_id, "PLANNING")
            self.quickActionDone.emit(f"Added {title} to Planning")

        self._pool.start(_Worker(work, done, self.quickActionDone.emit))

    @Slot(int, "QVariantMap")
    def quickAddToLibrary(self, list_id: int, show: dict[str, Any]) -> None:
        tab = next((l["name"] for l in self._db.library_lists() if l["id"] == list_id), "your library")
        title = show.get("title") or ""
        if show.get("slug_id"):
            self.addToLibrary(list_id, show)
            self.quickActionDone.emit(f"Added {title} to {tab}")
            return
        anilist_id = int(show.get("anilist_id") or 0)

        def work() -> dict[str, Any] | None:
            cached = self._db.get_anidb_mapping(anilist_id) if anilist_id else None
            if cached is not None:
                return {"slug_id": cached.slug_id, "numeric_id": cached.numeric_id,
                        "title": cached.title, "poster_url": cached.poster_url}
            titles = self._titles_for(anilist_id, title) if anilist_id else (title,)
            result = matcher.find_source_result(titles, lambda q: source.search(q, self._http))
            if result is None:
                return None
            if anilist_id:
                self._db.save_anidb_mapping(anilist_id, AniDBMapping(
                    anilist_id=anilist_id, slug_id=result.slug_id, numeric_id=result.numeric_id,
                    title=result.title, poster_url=result.poster_url, kind=result.kind))
            return {"slug_id": result.slug_id, "numeric_id": result.numeric_id,
                    "title": result.title, "poster_url": result.poster_url}

        def done(found: dict[str, Any] | None) -> None:
            if found is None:
                self.quickActionDone.emit(f"{title} isn't on the streaming source yet")
                return
            self.addToLibrary(list_id, {**found, "anilist_id": anilist_id,
                                        "poster_url": show.get("poster_url") or found["poster_url"]})
            self.quickActionDone.emit(f"Added {title} to {tab}")

        self._pool.start(_Worker(work, done, self.quickActionDone.emit))

