"""Client for hianime.at, the public backend ani-cli currently scrapes.

Replaces the previous anidb.app client. That site went dark behind a
site-wide "Under maintenance" 503 (confirmed live: every path, including the
bare origin, returns the same 503 maintenance page), and upstream ani-cli had
already migrated off it onto hianime.at -- so this mirrors ani-cli master's
``hianime_search`` / ``hianime_episodes`` / ``hianime_m3u8`` pipeline, using
``httpx`` instead of ``curl`` + ``sed``.

The pipeline, all verified live end to end while writing this:

1. ``/search?keyword=`` -> HTML result cards (slug id, title, poster, type).
2. ``/api/theme/episode/list/{numeric_id}`` -> JSON wrapping an HTML episode
   list (``data-id`` is the episode id the next step needs).
3. ``/api/theme/episode/servers?episodeId=`` -> JSON wrapping HTML server
   buttons; each carries a base64 ``data-hash`` of its embed URL.
4. The ZokoAnime embed page ships its player config as
   ``window.__P="<base64(json XOR "otaku-embed-v1")>"`` -- see _deobfuscate.
   That config holds the master playlist, the subtitle track, and the site's
   own intro/outro timings.
5. The master playlist itself, fetched with the embed origin as ``Referer``.

Two things about this host that the anidb.app client didn't have to deal
with, both confirmed live and both load-bearing:

* The stream host **403s playlist requests without a ``Referer``** (segment
  requests are fine without one). Both the master and the per-quality
  playlists are affected, so the referer has to reach mpv too, not just the
  requests made here -- hence ``StreamInfo.referer``.
* Subtitles are **not** in the HLS manifest. Sub-mode episodes ship a
  separate WebVTT track listed in the player config, so without loading
  ``StreamInfo.subtitle_url`` as an external track, "sub" plays raw Japanese
  audio with no subtitles at all.
"""

from __future__ import annotations

import base64
import binascii
import html
import json
import re
from dataclasses import dataclass

import httpx

BASE_URL = "https://hianime.at"
SEARCH_URL = f"{BASE_URL}/search"
EPISODES_URL_TEMPLATE = f"{BASE_URL}/api/theme/episode/list/{{numeric_id}}"
SERVERS_URL = f"{BASE_URL}/api/theme/episode/servers"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Only the ZokoAnime embed uses the window.__P config this module understands.
# The other servers listed alongside it (HD-1/HD-2/Vidstream/VidPlay) are
# different players with their own unrelated obfuscation; ani-cli only
# supports ZokoAnime too.
_SERVER_NAME = "ZokoAnime"
_EMBED_XOR_KEY = b"otaku-embed-v1"

# The search page repeats the same card markup in its "top 10" sidebar, which
# would otherwise show up as duplicate results.
_SIDEBAR_MARKER = 'id="main-sidebar"'

_CARD_SPLIT_RE = re.compile(r'<div class="flw-item')
_CARD_NAME_RE = re.compile(
    r'<h3 class="film-name">\s*<a href="[^"]*?/([^"/?]+)"\s+title="([^"]*)"'
)
_CARD_POSTER_RE = re.compile(r'<img\s+src="([^"]+)"\s+class="film-poster-img"')
_CARD_KIND_RE = re.compile(r'<span class="fdi-item">([^<]*)</span>')
_CARD_DURATION_RE = re.compile(r'<span class="fdi-item fdi-duration">([^<]*)</span>')
# The trailing \s* matters: the poster cards close these straight after the
# number, but the spotlight hero renders the same markup with a space before
# </div>, so a pattern tuned to the cards silently read every hero as sub=0.
_CARD_SUB_COUNT_RE = re.compile(r'tick-item tick-sub">.*?(\d+)\s*</div>')
_CARD_DUB_COUNT_RE = re.compile(r'tick-item tick-dub">.*?(\d+)\s*</div>')
_TRAILING_ID_RE = re.compile(r"-(\d+)$")

