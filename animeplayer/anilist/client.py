"""GraphQL client for AniList (https://graphql.anilist.co).

Login uses AniList's "Auth Pin" implicit-grant variant: the user authorizes in
their browser and AniList shows them the access token to copy into the app,
rather than this app running a local HTTP server to catch a redirect. That's
AniList's own documented recommendation for apps without a redirect server --
see https://docs.anilist.co/guide/auth/ ("Auth Pin"). To use it, the user's
AniList API client (created at anilist.co/settings/developer) must have its
Redirect URL set to exactly https://anilist.co/api/v2/oauth/pin.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Any

import httpx

API_URL = "https://graphql.anilist.co"
USER_AGENT = "AnimePlayer/1.0 (+https://github.com/Supred502/Anime_Player)"
AUTHORIZE_URL_TEMPLATE = "https://anilist.co/api/v2/oauth/authorize?client_id={client_id}&response_type=token"

_VIEWER_QUERY = """
query {
  Viewer { id name }
}
"""

_MEDIA_LIST_COLLECTION_QUERY = """
query ($userId: Int!) {
  MediaListCollection(userId: $userId, type: ANIME) {
    lists {
      entries {
        status
        progress
        score
        media {
          id
          title { romaji english }
          synonyms
          coverImage { large }
          genres
          popularity
        }
      }
    }
  }
}
"""

_MEDIA_FIELDS = """
    id
    idMal
    title { romaji english }
    synonyms
    coverImage { large }
    bannerImage
    countryOfOrigin
    averageScore
    popularity
    genres
    format
    episodes
    description(asHtml: false)
"""

_MEDIA_SEARCH_QUERY = f"""
query ($search: String) {{
  Page(perPage: 5) {{
    media(search: $search, type: ANIME) {{
      {_MEDIA_FIELDS}
    }}
  }}
}}
"""

_MEDIA_BY_ID_QUERY = f"""
query ($id: Int!) {{
  Media(id: $id) {{
    {_MEDIA_FIELDS}
  }}
}}
"""

# genre_in/tag_in are AniList's own catalog filters -- this is the whole reason
# genre/tag search goes through AniList rather than the streaming source: the
# catalog and genre taxonomy are both far smaller (confirmed live: ~20-30
# results for a single source-side genre filter vs AniList's hundreds).
# pageInfo.hasNextPage lets the UI offer "Load more" instead of silently
# capping results at one page of 50.
#
# format_in/format_not_in are built dynamically (see _build_filter_search_query
# below) rather than always-present optional variables like genres/tags are --
# confirmed live against the real API that AniList's server 500s whenever a
# $formats/$notFormats variable of type [MediaFormat] is present in the query
# at all and passed null, even though the exact same null-when-unused pattern
# works fine for the [String]-typed genre/tag variables. Passing [] instead of
# null avoids the 500 but silently matches zero results instead of "no
# filter" -- the argument has to be left out of the query text entirely.
# Every optional filter, as (GraphQL variable declaration, media argument).
# They are assembled into the query text only when actually used -- see the
# comment above for why an unused enum-typed variable cannot simply be passed
# as null.
_FILTER_ARGUMENTS: dict[str, tuple[str, str]] = {
    "formats": ("$formats: [MediaFormat]", "format_in: $formats"),
    "notFormats": ("$notFormats: [MediaFormat]", "format_not_in: $notFormats"),
    "country": ("$country: CountryCode", "countryOfOrigin: $country"),
    "minScore": ("$minScore: Int", "averageScore_greater: $minScore"),
    "season": ("$season: MediaSeason", "season: $season"),
    "seasonYear": ("$seasonYear: Int", "seasonYear: $seasonYear"),
    "statuses": ("$statuses: [MediaStatus]", "status_in: $statuses"),
    "notStatuses": ("$notStatuses: [MediaStatus]", "status_not_in: $notStatuses"),
    "sort": ("$sort: [MediaSort]", "sort: $sort"),
}


def _build_filter_search_query(used: list[str]) -> str:
    declarations = [_FILTER_ARGUMENTS[name][0] for name in used]
    arguments = [_FILTER_ARGUMENTS[name][1] for name in used]
    extra_vars = ("\n  " + ", ".join(declarations) + ",") if declarations else ""
    extra_args = (" " + ", ".join(arguments) + ",") if arguments else ""
    # sort is in the optional set, so a query that doesn't ask for one still
    # needs a default -- popularity, which is what "browse this genre" means.
    default_sort = "" if "sort" in used else " sort: POPULARITY_DESC,"
    return f"""
