"""QObject bridge exposing the Python services to QML.

Network calls run on QThreadPool workers so the UI thread never blocks; each
worker reports back by emitting a Qt signal, which is safe to do from any
thread (Qt auto-queues delivery to the GUI-thread QML bindings). self._db is
safe to call directly from worker threads too -- see storage/db.py.
"""

from __future__ import annotations

import json
import re
import socket
import tempfile
import webbrowser
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Callable

import httpx
import qrcode
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from animeplayer.anilist import matcher
from animeplayer.anilist.client import AniListClient, MediaSummary, build_authorize_url
from animeplayer.aniskip import client as aniskip
from animeplayer.player.idle_inhibitor import IdleInhibitor
from animeplayer.remote.server import RemoteServer
from animeplayer.sources import hianime as source
from animeplayer.sources import jikan
from animeplayer.storage import secrets
from animeplayer.storage.db import AniDBMapping, AniListStatus, Database

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

_HTML_TAG_RE = re.compile(r"<[^>]+>")


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
    anilistWatchingChanged = Signal(list)  # Home page "Watching" row
    anilistPlanningChanged = Signal(list)  # Home page "Planning" row
    anilistAnimeResolved = Signal(dict)  # source result for a Home-page AniList card, ready to push DetailPage
    anilistAnimeResolveFailed = Signal(str)  # title we couldn't find a stream for
    anilistAnimeResolveErrored = Signal(str)  # the lookup itself failed (site down, no network, ...)
    anilistGenresLoaded = Signal(list)
    anilistTagsLoaded = Signal(list)
    filterSearchFinished = Signal(dict)  # {results, page, hasMore} -- AniList-sourced results
    recommendationsFailed = Signal(str)  # empty-search recommendations couldn't be built (e.g. not logged in yet)

    skipTimesReady = Signal(dict)  # {"op": {"start","end"}, "ed": {...}} -- either/both keys may be absent
    nextEpisodeLoading = Signal(int, float)  # (episode_id, episode_number) -- fired before streamReady on auto-next
    noNextEpisode = Signal()  # auto-next requested but the current episode is the last one known

    remoteServerFailed = Signal(str)  # the phone remote couldn't start; the app itself is fine
    remoteCommand = Signal(str, "QVariant")  # (cmd, args) from the phone remote -- see remote/server.py

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._http = httpx.Client(follow_redirects=True, timeout=15)
        self._pool = QThreadPool.globalInstance()
        self._db = Database()
        self._current_anime: dict[str, Any] | None = None
        self._current_stream_info: source.StreamInfo | None = None
        self._progressReady.connect(self._save_progress_on_gui_thread)
        self._idle_inhibitor = IdleInhibitor()
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
        self._try_restore_anilist_session()
        self._emit_anilist_home_lists()

        # Live playback snapshot for the phone remote's /api/state poll --
        # kept up to date by PlayerPage.qml calling reportPlaybackState()
        # periodically, since Backend has no direct view into mpv itself.
        self._playback_state: dict[str, Any] = {
            "title": None, "episode_number": 0, "position": 0.0, "duration": 0.0, "paused": True,
        }
        self._remote_server: RemoteServer | None = None
        # Auto-start the phone remote on launch, unless the user explicitly
        # turned it off last time via the Settings Stop button -- requested
        # so "open the anime, then open the phone app" needs zero manual
        # steps in between (no visiting Settings to click Start each time).
        if (self._db.get_setting("remote_enabled") or "true") == "true":
            self.startRemoteServer()

    def _drop_mappings_from_a_previous_source(self) -> None:
        """One-time cache reset when the streaming backend changes underneath
        an existing install -- see Database.clear_anidb_mappings."""
        if self._db.get_setting("stream_source") == source.BASE_URL:
            return
        self._db.clear_anidb_mappings()
        self._db.set_setting("stream_source", source.BASE_URL)

    @Slot(bool)
    def setKeepScreenAwake(self, awake: bool) -> None:
        """Driven straight from "is an episode playing right now" -- see
        player/idle_inhibitor.py for why playback alone doesn't keep the
        session awake. Deliberately follows pause as well as page lifetime:
        pausing and walking away should let the screen sleep normally."""
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
            self.searchFinished.emit([asdict(r) for r in results])
            if self._anilist_client is not None:
                self._match_anilist_statuses(results)

        self._pool.start(_Worker(work, done, self.searchFailed.emit))

    # -- AniList-backed genre/tag search --------------------------------------
    # Deliberately separate from the plain title search above: the streaming source's
    # catalog and genre list are both much smaller than AniList's (confirmed
    # live -- a single source-side genre filter returned ~20-30 results where the
    # same genre on AniList has hundreds), so genre/tag filtering browses
    # AniList's catalog instead and resolves a playable source match lazily,
    # only once a specific result is clicked (openAnilistAnime, reused from the
    # Home page's Watching/Planning cards).

    @Slot()
    def fetchAnilistGenres(self) -> None:
        if self._genre_cache is not None:
            self.anilistGenresLoaded.emit(self._genre_cache)
            return

        def work() -> list[str]:
            return self._anilist_public.get_genre_collection()

        def done(genres: list[str]) -> None:
            self._genre_cache = sorted(genres)
            self.anilistGenresLoaded.emit(self._genre_cache)

        self._pool.start(_Worker(work, done, lambda _msg: None))

    @Slot()
    def fetchAnilistTags(self) -> None:
        if self._tag_cache is not None:
            self.anilistTagsLoaded.emit(self._tag_cache)
            return

        def work() -> list[str]:
            return self._anilist_public.get_tag_collection()

        def done(tags: list[str]) -> None:
            self._tag_cache = sorted(tags)
            self.anilistTagsLoaded.emit(self._tag_cache)

        self._pool.start(_Worker(work, done, lambda _msg: None))

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

    @staticmethod
    def _media_summary_to_card(m: MediaSummary) -> dict[str, Any]:
        return {
            "anilist_id": m.id,
            "title": m.title,
            "poster_url": m.cover_url or "",
            "kind": m.format or "",
            # Empty rather than "0.0" when AniList has no score yet, so the
            # card can leave the star out instead of advertising a zero.
            "rating": f"{m.average_score / 10:.1f}" if m.average_score else "",
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

    @Slot(str, list, list, list, list, list, list, list, list, int)
    def searchByFilters(
        self,
        query: str,
        genres: list,
        exclude_genres: list,
        tags: list,
        exclude_tags: list,
        status_include: list,
        status_exclude: list,
        formats: list,
        exclude_formats: list,
        page: int,
    ) -> None:
        def work() -> tuple[list[MediaSummary], bool]:
            return self._anilist_public.search_by_filters(
                query, genres, tags,
                exclude_genres=exclude_genres, exclude_tags=exclude_tags,
                formats=formats, exclude_formats=exclude_formats,
                page=page,
            )

        def done(result: tuple[list[MediaSummary], bool]) -> None:
            results, has_more = result
            # Status (Watching/Planning/Completed/... or "not in my list") isn't
            # part of AniList's public catalog filters -- it's this user's own
            # list data, so it's applied locally after the catalog page comes
            # back. This means a page can come back with fewer visible results
            # than 50 after filtering even though has_more is still true --
            # "Load more" just keeps pulling subsequent catalog pages.
            filtered = self._apply_status_filter(results, status_include, status_exclude)
            ranked = self._affinity_sorted(filtered)
            self.filterSearchFinished.emit(
                {
                    "results": [self._media_summary_to_card(m) for m in ranked],
                    "page": page,
                    "hasMore": has_more,
                }
            )

        self._pool.start(_Worker(work, done, self.searchFailed.emit))

    @Slot()
    def loadRecommendations(self) -> None:
        """Empty search (no query/genre/tag): surface sequels/later seasons of
        shows the user has completed or is currently watching but hasn't
        added to their list yet -- e.g. watched season 1+2 of something,
        season 3 exists and isn't in any of their AniList lists yet."""
        source_entries = self._db.get_anilist_by_status("COMPLETED") + self._db.get_anilist_by_status("CURRENT")
        if not source_entries:
            self.recommendationsFailed.emit(
                "Log in to AniList and watch a few shows to see recommendations here."
            )
            return

        known_ids: set[int] = set()
        for status in ("CURRENT", "PLANNING", "COMPLETED", "DROPPED", "PAUSED", "REPEATING"):
            known_ids.update(e.anilist_id for e in self._db.get_anilist_by_status(status))
        source_ids = [e.anilist_id for e in source_entries]

        def work() -> dict[int, list[MediaSummary]]:
            return self._anilist_public.get_sequel_relations(source_ids)

        def done(relations: dict[int, list[MediaSummary]]) -> None:
            seen: dict[int, MediaSummary] = {}
            for sequels in relations.values():
                for m in sequels:
                    if m.id not in known_ids:
                        seen[m.id] = m
            if not seen:
                self.recommendationsFailed.emit(
                    "No unwatched sequels found -- looks like you're all caught up."
                )
                return
            ranked = self._affinity_sorted(list(seen.values()))
            self.filterSearchFinished.emit(
                {
                    "results": [self._media_summary_to_card(m) for m in ranked],
                    "page": 1,
                    "hasMore": False,
                }
            )

        self._pool.start(_Worker(work, done, self.recommendationsFailed.emit))

    @Slot(str, str, str, str)
    def loadEpisodes(self, slug_id: str, numeric_id: str, title: str, poster_url: str) -> None:
        self._current_anime = {
            "slug_id": slug_id,
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
            match = matcher.best_source_result(title, source.search(title, self._http))
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
            if self._current_anime is not None and self._current_anime["slug_id"] == slug_id:
                self._current_anime["slug_id"] = new_slug_id
                self._current_anime["episode_count"] = len(episodes)
                self._current_anime["has_filler_data"] = any(e.filler for e in episodes)
                self._current_anime["episodes"] = episodes
                self._maybe_fetch_filler_fallback(new_slug_id)
            if self._anilist_client is not None:
                self._resolve_current_anime_status(new_slug_id, title)

        self._pool.start(_Worker(work, done, self.episodesFailed.emit))

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

        def work() -> set[int]:
            return jikan.get_filler_episodes(mal_id, self._http)

        def done(filler_numbers: set[int]) -> None:
            if filler_numbers:
                self.fillerEpisodesUpdated.emit(sorted(filler_numbers))

        self._pool.start(_Worker(work, done, lambda _msg: None))

    @Slot(int, float, bool)
    def loadStream(self, episode_id: int, episode_number: float, dub: bool = False) -> None:
        anime_snapshot = dict(self._current_anime) if self._current_anime else None
        preferred = self.getPreferredQuality()
        if self._current_anime is not None:
            self._current_anime["current_episode_number"] = episode_number

        def finish_up(info: source.StreamInfo) -> None:
            self._progressReady.emit(episode_id, episode_number)
            if self._anilist_client is not None and anime_snapshot and anime_snapshot.get("anilist_id"):
                self._push_anilist_progress(anime_snapshot, episode_number)
            # The source hands back the MAL id with the stream, which is often
            # the only place we get one: the AniList path only supplies it when
            # the user is logged in and the title matched. Feeding it back here
            # is what lets ani-skip and the Jikan filler lookup work logged-out.
            self._adopt_mal_id(info.mal_id)
            self._emit_skip_times(info, episode_number)

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
        times = {}
        if info.skip_intro:
            times["op"] = {"start": info.skip_intro[0], "end": info.skip_intro[1]}
        if info.skip_outro:
            times["ed"] = {"start": info.skip_outro[0], "end": info.skip_outro[1]}
        if times:
            self.skipTimesReady.emit(times)
            return
        self._maybe_fetch_skip_times(episode_number)

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
        if not candidates:
            self.noNextEpisode.emit()
            return
        next_episode = candidates[0]
        self.nextEpisodeLoading.emit(next_episode.episode_id, next_episode.number)
        self.loadStream(next_episode.episode_id, next_episode.number, dub)

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

    @Slot(result=bool)
    def getAutoNextEnabled(self) -> bool:
        return (self._db.get_setting("auto_next_enabled") or "true") == "true"

    @Slot(bool)
    def setAutoNextEnabled(self, value: bool) -> None:
        self._db.set_setting("auto_next_enabled", "true" if value else "false")

    @Slot(result=int)
    def getCurrentEpisodeCount(self) -> int:
        anime = self._current_anime
        return int(anime.get("episode_count") or 0) if anime else 0

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
        return {"episode_number": entry.episode_number, "position_seconds": entry.position_seconds}

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

    @Slot(int, float, float)
    def savePlaybackPosition(self, episode_id: int, episode_number: float, position_seconds: float) -> None:
        if not self._current_anime:
            return
        self._db.save_progress(
            anime_slug_id=self._current_anime["slug_id"],
            anime_title=self._current_anime["title"],
            poster_url=self._current_anime["poster_url"],
            episode_id=episode_id,
            episode_number=episode_number,
            position_seconds=position_seconds,
            duration_seconds=0,
        )

    @Slot()
    def refreshContinueWatching(self) -> None:
        self._emit_continue_watching()

    def _emit_continue_watching(self) -> None:
        entries = self._db.continue_watching()
        self.continueWatchingChanged.emit(
            [
                {
                    "slug_id": e.anime_slug_id,
                    "numeric_id": e.anime_slug_id.rsplit("-", 1)[-1],
                    "title": e.anime_title,
                    "poster_url": e.poster_url or "",
                    "episode_number": e.episode_number,
                    "position_seconds": e.position_seconds,
                    "duration_seconds": e.duration_seconds,  # lets the card draw a real resume bar
                }
                for e in entries
            ]
        )

    # -- AniList: settings ---------------------------------------------------

    @Slot(result=str)
    def anilistClientId(self) -> str:
        return self._db.get_setting("anilist_client_id") or ""

    @Slot(str)
    def setAnilistClientId(self, value: str) -> None:
        self._db.set_setting("anilist_client_id", value.strip())

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
                    )
                    for e in entries
                ]
            )
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

        self.anilistWatchingChanged.emit(as_dicts(self._db.get_anilist_by_status("CURRENT")))

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

        def work() -> source.SearchResult | None:
            results = source.search(title, self._http)
            return matcher.best_source_result(title, results)

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

    def _match_anilist_statuses(self, results: list[source.SearchResult]) -> None:
        client = self._anilist_client
        if client is None:
            return

        def work() -> dict[str, dict[str, Any]]:
            matches: dict[str, dict[str, Any]] = {}
            for result in results:
                media_id = matcher.resolve_media_id(result.title, client, self._db)
                if media_id is None:
                    continue
                status = self._db.get_anilist_status(media_id)
                if status is not None:
                    matches[result.slug_id] = {
                        "status": status.status,
                        "label": _STATUS_LABELS.get(status.status, status.status),
                        "progress": status.progress,
                    }
            return matches

        def done(matches: dict[str, dict[str, Any]]) -> None:
            if matches:
                self.anilistStatusesResolved.emit(matches)

        self._pool.start(_Worker(work, done, lambda _msg: None))

    def _resolve_current_anime_status(self, slug_id: str, title: str) -> None:
        client = self._anilist_client
        if client is None:
            return

        def work() -> tuple[MediaSummary | None, AniListStatus | None]:
            summary = matcher.resolve_media_summary(title, client, self._db)
            status = self._db.get_anilist_status(summary.id) if summary is not None else None
            return summary, status

        def done(result: tuple[MediaSummary | None, AniListStatus | None]) -> None:
            summary, status = result
            media_id = summary.id if summary is not None else None
            if self._current_anime is not None and self._current_anime["slug_id"] == slug_id:
                self._current_anime["anilist_id"] = media_id
                self._current_anime["mal_id"] = summary.id_mal if summary is not None else None
                self._maybe_fetch_filler_fallback(slug_id)
                current_episode_number = self._current_anime.get("current_episode_number")
                if current_episode_number is not None:
                    self._maybe_fetch_skip_times(current_episode_number)
            if status is not None:
                self.anilistCurrentStatus.emit(
                    _STATUS_LABELS.get(status.status, status.status), status.progress
                )
            else:
                self.anilistCurrentStatus.emit("", 0)
            if summary is not None:
                self.anilistMediaDetails.emit(
                    {
                        "average_score": summary.average_score or 0,
                        "genres": list(summary.genres),
                        "format": summary.format or "",
                        "episodes": summary.episodes or 0,
                        "description": _strip_html(summary.description or ""),
                        "cover_url": summary.cover_url or "",
                    }
                )

        self._pool.start(_Worker(work, done, lambda _msg: None))

    def _push_anilist_progress(self, anime_snapshot: dict[str, Any], episode_number: float) -> None:
        client = self._anilist_client
        media_id = anime_snapshot.get("anilist_id")
        if client is None or media_id is None:
            return
        episode_count = anime_snapshot.get("episode_count")
        status = "COMPLETED" if episode_count and episode_number >= episode_count else "CURRENT"
        progress = int(episode_number)

        def work() -> None:
            client.save_progress(media_id, status, progress)

        def done(_result: None) -> None:
            existing = self._db.get_anilist_status(media_id)
            score = existing.score if existing else 0.0
            title = existing.title if existing else anime_snapshot["title"]
            cover_url = existing.cover_url if existing else anime_snapshot.get("poster_url")
            self._db.upsert_anilist_status(
                AniListStatus(
                    anilist_id=media_id, status=status, progress=progress, score=score,
                    title=title, cover_url=cover_url,
                )
            )
            self._emit_anilist_home_lists()

        self._pool.start(_Worker(work, done, self.anilistError.emit))