# hianime's search does not tokenise punctuation: searching its *own* title
# for a show returns nothing when that title contains any. Confirmed live --
# "Re:ZERO -Starting Life in Another World- Season 3" is the exact title of
# an entry on the site and finds zero results, while the same words with the
# colon and dashes replaced by spaces finds it as the only hit.
_QUERY_PUNCT_RE = re.compile(r"[^\w\s]+")
_QUERY_WS_RE = re.compile(r"\s+")

_EPISODE_RE = re.compile(r'<a\s[^>]*?data-number="([^"]*)"[^>]*?data-id="(\d+)"', re.S)
_EPISODE_TITLE_RE = re.compile(r'title="([^"]*)"')
_EPISODE_SLUG_RE = re.compile(r'/watch/([^"?]+)\?ep=')

_SERVER_ITEM_RE = re.compile(r'<div class="item server-item"([^>]*)>')
_SERVER_ATTR_RE = re.compile(r'data-(type|server-name|hash)="([^"]*)"')

_EMBED_BLOB_RE = re.compile(r'window\.__P\s*=\s*"([^"]*)"')
_MAL_ID_RE = re.compile(r"/mal/(\d+)/")

_VARIANT_RE = re.compile(r"#EXT-X-STREAM-INF:([^\n]*)\n(\S+)")
_BANDWIDTH_RE = re.compile(r"BANDWIDTH=(\d+)")
_RESOLUTION_RE = re.compile(r"RESOLUTION=(\d+)x(\d+)")
_CLOUDFLARE_MARKERS = ("Just a moment", "Checking your browser")
_MAINTENANCE_MARKERS = ("Under maintenance", "Under Maintenance")


class SourceError(Exception):
    """Base error for streaming-source failures."""


class SourceUnavailableError(SourceError):
    """The site answered, but with a maintenance/outage page rather than content.

    Split out from a bare HTTP error because it is the exact failure that
    killed the previous backend, and it needs to read as "the site is down,
    not your network" in the UI rather than as a raw status line.
    """


class CloudflareBlockedError(SourceError):
    """A response looks like a Cloudflare interstitial rather than real content."""


class NoStreamFoundError(SourceError):
    """An episode has no playable source for the requested language."""


@dataclass(frozen=True, slots=True)
class SearchResult:
    slug_id: str  # e.g. "dorohedoro-2691" -- pass to get_episodes()
    numeric_id: str  # e.g. "2691"
    title: str
    poster_url: str
    kind: str  # e.g. "TV", "Movie", "OVA", "ONA", "SPECIAL"
    rating: str  # always "" here; hianime cards carry no score (AniList fills it in on DetailPage)
    duration: str  # e.g. "23m"
    sub_count: int  # subbed episodes available; 0 if the card doesn't say
    dub_count: int  # dubbed episodes available; 0 means sub-only


@dataclass(frozen=True, slots=True)
class Episode:
    episode_id: int  # backend id, needed to resolve stream sources
    number: float  # some entries are fractional (e.g. specials numbered x.5)
    filler: bool  # always False here -- hianime marks no filler, Jikan fills this in (see sources/jikan.py)
    title: str  # e.g. "Night of the Hunter"; often just "Episode N"


@dataclass(frozen=True, slots=True)
class StreamVariant:
    resolution: str  # e.g. "1080p"
    url: str
    bandwidth: int


@dataclass(frozen=True, slots=True)
class StreamInfo:
    master_url: str  # adaptive playlist -- mpv picks/switches quality itself
    referer: str  # the stream host 403s playlist requests without this
    variants: tuple[StreamVariant, ...] = ()  # sorted best (highest bandwidth) first
    subtitle_url: str | None = None  # external WebVTT; subs are not in the manifest
    mal_id: int | None = None  # from the embed URL -- feeds ani-skip and the Jikan filler lookup
    skip_intro: tuple[float, float] | None = None  # (start, end) seconds, from the site's own data
    skip_outro: tuple[float, float] | None = None


def _check_usable(text: str) -> None:
    if any(marker in text for marker in _CLOUDFLARE_MARKERS):
        raise CloudflareBlockedError(
            "hianime.at returned a Cloudflare check instead of content. "
            "This usually clears up on its own after a short wait."
        )
    if any(marker in text for marker in _MAINTENANCE_MARKERS):
        raise SourceUnavailableError("hianime.at is down for maintenance right now.")