query (
  $search: String, $genres: [String], $notGenres: [String], $tags: [String], $notTags: [String],{extra_vars}
  $page: Int
) {{
  Page(perPage: 50, page: $page) {{
    pageInfo {{ hasNextPage }}
    media(
      search: $search, genre_in: $genres, genre_not_in: $notGenres,
      tag_in: $tags, tag_not_in: $notTags,{extra_args}
      type: ANIME,{default_sort} isAdult: false
    ) {{
      {_MEDIA_FIELDS}
    }}
  }}
}}
"""

_GENRE_COLLECTION_QUERY = """
query {
  GenreCollection
}
"""

_TAG_COLLECTION_QUERY = """
query {
  MediaTagCollection {
    name
    isAdult
  }
}
"""

# The two "what should I watch next" signals, fetched together because they
# come from the same media objects and a second round trip per batch would
# double the cost for nothing:
#
#   * SEQUEL relations -- "you finished season 1, season 2 exists". Precise,
#     but only ever suggests more of what's already been watched.
#   * recommendations -- AniList's community "if you liked this, try that",
#     ordered by how many people agreed. This is what makes the feature
#     suggest something genuinely new.
#
# The caller cross-references both against the user's full list locally to
# drop anything already added in any status.
_RECOMMENDATION_SOURCES_QUERY = f"""
query ($ids: [Int]) {{
  Page(perPage: 50) {{
    media(id_in: $ids, type: ANIME) {{
      id
      title {{ romaji english }}
      relations {{
        edges {{
          relationType
          node {{
            {_MEDIA_FIELDS}
          }}
        }}
      }}
      recommendations(perPage: 8, sort: RATING_DESC) {{
        nodes {{
          rating
          mediaRecommendation {{
            {_MEDIA_FIELDS}
          }}
        }}
      }}
    }}
  }}
}}
"""

# A page of the catalog by popularity, used to pick something at random. Only
# ids/titles are needed to choose, but the full fields come back so the chosen
# one needs no follow-up request.
_POPULAR_PAGE_QUERY = f"""
query ($page: Int, $formats: [MediaFormat]) {{
  Page(perPage: 50, page: $page) {{
    pageInfo {{ lastPage }}
    media(type: ANIME, format_in: $formats, sort: POPULARITY_DESC, isAdult: false) {{
      {_MEDIA_FIELDS}
    }}
  }}
}}
"""

_SAVE_MEDIA_LIST_ENTRY_MUTATION = """
mutation ($mediaId: Int, $status: MediaListStatus, $progress: Int) {
  SaveMediaListEntry(mediaId: $mediaId, status: $status, progress: $progress) {
    id
  }
}
"""


_DELETE_MEDIA_LIST_ENTRY_MUTATION = """
mutation ($id: Int) {
  DeleteMediaListEntry(id: $id) { deleted }
}
"""

# Deleting needs the *entry* id, not the media id, and the only way to learn
# it is to ask for the viewer's entry for that media.
_MEDIA_LIST_ENTRY_ID_QUERY = """
query ($mediaId: Int, $userId: Int) {
  MediaList(mediaId: $mediaId, userId: $userId, type: ANIME) { id status }
}
"""


class AniListError(Exception):
    """A GraphQL request succeeded at the HTTP level but returned errors."""


@dataclass(frozen=True, slots=True)
class Viewer:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class ListEntry:
    media_id: int
    status: str  # CURRENT, PLANNING, COMPLETED, DROPPED, PAUSED, REPEATING
    progress: int
    score: float
    title: str  # primary display title (english, falling back to romaji)
    cover_url: str | None
    titles: tuple[str, ...]  # romaji, english, synonyms -- used for title matching
    genres: tuple[str, ...]
    popularity: int


@dataclass(frozen=True, slots=True)
class MediaSummary:
    id: int
    id_mal: int | None  # MyAnimeList id -- used for the Jikan filler-episode fallback
    title: str  # primary display title (english, falling back to romaji)
    titles: tuple[str, ...]  # romaji, english, synonyms -- used for title matching
    cover_url: str | None
    # Wide key art, for the detail page's header. Often null -- AniList only
    # has one for the better-known entries, so anything using it needs a
    # fallback to the cover.
    banner_url: str | None
    # Two-letter code (JP, CN, KR, TW). AniList can filter *to* one country
    # but has no country_not_in, so excluding one is done on the results.
    country: str | None
    average_score: int | None  # 0-100, AniList's own scale
    popularity: int
    genres: tuple[str, ...]
    format: str | None  # e.g. "TV", "MOVIE", "OVA"
    episodes: int | None
    description: str | None  # plain-ish text; still needs HTML tags stripped for display


def build_authorize_url(client_id: str) -> str:
    return AUTHORIZE_URL_TEMPLATE.format(client_id=client_id)


def _titles_of(media: dict) -> tuple[str, ...]:
    title = media.get("title", {})
    candidates = [title.get("romaji"), title.get("english"), *media.get("synonyms", [])]
    return tuple(t for t in candidates if t)


def _primary_title(media: dict) -> str:
    title = media.get("title", {})
    return title.get("english") or title.get("romaji") or "Unknown"


def _media_summary_of(media: dict) -> MediaSummary:
    return MediaSummary(
        id=media["id"],
        id_mal=media.get("idMal"),
        title=_primary_title(media),
        titles=_titles_of(media),
        cover_url=(media.get("coverImage") or {}).get("large"),
        banner_url=media.get("bannerImage"),
        country=media.get("countryOfOrigin"),
        average_score=media.get("averageScore"),
        popularity=media.get("popularity") or 0,
        genres=tuple(media.get("genres") or []),
        format=media.get("format"),
        episodes=media.get("episodes"),
        description=media.get("description"),
    )


# AniList publishes a 90 requests/minute budget and has been serving a
# degraded 30/minute for some time now. Either way the app has to stay under
# it on its own, because the only feedback the server gives is a 429 that has
# already cost the user whatever they were looking at -- which is exactly what
# they hit after a few trips between Home and Browse.
#
# Deliberately under 30 rather than at it: the window the server measures is
# not the window measured here, so a burst that is exactly at the limit
# locally can still straddle the boundary there.
_REQUESTS_PER_MINUTE = 25
_RATE_WINDOW_SECONDS = 60.0
# How long a read stays good for. Everything this app asks AniList is a
# catalog or a list, and neither changes minute to minute -- whereas going
# Home, Browse, Home costs the same three queries again every time without
# this. Mutations bypass it in both directions (see _request).
_CACHE_TTL_SECONDS = 300.0
_CACHE_MAX_ENTRIES = 256


class _RateLimiter:
    """Spreads requests across a sliding window, shared by every client.

    Shared, not per-client, because AniList counts per user/IP and this app
    runs an unauthenticated client for catalog browsing alongside the
    logged-in one. Blocking (rather than dropping) is right here: every caller
    is already on a worker thread, so waiting costs a slower row, not a frozen
    window.
    """

    def __init__(self, limit: int = _REQUESTS_PER_MINUTE, window: float = _RATE_WINDOW_SECONDS) -> None:
        self._limit = limit
        self._window = window
        self._times: deque[float] = deque()
        self._lock = threading.Lock()
        # Set from a 429's Retry-After: a wall everything waits behind, so one
        # rejected request doesn't let the other nine workers keep hammering.
        self._blocked_until = 0.0

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._times and now - self._times[0] >= self._window:
                    self._times.popleft()
                wait = max(0.0, self._blocked_until - now)
                if wait <= 0 and len(self._times) < self._limit:
                    self._times.append(now)
                    return
                if wait <= 0:
                    wait = self._window - (now - self._times[0])
            time.sleep(max(0.05, wait))

    def back_off(self, seconds: float) -> None:
        with self._lock:
            self._blocked_until = max(self._blocked_until, time.monotonic() + seconds)


_limiter = _RateLimiter()


class _Counter:
    """Counts real network calls, for measuring how much this app actually
    asks of AniList. Off unless ANIMEPLAYER_COUNT_ANILIST is set."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.on = bool(os.environ.get("ANIMEPLAYER_COUNT_ANILIST"))

    def record(self, query: str) -> None:
        if not self.on:
            return
        name = "unknown"
        for line in query.strip().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith(("query", "mutation", "{")):
                name = stripped.split("(")[0].split("{")[0].strip()
                break
        self.calls.append(name)


