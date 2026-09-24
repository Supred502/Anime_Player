"""QObject bridge exposing the Python services to QML.

Network calls run on QThreadPool workers so the UI thread never blocks; each
worker reports back by emitting a Qt signal, which is safe to do from any
thread (Qt auto-queues delivery to the GUI-thread QML bindings). self._db is
safe to call directly from worker threads too -- see storage/db.py.
"""

from __future__ import annotations

import json
import random
import re
import socket
import tempfile
import webbrowser
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Callable

import httpx
import qrcode
from PySide6.QtCore import Property, QObject, QRunnable, QThreadPool, Signal, Slot

from animeplayer.anilist import matcher
from animeplayer.anilist.client import (
    AniListClient,
    ChainEntry,
    MediaSummary,
    build_authorize_url,
)
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
    _HOME_ROW_CATALOG = {"trending": "most-popular"}

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

    @Slot(result=list)
    def catalogs(self) -> list[dict[str, str]]:
        """Every browsable catalog, for the Browse page's category picker."""
        return [{"key": key, "label": label} for key, label in source.CATALOGS.items()]

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
            self.homeSpotlightReady.emit([self._spotlight_to_card(s) for s in spotlight])
            self.homeRowReady.emit(
                "trending", [self._search_result_to_card(r) for r in trending]
            )

        def highlights_failed(message: str) -> None:
            self.homeRowFailed.emit("trending", message)

        self._pool.start(_Worker(highlights, highlights_done, highlights_failed))

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

    @Slot(str, int)
    def browseCatalog(self, category: str, page: int) -> None:
        """One page of a named catalog, for the Browse page's infinite scroll."""
        token = self._begin_browse()

        def work() -> source.CatalogPage:
            return source.browse(category, max(1, page), self._http)

        def done(result: source.CatalogPage) -> None:
            self._emit_browse_page(category, result, token)

        self._pool.start(_Worker(work, done, self._browse_failed(token)))

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

    def _emit_browse_page(self, key: str, result: source.CatalogPage, token: int) -> None:
        if token != self._browse_token:
            return
        self.browseFinished.emit(
            {
                "key": key,
                "results": [self._search_result_to_card(r) for r in result.results],
                "page": result.page,
                "hasMore": result.has_more,
            }
        )
        self._match_anilist_statuses(list(result.results))

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

    # dict, not a long positional list: this grew from four filters to ten,
    # and a ten-argument slot means every new filter is an edit in three
    # places. QML passes the same field names the AniList client takes.
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
            # Only re-rank by affinity when the user hasn't asked for an order.
            # Sorting their chosen "highest scored first" by genre overlap
            # instead is the kind of helpfulness that reads as a bug.
            ranked = filtered if spec.get("sort") else self._affinity_sorted(filtered)
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
            if self._current_anime is not None and self._current_anime["slug_id"] == slug_id:
                self._current_anime["slug_id"] = new_slug_id
                self._current_anime["episode_count"] = len(episodes)
                self._current_anime["has_filler_data"] = any(e.filler for e in episodes)
                self._current_anime["episodes"] = episodes
                self._maybe_fetch_filler_fallback(new_slug_id)
            # Unconditional: what this fills in is public AniList data (see
            # _resolve_current_anime_status), and gating it on being logged in
            # meant a logged-out detail page showed a title and nothing else.
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
                "watchOrder": chain,
                "unwatchedPrequels": unwatched,
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
                self._fetch_anime_extras(summary.id, slug_id)
                self.anilistMediaDetails.emit(
                    {
                        "average_score": summary.average_score or 0,
                        "genres": list(summary.genres),
                        "format": summary.format or "",
                        "episodes": summary.episodes or 0,
                        "description": _strip_html(summary.description or ""),
                        "cover_url": summary.cover_url or "",
                        "banner_url": summary.banner_url or "",
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

        self._pool.start(_Worker(work, done, self.anilistError.emit))