def _get(url: str, client: httpx.Client, **kwargs) -> httpx.Response:
    headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
    resp = client.get(url, headers=headers, **kwargs)
    if resp.status_code == 503:
        _check_usable(resp.text)  # a maintenance page is the likely cause; report it as such
        raise SourceUnavailableError("hianime.at is temporarily unavailable (503).")
    resp.raise_for_status()
    _check_usable(resp.text)
    return resp


def _flatten(markup: str) -> str:
    return re.sub(r"\s+", " ", markup)


def _first(pattern: re.Pattern[str], text: str, default: str = "") -> str:
    match = pattern.search(text)
    return match.group(1).strip() if match else default


def _search_keyword(query: str) -> str:
    return _QUERY_WS_RE.sub(" ", _QUERY_PUNCT_RE.sub(" ", query)).strip()


def _parse_cards(markup: str) -> list[SearchResult]:
    """Parses the site's standard poster-card grid (``flw-item``).

    The same markup backs search results, every catalog page (most-popular,
    top-airing, ...) and the filter endpoint, so all of them come through
    here rather than each growing its own copy of these regexes.
    """
    results: list[SearchResult] = []
    seen: set[str] = set()
    for block in _CARD_SPLIT_RE.split(markup)[1:]:
        flat = _flatten(block)
        name_match = _CARD_NAME_RE.search(flat)
        if not name_match:
            continue
        slug_id, title = name_match.groups()
        id_match = _TRAILING_ID_RE.search(slug_id)
        if not id_match or slug_id in seen:
            continue
        seen.add(slug_id)
        results.append(
            SearchResult(
                slug_id=slug_id,
                numeric_id=id_match.group(1),
                title=html.unescape(title),
                poster_url=_first(_CARD_POSTER_RE, flat),
                kind=_first(_CARD_KIND_RE, flat),
                rating="",
                duration=_first(_CARD_DURATION_RE, flat),
                sub_count=int(_first(_CARD_SUB_COUNT_RE, flat, "0")),
                dub_count=int(_first(_CARD_DUB_COUNT_RE, flat, "0")),
            )
        )
    return results


def search(query: str, client: httpx.Client) -> list[SearchResult]:
    """Search hianime.at for anime matching `query`."""
    resp = _get(SEARCH_URL, client, params={"keyword": _search_keyword(query)})
    return _parse_cards(resp.text.split(_SIDEBAR_MARKER)[0])


# -- Catalog browsing ------------------------------------------------------
#
# The site publishes the same rankings its own home page is built from as
# plain paginated pages of the standard card grid, so "Top Airing" and
# friends need no API and no AniList round trip -- one GET and _parse_cards.
# Every path below was confirmed live to return a full grid; the ones that
# look like they should exist but don't (/completed, /recently-added,
# /genre/<x>) are deliberately absent -- this site spells them
# /latest-completed, /new-anime and /genres/<x>.

# Ordered: this is also the order the home page stacks its rows in.
CATALOGS: dict[str, str] = {
    "top-airing": "Top Airing",
    "most-popular": "Most Popular",
    "most-favorite": "Most Favorite",
    "latest-completed": "Latest Completed",
    "recently-updated": "Latest Episodes",
    "new-anime": "New on HiAnime",
    "top-upcoming": "Top Upcoming",
    "subbed-anime": "Recently Subbed",
    "dubbed-anime": "Recently Dubbed",
    "movie": "Movies",
    "tv": "TV Series",
    "ova": "OVAs",
    "ona": "ONAs",
    "special": "Specials",
}

FILTER_URL = f"{BASE_URL}/filter"
GENRE_PATH_PREFIX = "genres/"

# The filter form's own option lists, as (value, label) pairs, lifted from
# /filter. Hardcoded rather than scraped on every launch: they are a fixed
# part of the site's UI, and a filter bar that can't draw itself until a
# network round trip lands is worse than one that is occasionally a value
# out of date. get_genres() *is* fetched, since that list is long and does
# grow.
FILTER_TYPES = (("tv", "TV"), ("movie", "Movie"), ("ova", "OVA"),
                ("ona", "ONA"), ("special", "Special"), ("music", "Music"))