_counter = _Counter()


class AniListClient:
    # Shared across instances for the same reason the limiter is: the
    # unauthenticated catalog client and the logged-in one are two views of
    # one budget. Keyed by token as well as query, so one user's list can
    # never be served to another.
    _cache: "OrderedDict[tuple, tuple[float, dict]]" = OrderedDict()
    _cache_lock = threading.Lock()

    def __init__(self, client: httpx.Client, token: str | None = None) -> None:
        """token is only required for viewer-specific calls (get_viewer,
        get_list_collection, save_progress). Search/genre/tag queries are
        public AniList data and work fine without one -- callers who aren't
        logged in still get genre/tag search."""
        self._token = token
        self._client = client

    @classmethod
    def clear_cache(cls) -> None:
        """Drops every cached read. Called after anything that writes to the
        user's list, so the next read reflects the write instead of a
        five-minute-old copy of it."""
        with cls._cache_lock:
            cls._cache.clear()

    @classmethod
    def _cached(cls, key: tuple) -> dict | None:
        with cls._cache_lock:
            hit = cls._cache.get(key)
            if hit is None:
                return None
            stored_at, data = hit
            if time.monotonic() - stored_at > _CACHE_TTL_SECONDS:
                del cls._cache[key]
                return None
            cls._cache.move_to_end(key)
            return data

    # Identical queries that are already in flight, so a second caller waits
    # for the first one's answer instead of asking again. The cache alone does
    # not cover this: three filter toggles in a second all miss, because none
    # of them has come back yet to populate it. Measured -- three identical
    # searches fired together cost three requests before this, and one after.
    _inflight: dict[tuple, threading.Event] = {}
    _inflight_lock = threading.Lock()

    @classmethod
    def _remember(cls, key: tuple, data: dict) -> None:
        with cls._cache_lock:
            cls._cache[key] = (time.monotonic(), data)
            cls._cache.move_to_end(key)
            while len(cls._cache) > _CACHE_MAX_ENTRIES:
                cls._cache.popitem(last=False)

    # How many times to sit out a 429 before giving up and telling the user.
    _RETRY_ATTEMPTS = 3
    # AniList's Retry-After is in whole seconds and is usually well under a
    # minute, but a bad value shouldn't be able to wedge a worker thread.
    _MAX_BACKOFF_SECONDS = 70.0

    def _request(self, query: str, variables: dict | None = None, *, cache: bool = True) -> dict:
        variables = variables or {}
        key = (self._token or "", query, json.dumps(variables, sort_keys=True, default=str))
        if cache:
            hit = self._cached(key)
            if hit is not None:
                return hit
            # Someone else is already asking this exact question -- wait for
            # their answer rather than asking it again.
            with self._inflight_lock:
                waiting = self._inflight.get(key)
                if waiting is None:
                    self._inflight[key] = threading.Event()
            if waiting is not None:
                # Bounded: if the leader dies without setting the event, this
                # falls through and makes the request itself rather than
                # hanging the worker thread forever.
                waiting.wait(timeout=self._INFLIGHT_WAIT_SECONDS)
                hit = self._cached(key)
                if hit is not None:
                    return hit

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            # AniList asks third-party clients to identify themselves so they
            # can see where their API traffic comes from (and contact an app
            # that misbehaves rather than just blocking it).
            "User-Agent": USER_AGENT,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        try:
            data = self._send(query, variables, headers)
        finally:
            if cache:
                with self._inflight_lock:
                    done = self._inflight.pop(key, None)
                if done is not None:
                    done.set()
        if cache:
            self._remember(key, data)
        return data

    # How long a caller waits on an identical in-flight request before giving
    # up and making its own.
    _INFLIGHT_WAIT_SECONDS = 30.0

    def _send(self, query: str, variables: dict, headers: dict) -> dict:
        for attempt in range(self._RETRY_ATTEMPTS):
            _limiter.acquire()
            _counter.record(query)
            resp = self._client.post(API_URL, json={"query": query, "variables": variables}, headers=headers)
            if resp.status_code == 429 and attempt < self._RETRY_ATTEMPTS - 1:
                # Retry-After is what AniList actually tells us to wait; the
                # window length is the honest fallback when the header is
                # missing or unparseable.
                try:
                    wait = float(resp.headers.get("Retry-After", ""))
                except ValueError:
                    wait = _RATE_WINDOW_SECONDS
                wait = min(max(wait, 1.0), self._MAX_BACKOFF_SECONDS)
                _limiter.back_off(wait)
                continue
            break

        if resp.status_code == 429:
            raise AniListError(
                "AniList is rate-limiting us right now -- give it a minute and try again."
            )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            messages = "; ".join(e.get("message", "unknown error") for e in payload["errors"])
            raise AniListError(messages)
        return payload["data"]

    def get_viewer(self) -> Viewer:
        data = self._request(_VIEWER_QUERY)
        viewer = data["Viewer"]
        return Viewer(id=viewer["id"], name=viewer["name"])

    def get_list_collection(self, user_id: int) -> list[ListEntry]:
        # Uncached: this is the "refresh my list" call, and a refresh that can
        # answer from a cache is not a refresh.
        data = self._request(_MEDIA_LIST_COLLECTION_QUERY, {"userId": user_id}, cache=False)
        entries: list[ListEntry] = []
        for lst in data["MediaListCollection"]["lists"]:
            for entry in lst["entries"]:
                media = entry["media"]
                entries.append(
                    ListEntry(
                        media_id=media["id"],
                        status=entry["status"],
                        progress=entry["progress"],
                        score=entry["score"],
                        title=_primary_title(media),
                        cover_url=(media.get("coverImage") or {}).get("large"),
                        titles=_titles_of(media),
                        genres=tuple(media.get("genres") or []),
                        popularity=media.get("popularity") or 0,
                    )
                )
        return entries

    def search_media(self, query: str) -> list[MediaSummary]:
        data = self._request(_MEDIA_SEARCH_QUERY, {"search": query})
        return [_media_summary_of(m) for m in data["Page"]["media"]]

    def get_media_by_id(self, media_id: int) -> MediaSummary:
        data = self._request(_MEDIA_BY_ID_QUERY, {"id": media_id})
        return _media_summary_of(data["Media"])

    def get_genre_collection(self) -> list[str]:
        data = self._request(_GENRE_COLLECTION_QUERY)
        return list(data["GenreCollection"])

    def get_tag_collection(self) -> list[str]:
        data = self._request(_TAG_COLLECTION_QUERY)
        return [t["name"] for t in data["MediaTagCollection"] if not t.get("isAdult")]

    def search_by_filters(
        self,
        search: str,
        genres: list[str],
        tags: list[str],
        *,
        exclude_genres: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        formats: list[str] | None = None,
        exclude_formats: list[str] | None = None,
        country: str | None = None,
        min_score: int | None = None,
        season: str | None = None,
        season_year: int | None = None,
        statuses: list[str] | None = None,
        exclude_statuses: list[str] | None = None,
        sort: str | None = None,
        page: int = 1,
    ) -> tuple[list[MediaSummary], bool]:
        """Browses AniList's own catalog, optionally combined with a title
        search. This is what the app's filtering uses rather than the source's
        own filter endpoint: AniList can exclude as well as include, knows
        tags and country of origin, and has a far larger catalog. Returns
        (results, has_next_page).

        formats/exclude_formats use AniList's MediaFormat enum (TV, TV_SHORT,
        MOVIE, SPECIAL, OVA, ONA, MUSIC); country is a two-letter code (JP,
        CN, KR, TW); season is a MediaSeason (WINTER, SPRING, SUMMER, FALL).
        """
        variables: dict[str, Any] = {
            "search": search or None,
            "genres": genres or None,
            "notGenres": exclude_genres or None,
            "tags": tags or None,
            "notTags": exclude_tags or None,
            "page": page,
        }
        optional = {
            "formats": formats or None,
            "notFormats": exclude_formats or None,
            "country": country or None,
            "minScore": min_score or None,
            "season": season or None,
            "seasonYear": season_year or None,
            "statuses": statuses or None,
            "notStatuses": exclude_statuses or None,
            # A typed title with no chosen order sorts by how well it matches
            # what was typed. Without this the query falls through to the
            # POPULARITY_DESC default, and searching "Dorohedoro" answered
            # with Re:ZERO -- the most popular thing AniList thought was
            # vaguely relevant (confirmed live through the real search field).
            "sort": [sort] if sort else (["SEARCH_MATCH"] if search else None),
        }
        used = [name for name, value in optional.items() if value]
        variables.update({name: optional[name] for name in used})
        data = self._request(_build_filter_search_query(used), variables)
        page_data = data["Page"]
        results = [_media_summary_of(m) for m in page_data["media"]]
        has_next = bool((page_data.get("pageInfo") or {}).get("hasNextPage"))
        return results, has_next

    def get_recommendation_sources(
        self, media_ids: list[int]
    ) -> list[tuple[str, MediaSummary, str, int]]:
        """For each given anime, what to watch after it.

        Returns (kind, suggestion, because_of_title, weight) rows, where kind
        is "sequel" or "similar". AniList pages this 50 ids at a time, so a
        longer list is fetched in batches -- the caller decides how many of the
        user's shows are worth spending requests on.
        """
        rows: list[tuple[str, MediaSummary, str, int]] = []
        for start in range(0, len(media_ids), 50):
            data = self._request(
                _RECOMMENDATION_SOURCES_QUERY, {"ids": media_ids[start : start + 50]}
            )
            for media in data["Page"]["media"]:
                because = _primary_title(media)
                for edge in (media.get("relations") or {}).get("edges", []):
                    if edge.get("relationType") == "SEQUEL":
                        rows.append(("sequel", _media_summary_of(edge["node"]), because, 0))
                for node in (media.get("recommendations") or {}).get("nodes", []):
                    suggestion = node.get("mediaRecommendation")
                    if suggestion:
                        rows.append(
                            ("similar", _media_summary_of(suggestion), because, node.get("rating") or 0)
                        )
        return rows

    def get_popular_page(self, page: int, formats: list[str]) -> tuple[list[MediaSummary], int]:
        """One page of the catalog by popularity, plus how many pages there
        are. Used to pick a random anime from a pool worth picking from --
        uniformly random across all of AniList is almost always an obscure
        short nobody asked for."""
        data = self._request(_POPULAR_PAGE_QUERY, {"page": page, "formats": formats})
        page_data = data["Page"]
        last_page = (page_data.get("pageInfo") or {}).get("lastPage") or page
        return [_media_summary_of(m) for m in page_data["media"]], last_page

    def get_media_extras(self, media_id: int) -> "MediaExtras":
        """Everything the detail page shows beside the episode list: related
        entries, what the community recommends next, and reviews."""
        media = self._request(_MEDIA_EXTRAS_QUERY, {"id": media_id})["Media"]

        relations = []
        for edge in (media.get("relations") or {}).get("edges", []):
            node = edge.get("node") or {}
            if not node.get("id"):
                continue
            relations.append(
                Relation(
                    relation_type=edge.get("relationType") or "",
                    media=_media_summary_of(node),
                    year=(node.get("startDate") or {}).get("year"),
                    status=node.get("status"),
                )
            )

        recommendations = [
            _media_summary_of(node["mediaRecommendation"])
            for node in (media.get("recommendations") or {}).get("nodes", [])
            if node.get("mediaRecommendation")
        ]

        reviews = [
            Review(
                id=node["id"],
                summary=(node.get("summary") or "").strip(),
                score=node.get("score"),
                rating=node.get("rating") or 0,
                rating_amount=node.get("ratingAmount") or 0,
                user=((node.get("user") or {}).get("name")) or "Anonymous",
            )
            for node in (media.get("reviews") or {}).get("nodes", [])
            if (node.get("summary") or "").strip()
        ]

        airing = media.get("nextAiringEpisode") or {}
        return MediaExtras(
            relations=tuple(relations),
            recommendations=tuple(recommendations),
            reviews=tuple(reviews),
            next_episode=airing.get("episode"),
            next_airing_at=airing.get("airingAt"),
            status=media.get("status") or "",
        )

    # Six rounds is plenty: each one steps one sequel/prequel further from
    # where we started, and the longest real chains (Monogatari, JoJo) are
    # well inside eight entries either side. A bound matters because this
    # walks a graph the server describes one node at a time.
    _CHAIN_ROUNDS = 6

    def get_watch_order(self, media_id: int) -> list["ChainEntry"]:
        """The franchise's entries in story order, starting from any one of
        them.

        Built by walking only PREQUEL/SEQUEL edges outwards until the chain
        closes, then following it from the end that has no prequel. Side
        stories, spin-offs and recaps are deliberately not in here -- they are
        related viewing, not a watch order, and including them is how an OVA
        ends up announced as "season 2".
        """
        nodes: dict[int, dict] = {}
        # id -> the id that comes after it. Recorded from both directions,
        # since a pair is described from each side and either may be the one
        # we happen to fetch.
        next_of: dict[int, int] = {}
        frontier = {media_id}

        for _round in range(self._CHAIN_ROUNDS):
            pending = [i for i in frontier if i not in nodes]
            if not pending:
                break
            frontier = set()
            for start in range(0, len(pending), 50):
                data = self._request(_CHAIN_QUERY, {"ids": pending[start : start + 50]})
                for media in data["Page"]["media"]:
                    nodes[media["id"]] = media
                    for edge in (media.get("relations") or {}).get("edges", []):
                        neighbour = (edge.get("node") or {}).get("id")
                        kind = edge.get("relationType")
                        if not neighbour or kind not in _STORY_RELATIONS:
                            continue
                        frontier.add(neighbour)
                        if kind == "SEQUEL":
                            next_of[media["id"]] = neighbour
                        else:
                            next_of[neighbour] = media["id"]

        if media_id not in nodes:
            return []

        # Only entries actually reachable along the chain: a batch fetch also
        # brings back neighbours-of-neighbours that were never linked in.
        has_previous = set(next_of.values())
        start_id = media_id
        seen: set[int] = set()
        while start_id in has_previous and start_id not in seen:
            seen.add(start_id)
            start_id = next(prev for prev, nxt in next_of.items() if nxt == start_id)

        chain: list[dict] = []
        current: int | None = start_id
        visited: set[int] = set()
        while current is not None and current not in visited:
            visited.add(current)
            media = nodes.get(current)
            if media is not None:
                chain.append(media)
            current = next_of.get(current)

        return [
            ChainEntry(
                id=media["id"],
                title=_primary_title(media),
                format=media.get("format"),
                episodes=media.get("episodes"),
                year=(media.get("startDate") or {}).get("year"),
                status=media.get("status"),
                cover_url=(media.get("coverImage") or {}).get("large"),
            )
            for media in _main_line(chain, media_id)
        ]

    # Writes never read from the cache and drop all of it afterwards: the
    # very next thing the UI does is re-read the list to show what changed,
    # and a five-minute-old copy of it would show the opposite.
    def save_progress(self, media_id: int, status: str, progress: int) -> None:
        self._request(
            _SAVE_MEDIA_LIST_ENTRY_MUTATION,
            {"mediaId": media_id, "status": status, "progress": progress},
            cache=False,
        )
        self.clear_cache()

    def set_list_status(self, media_id: int, status: str) -> None:
        """Puts an anime on the viewer's list with the given status, or moves
        it there. Progress is left alone -- marking something Planning must
        not reset how far into it the user already got."""
        self._request(
            _SAVE_MEDIA_LIST_ENTRY_MUTATION,
            {"mediaId": media_id, "status": status, "progress": None},
            cache=False,
        )
        self.clear_cache()

    def get_list_entry(self, media_id: int, user_id: int) -> tuple[int, str] | None:
        """(entry id, status) for this viewer's list entry, or None if the
        anime isn't on their list."""
        # Uncached: this is read immediately after a write, to find the entry
        # the write just created.
        data = self._request(
            _MEDIA_LIST_ENTRY_ID_QUERY, {"mediaId": media_id, "userId": user_id},
            cache=False,
        )
        entry = data.get("MediaList")
        if not entry:
            return None
        return entry["id"], entry.get("status") or ""

    def remove_from_list(self, media_id: int, user_id: int) -> bool:
        """Takes an anime off the viewer's list entirely. Returns whether
        there was anything to remove."""
        found = self.get_list_entry(media_id, user_id)
        if found is None:
            return False
        self._request(_DELETE_MEDIA_LIST_ENTRY_MUTATION, {"id": found[0]}, cache=False)
        self.clear_cache()
        return True


