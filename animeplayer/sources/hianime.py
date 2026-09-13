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
_CARD_SUB_COUNT_RE = re.compile(r'tick-item tick-sub">.*?(\d+)</div>')
_CARD_DUB_COUNT_RE = re.compile(r'tick-item tick-dub">.*?(\d+)</div>')
_TRAILING_ID_RE = re.compile(r"-(\d+)$")

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


def search(query: str, client: httpx.Client) -> list[SearchResult]:
    """Search hianime.at for anime matching `query`."""
    resp = _get(SEARCH_URL, client, params={"keyword": query})
    page = resp.text.split(_SIDEBAR_MARKER)[0]

    results: list[SearchResult] = []
    seen: set[str] = set()
    for block in _CARD_SPLIT_RE.split(page)[1:]:
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