FILTER_STATUSES = (("completed", "Finished"), ("releasing", "Airing"),
                   ("not_yet_aired", "Upcoming"))
FILTER_SEASONS = (("spring", "Spring"), ("summer", "Summer"),
                  ("fall", "Fall"), ("winter", "Winter"))
FILTER_LANGUAGES = (("sub", "Sub"), ("dub", "Dub"))
FILTER_SORTS = (("", "Default"), ("most_viewed", "Most Watched"),
                ("most_followed", "Most Followed"), ("trending", "Trending"),
                ("avg_score", "Score"), ("release_date", "Newest"),
                ("updated_date", "Recently Updated"), ("added_date", "Recently Added"),
                ("title_az", "Name A-Z"))

_SPOTLIGHT_SPLIT_RE = re.compile(r'<div class="deslide-item">')
_SPOTLIGHT_RANK_RE = re.compile(r'<div class="desi-sub-text">\s*#(\d+)')
_SPOTLIGHT_TITLE_RE = re.compile(r'desi-head-title[^>]*data-jname="([^"]*)"[^>]*>\s*([^<]+)')
_SPOTLIGHT_BANNER_RE = re.compile(r'<img class="film-poster-img"\s+src="([^"]+)"')
_SPOTLIGHT_DESC_RE = re.compile(r'<div class="desi-description">\s*(.*?)\s*</div>')
_SPOTLIGHT_DETAIL_RE = re.compile(r'href="[^"]*?/([^"/?]+)"\s+class="btn btn-secondary')
_SCD_ITEM_RE = re.compile(r'<div class="scd-item[^"]*">\s*(?:<i[^>]*></i>)?\s*([^<]*?)\s*<')

_TRENDING_ITEM_RE = re.compile(
    r'<div class="number">\s*<span>(\d+)</span>.*?data-jname="([^"]*)">([^<]*)<.*?'
    r'href="[^"]*?/([^"/?]+)" class="film-poster".*?<img src="([^"]+)"',
    re.S,
)

# "Next" rather than counting page numbers: the paginator only ever renders a
# window of three around the current page, so the page-number links say
# nothing about whether more exist.
_NEXT_PAGE_MARKER = 'title="Next"'

_GENRE_ITEM_RE = re.compile(r'f-genre-item" data-id="([^"]+)">([^<]+)<')
# The genre half of a catalog path is the only part not drawn from a fixed
# list, and it is pasted straight into a URL -- so it is checked against the
# shape a genre slug actually has rather than merely for its prefix.
_GENRE_SLUG_RE = re.compile(r"[a-z0-9-]+$")


def _is_catalog_path(category: str) -> bool:
    if category in CATALOGS:
        return True
    prefix, _, slug = category.partition("/")
    return prefix + "/" == GENRE_PATH_PREFIX and _GENRE_SLUG_RE.fullmatch(slug) is not None


@dataclass(frozen=True, slots=True)
class Spotlight:
    """A featured entry from the home page's hero carousel.

    Distinct from SearchResult because the hero is the one place the site
    hands over a wide banner image and a synopsis -- a poster card carries
    neither, and a hero built from a 2:3 poster looks like a mistake.
    """

    slug_id: str
    numeric_id: str
    title: str
    japanese_title: str
    banner_url: str
    description: str
    kind: str  # "TV", "Movie", ...
    duration: str  # e.g. "24m"
    released: str  # e.g. "Apr 7, 2013"
    sub_count: int
    dub_count: int
    rank: int  # its position in the carousel, as the site numbers it


@dataclass(frozen=True, slots=True)
class CatalogPage:
    results: tuple[SearchResult, ...]
    page: int
    has_more: bool


def _catalog_page(url: str, page: int, client: httpx.Client, **kwargs) -> CatalogPage:
    # A list of pairs rather than a dict: the filter endpoint takes genre[]
    # once per selected genre, which a mapping cannot express.
    params = [*kwargs.pop("params", ()), ("page", str(page))]
    resp = _get(url, client, params=params, **kwargs)
    # Split off the sidebar first: it carries its own "Top 10" card grid,
    # which would otherwise land in the results as ten phantom entries.
    body = resp.text.split(_SIDEBAR_MARKER)[0]
    return CatalogPage(
        results=tuple(_parse_cards(body)),
        page=page,
        has_more=_NEXT_PAGE_MARKER in resp.text,
    )