# -- Detail-page extras ----------------------------------------------------
#
# Relations, community recommendations and reviews, for the "what else is
# there" half of the detail page. One query rather than three: they are all
# fields of the same Media, and AniList rate-limits by request.

_RELATION_FIELDS = """
      id
      idMal
      title { romaji english }
      synonyms
      coverImage { large }
      bannerImage
      averageScore
      popularity
      genres
      format
      episodes
      description(asHtml: false)
      startDate { year }
      status
"""

_MEDIA_EXTRAS_QUERY = """
query ($id: Int!) {
  Media(id: $id, type: ANIME) {
    relations {
      edges {
        relationType(version: 2)
        node { %s }
      }
    }
    recommendations(perPage: 12, sort: RATING_DESC) {
      nodes {
        rating
        mediaRecommendation { %s }
      }
    }
    status
    nextAiringEpisode { episode airingAt }
    reviews(perPage: 6, sort: RATING_DESC) {
      nodes {
        id
        summary
        score
        rating
        ratingAmount
        user { name }
      }
    }
  }
}
""" % (_RELATION_FIELDS, _RELATION_FIELDS)

# Only the edges that mean "more of this story". SIDE_STORY, SPIN_OFF and the
# rest are related viewing, not the same watch order, and putting them in the
# chain is how a recap or an OVA ends up presented as "season 2".
_STORY_RELATIONS = ("PREQUEL", "SEQUEL")

# Formats that are side content whatever AniList calls the edge. An OVA or a
# special is extra viewing, not a step in the story, and AniList files plenty
# of them as PREQUEL -- "Attack on Titan: No Regrets" is an OVA that turned up
# as step 1 of Attack on Titan's watch order.
_SIDE_FORMATS = frozenset({"OVA", "SPECIAL", "MUSIC"})
# A one-or-two-episode entry in a different format from the show itself is the
# other shape this takes: One Piece's chain began with "MONSTERS: Ippaku
# Sanjou Hiryuu Jigoku", a single-episode ONA prequel to an 1100-episode TV
# series.
_SHORT_ASIDE_EPISODES = 2

_CHAIN_QUERY = """
query ($ids: [Int]) {
  Page(perPage: 50) {
    media(id_in: $ids, type: ANIME) {
      id
      title { romaji english }
      format
      episodes
      startDate { year }
      status
      coverImage { large }
      relations {
        edges {
          relationType(version: 2)
          node { id }
        }
      }
    }
  }
}
"""


@dataclass(frozen=True, slots=True)
class Relation:
    relation_type: str  # "SEQUEL", "PREQUEL", "SIDE_STORY", "SPIN_OFF", ...
    media: MediaSummary
    year: int | None
    status: str | None  # "FINISHED", "RELEASING", "NOT_YET_RELEASED", ...