def browse(category: str, page: int, client: httpx.Client) -> CatalogPage:
    """One page of a named catalog (a CATALOGS key, or "genres/<slug>")."""
    if not _is_catalog_path(category):
        raise SourceError(f"Unknown catalog: {category}")
    return _catalog_page(f"{BASE_URL}/{category}", page, client)


def filter_browse(
    client: httpx.Client,
    page: int = 1,
    keyword: str = "",
    type_: str = "",
    status: str = "",
    season: str = "",
    language: str = "",
    sort: str = "",
    genres: tuple[str, ...] = (),
) -> CatalogPage:
    """The site's own /filter endpoint.

    Preferred over filtering AniList for anything the user is about to
    *watch*: every result here is by definition present on the source, so a
    click can't land on "couldn't find a stream". AniList-side filtering
    stays for tags and for the user's own list status, neither of which this
    endpoint knows anything about.
    """
    params: list[tuple[str, str]] = [
        (name, value)
        for name, value in (
            ("keyword", _search_keyword(keyword) if keyword else ""),
            ("type", type_),
            ("status", status),
            ("season", season),
            ("language", language),
            ("sort", sort),
        )
        if value
    ]
    params.extend(("genre[]", g) for g in genres)
    return _catalog_page(FILTER_URL, page, client, params=params)


def get_genres(client: httpx.Client) -> list[tuple[str, str]]:
    """Every genre the filter form offers, as (slug, label)."""
    resp = _get(FILTER_URL, client)
    seen: set[str] = set()
    genres: list[tuple[str, str]] = []
    for slug, label in _GENRE_ITEM_RE.findall(_flatten(resp.text)):
        if slug in seen:
            continue
        seen.add(slug)
        genres.append((slug, html.unescape(label).strip()))
    return genres


def _parse_spotlight(markup: str) -> list[Spotlight]:
    items: list[Spotlight] = []
    for index, block in enumerate(_SPOTLIGHT_SPLIT_RE.split(markup)[1:], start=1):
        flat = _flatten(block)
        title_match = _SPOTLIGHT_TITLE_RE.search(flat)
        detail_match = _SPOTLIGHT_DETAIL_RE.search(flat)
        if not title_match or not detail_match:
            continue
        slug_id = detail_match.group(1)
        id_match = _TRAILING_ID_RE.search(slug_id)
        if not id_match:
            continue
        # The detail strip is positional: format, then runtime, then air date.
        # Reading it by position rather than by pattern because each item is
        # the same anonymous <div class="scd-item">, and an entry missing one
        # (upcoming shows have no runtime) simply has a shorter strip.
        details = [d for d in _SCD_ITEM_RE.findall(flat) if d]
        rank_match = _SPOTLIGHT_RANK_RE.search(flat)
        items.append(
            Spotlight(
                slug_id=slug_id,
                numeric_id=id_match.group(1),
                title=html.unescape(title_match.group(2)).strip(),
                japanese_title=html.unescape(title_match.group(1)).strip(),
                banner_url=_first(_SPOTLIGHT_BANNER_RE, flat),
                description=html.unescape(_first(_SPOTLIGHT_DESC_RE, flat)),
                kind=details[0] if details else "",
                duration=details[1] if len(details) > 1 else "",
                released=details[2] if len(details) > 2 else "",
                sub_count=int(_first(_CARD_SUB_COUNT_RE, flat, "0")),
                dub_count=int(_first(_CARD_DUB_COUNT_RE, flat, "0")),
                rank=int(rank_match.group(1)) if rank_match else index,
            )
        )
    return items