@dataclass(frozen=True, slots=True)
class Review:
    id: int
    summary: str  # the author's own one-line, spoiler-free teaser
    score: int | None  # the reviewer's score out of 100
    rating: int  # how many readers found it helpful
    rating_amount: int
    user: str


@dataclass(frozen=True, slots=True)
class MediaExtras:
    relations: tuple[Relation, ...]
    recommendations: tuple[MediaSummary, ...]
    reviews: tuple[Review, ...]
    # The next broadcast, for a show still airing: (episode number, unix time
    # it airs). None for anything finished or not yet scheduled. This is the
    # Japanese broadcast -- AniList has no dub schedule, and neither does
    # anything else that could be asked cheaply, so the UI says "episode N
    # airs ..." rather than implying the dub follows it.
    next_episode: int | None = None
    next_airing_at: int | None = None
    status: str = ""


def _is_side_content(media: dict, anchor: dict) -> bool:
    """Whether a chain entry is extra viewing rather than a step in the story."""
    media_format = media.get("format")
    if media_format in _SIDE_FORMATS:
        return True
    episodes = media.get("episodes") or 0
    return (
        media_format != anchor.get("format")
        and 0 < episodes <= _SHORT_ASIDE_EPISODES
    )


def _main_line(chain: list[dict], anchor_id: int) -> list[dict]:
    """Trims side content off the ends of a franchise chain.

    Only off the *ends*, and only while it keeps finding it. An OVA prequel
    or a one-shot sits before the first real season, so dropping it is what
    makes "Attack on Titan: No Regrets" stop being step 1 of Attack on Titan.
    A film *between* two seasons is a different thing -- it is a step in the
    story that happens to be a single-episode MOVIE, so trimming inwards from
    the ends leaves it alone where a filter would have thrown it out and cut
    the chain in half.

    The entry being viewed is never dropped: opening a side story directly
    should still show it in context, not an order it isn't part of.
    """
    anchor = next((m for m in chain if m["id"] == anchor_id), None)
    if anchor is None:
        return chain

    first, last = 0, len(chain) - 1
    while first < last and chain[first]["id"] != anchor_id and _is_side_content(chain[first], anchor):
        first += 1
    while last > first and chain[last]["id"] != anchor_id and _is_side_content(chain[last], anchor):
        last -= 1
    return chain[first : last + 1]


@dataclass(frozen=True, slots=True)
class ChainEntry:
    """One entry in a franchise's watch order."""

    id: int
    title: str
    format: str | None
    episodes: int | None
    year: int | None
    status: str | None
    cover_url: str | None