def _parse_trending(markup: str) -> list[SearchResult]:
    # Trending is a different, sparser card than the rest of the site: rank,
    # title and poster, with no format/runtime/sub-dub strip at all. The
    # missing fields are left empty rather than guessed, and the rank is
    # dropped because it is just the position -- the row renders it from the
    # index rather than carrying a number that could disagree with it.
    results: list[SearchResult] = []
    for _rank, _jname, title, slug_id, poster in _TRENDING_ITEM_RE.findall(markup):
        id_match = _TRAILING_ID_RE.search(slug_id)
        if not id_match:
            continue
        results.append(
            SearchResult(
                slug_id=slug_id,
                numeric_id=id_match.group(1),
                title=html.unescape(title).strip(),
                poster_url=poster,
                kind="",
                rating="",
                duration="",
                sub_count=0,
                dub_count=0,
            )
        )
    return results


def get_home_highlights(client: httpx.Client) -> tuple[list[Spotlight], list[SearchResult]]:
    """The home page's hero carousel and its Trending row, from one request.

    These two are the only parts of the home page that exist nowhere else on
    the site; every other row it shows has its own catalog page (see
    CATALOGS), which paginates and so makes a better "see all".
    """
    resp = _get(f"{BASE_URL}/home", client)
    body = resp.text.split(_SIDEBAR_MARKER)[0]
    return _parse_spotlight(body), _parse_trending(body)


def get_episodes(slug_id: str, client: httpx.Client) -> list[Episode]:
    """List episodes for an anime, given its full slug (e.g. "dorohedoro-2691").

    Takes the whole slug rather than just the numeric part because the id
    alone is not enough to tell whether the answer is the right show. The
    endpoint keys off the number and happily answers for *any* number it
    knows, so an id left over from a different backend doesn't fail -- it
    returns some unrelated anime's episodes (confirmed live: the previous
    backend's "one-piece-3880" returns High School DxD Hero's 12 episodes
    here). Every episode link carries the slug it belongs to, so they're
    checked against the slug asked for and a mismatch returns nothing, which
    the caller treats as "re-resolve this by title". ani-cli guards the same
    way, for the same reason.
    """
    numeric_id = slug_id.rsplit("-", 1)[-1]
    resp = _get(EPISODES_URL_TEMPLATE.format(numeric_id=numeric_id), client)
    # The JSON wraps a blob of HTML, escaped for embedding in JS.
    markup = resp.json().get("html", "").replace("\\/", "/").replace('\\"', '"')

    episodes: list[Episode] = []
    for raw_tag in re.split(r"<a\s", markup)[1:]:
        tag = _flatten("<a " + raw_tag.split(">")[0] + ">")
        match = _EPISODE_RE.search(tag)
        if not match:
            continue
        link_slug = _EPISODE_SLUG_RE.search(tag)
        if link_slug is not None and link_slug.group(1) != slug_id:
            return []  # this id belongs to a different anime -- see the docstring
        number_text, episode_id = match.groups()
        try:
            number = float(number_text)
        except ValueError:
            continue
        episodes.append(
            Episode(
                episode_id=int(episode_id),
                number=number,
                filler=False,
                title=html.unescape(_first(_EPISODE_TITLE_RE, tag)),
            )
        )
    return episodes


def _deobfuscate(blob: str) -> dict:
    """The embed page ships its player config as base64(json XOR key)."""
    try:
        raw = base64.b64decode(blob)
    except (binascii.Error, ValueError) as exc:
        raise NoStreamFoundError("The embed page's player config was unreadable") from exc
    decoded = bytes(byte ^ _EMBED_XOR_KEY[i % len(_EMBED_XOR_KEY)] for i, byte in enumerate(raw))
    try:
        return json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NoStreamFoundError("The embed page's player config was unreadable") from exc


def _parse_servers(markup: str, dub: bool) -> str:
    """Returns the ZokoAnime embed URL for the requested audio track."""
    wanted_type = "dub" if dub else "sub"
    available: set[str] = set()
    for attrs in _SERVER_ITEM_RE.findall(_flatten(markup.replace('\\"', '"'))):
        fields = dict(_SERVER_ATTR_RE.findall(attrs))
        available.add(fields.get("type", ""))
        if fields.get("type") != wanted_type or fields.get("server-name") != _SERVER_NAME:
            continue
        try:
            return base64.b64decode(fields.get("hash", "")).decode()
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
    if wanted_type not in available:
        track = "dubbed" if dub else "subbed"
        raise NoStreamFoundError(f"No {track} version of this episode is available")
    raise NoStreamFoundError("No supported streaming server for this episode")


def _skip_range(skip: dict, key: str) -> tuple[float, float] | None:
    entry = skip.get(key) if isinstance(skip, dict) else None
    if not isinstance(entry, dict):
        return None
    start, end = entry.get("start"), entry.get("end")
    if start is None or end is None or float(end) <= float(start):
        return None
    return (float(start), float(end))


def resolve_source(episode_id: int, client: httpx.Client, dub: bool = False) -> StreamInfo:
    """Resolve an episode id to its master playlist and everything that comes
    with it (referer, subtitle track, MAL id, intro/outro timings).

    This is the fast path (2 requests: servers, then the embed page) -- kept
    separate from get_stream_variants() so playback can start as soon as
    possible instead of waiting on a 3rd request just to build the quality list.
    """
    resp = _get(SERVERS_URL, client, params={"episodeId": episode_id})
    embed_url = _parse_servers(resp.json().get("html", ""), dub=dub)

    embed_resp = _get(embed_url, client)
    blob = _EMBED_BLOB_RE.search(embed_resp.text)
    if blob is None:
        raise NoStreamFoundError("No playable source found for this episode")
    config = _deobfuscate(blob.group(1))

    master_url = config.get("src")
    if not master_url:
        raise NoStreamFoundError("No playable source found for this episode")

    subtitles = config.get("subtitles") or []
    default_sub = next(
        (s for s in subtitles if s.get("default")),
        subtitles[0] if subtitles else None,
    )
    mal_match = _MAL_ID_RE.search(embed_url)
    skip = config.get("skip") or {}

    return StreamInfo(
        master_url=master_url,
        # The stream host wants the embed *site*, not the full embed path.
        referer=re.sub(r"^(https?://[^/]+).*", r"\1/", embed_url),
        subtitle_url=(default_sub or {}).get("src") or None,
        mal_id=int(mal_match.group(1)) if mal_match else None,
        skip_intro=_skip_range(skip, "intro"),
        skip_outro=_skip_range(skip, "outro"),
    )


def _parse_variants(master_playlist_text: str, master_url: str) -> tuple[StreamVariant, ...]:
    base = master_url.rsplit("/", 1)[0]
    variants = []
    for attrs, url in _VARIANT_RE.findall(master_playlist_text):
        if "I-FRAME" in attrs:
            continue
        bandwidth_match = _BANDWIDTH_RE.search(attrs)
        resolution_match = _RESOLUTION_RE.search(attrs)
        bandwidth = int(bandwidth_match.group(1)) if bandwidth_match else 0
        height = int(resolution_match.group(2)) if resolution_match else 0
        variants.append(
            StreamVariant(
                resolution=f"{height}p" if height else "auto",
                # Variant playlists are listed relative to the master.
                url=url if url.startswith("http") else f"{base}/{url}",
                bandwidth=bandwidth,
            )
        )
    variants.sort(key=lambda v: v.bandwidth, reverse=True)
    return tuple(variants)


def get_stream_variants(
    master_url: str, client: httpx.Client, referer: str = ""
) -> tuple[StreamVariant, ...]:
    """Fetches and parses the per-quality variants out of a master HLS playlist."""
    headers = {"Referer": referer} if referer else {}
    master_resp = _get(master_url, client, headers=headers)
    return _parse_variants(master_resp.text, master_url)


def resolve_stream(episode_id: int, client: httpx.Client, dub: bool = False) -> StreamInfo:
    """resolve_source plus the per-quality variant list (one extra round trip)."""
    info = resolve_source(episode_id, client, dub=dub)
    variants = get_stream_variants(info.master_url, client, referer=info.referer)
    return StreamInfo(
        master_url=info.master_url,
        referer=info.referer,
        variants=variants,
        subtitle_url=info.subtitle_url,
        mal_id=info.mal_id,
        skip_intro=info.skip_intro,
        skip_outro=info.skip_outro,
    )
