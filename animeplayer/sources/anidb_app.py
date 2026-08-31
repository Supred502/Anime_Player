"""Client for anidb.app, the public backend ani-cli currently scrapes.

Verified live against ani-cli v5.0.3 (``master``) during development: this
mirrors that script's ``anidb_search`` / ``anidb_episodes`` / ``anidb_m3u8``
pipeline, using ``httpx`` instead of ``curl`` + ``sed``. Search uses ani-cli's
own ``/browse`` endpoint (not the lighter ``/search/suggestions`` typeahead
endpoint, which appears to be capped around 8 results regardless of match
count) -- ani-cli itself relies on ``/browse`` in real-world use, which is
better evidence it tolerates normal request patterns than any test done here.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

import httpx

BASE_URL = "https://anidb.app"
SEARCH_URL = f"{BASE_URL}/browse"
EPISODES_URL_TEMPLATE = f"{BASE_URL}/api/frontend/anime/{{numeric_id}}/episodes"
LANGUAGES_URL_TEMPLATE = f"{BASE_URL}/api/frontend/episode/{{episode_id}}/languages"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Outer group = full slug ("hunter-x-hunter-2293"), inner group = trailing numeric id.
_SEARCH_ITEM_RE = re.compile(
    r'href="https://anidb\.app/anime/([a-z0-9-]+-(\d+))" class="anime-card[^"]*" title="([^"]+)"'
    r'.*?<img[^>]*src="([^"]+)"'
    r'.*?badge-orange[^>]*>(\w+)</span>'
    r'.*?badge-gray.*?</svg>\s*([\d.]+)\s*</span>',
    re.S,
)
_M3U8_MASTER_RE = re.compile(r"file:\s*'([^']+)'")
_VARIANT_RE = re.compile(r"#EXT-X-STREAM-INF:([^\n]*)\n(\S+)")
_BANDWIDTH_RE = re.compile(r"BANDWIDTH=(\d+)")
_RESOLUTION_RE = re.compile(r"RESOLUTION=(\d+)x(\d+)")
_CLOUDFLARE_MARKERS = ("Just a moment", "Checking your browser")


class AniDBError(Exception):
    """Base error for anidb.app client failures."""


class CloudflareBlockedError(AniDBError):
    """A response looks like a Cloudflare interstitial rather than real content.

    Confirmed to happen in practice (not just a theoretical risk) when this
    site is hit with a rapid burst of requests in a short window -- a normal
    human's occasional in-app searches are unlikely to trigger it, but it's
    real. TLS-impersonation (e.g. curl_cffi) would be one path forward if it
    starts happening under normal use; for now this just fails loudly instead
    of silently returning empty results.
    """


class NoStreamFoundError(AniDBError):
    """An episode has no playable source for the requested language."""


@dataclass(frozen=True, slots=True)
class SearchResult:
    slug_id: str  # e.g. "hunter-x-hunter-2293" -- pass to get_episodes()
    numeric_id: str  # e.g. "2293"
    title: str
    poster_url: str
    kind: str  # e.g. "TV", "Movie", "OVA", "Special"
    rating: str  # e.g. "8.0"


@dataclass(frozen=True, slots=True)
class Episode:
    episode_id: int  # backend id, needed to resolve stream sources
    number: float  # some entries are fractional (e.g. specials numbered x.5)
    filler: bool


@dataclass(frozen=True, slots=True)
class StreamVariant:
    resolution: str  # e.g. "1080p"
    url: str
    bandwidth: int


@dataclass(frozen=True, slots=True)
class StreamInfo:
    master_url: str  # adaptive playlist -- mpv picks/switches quality itself
    variants: tuple[StreamVariant, ...]  # sorted best (highest bandwidth) first


def _check_not_cloudflare(text: str) -> None:
    if any(marker in text for marker in _CLOUDFLARE_MARKERS):
        raise CloudflareBlockedError(
            "anidb.app returned a Cloudflare interstitial instead of content. "
            "This usually clears up on its own after a short wait."
        )


def search(query: str, client: httpx.Client) -> list[SearchResult]:
    """Search anidb.app for anime matching `query`."""
    resp = client.get(SEARCH_URL, params={"q": query}, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    _check_not_cloudflare(resp.text)

    flat_text = re.sub(r"\s+", " ", resp.text)
    results: list[SearchResult] = []
    for block in flat_text.split("<a href=")[1:]:
        match = _SEARCH_ITEM_RE.search("<a href=" + block)
        if not match:
            continue
        slug_id, numeric_id, title, poster_url, kind, rating = match.groups()
        results.append(
            SearchResult(
                slug_id=slug_id,
                numeric_id=numeric_id,
                title=html.unescape(title),
                poster_url=poster_url,
                kind=kind,
                rating=rating,
            )
        )
    return results


def get_episodes(numeric_id: str, client: httpx.Client) -> list[Episode]:
    """List episodes for an anime, given its numeric id (the slug's trailing number)."""
    resp = client.get(
        EPISODES_URL_TEMPLATE.format(numeric_id=numeric_id), headers={"User-Agent": USER_AGENT}
    )
    resp.raise_for_status()
    _check_not_cloudflare(resp.text)

    data = resp.json()
    return [
        Episode(episode_id=ep["id"], number=ep["number"], filler=ep.get("filler", False))
        for ep in data.get("episodes", [])
    ]


def _parse_variants(master_playlist_text: str) -> tuple[StreamVariant, ...]:
    variants = []
    for attrs, url in _VARIANT_RE.findall(master_playlist_text):
        bandwidth_match = _BANDWIDTH_RE.search(attrs)
        resolution_match = _RESOLUTION_RE.search(attrs)
        bandwidth = int(bandwidth_match.group(1)) if bandwidth_match else 0
        height = int(resolution_match.group(2)) if resolution_match else 0
        variants.append(
            StreamVariant(resolution=f"{height}p" if height else "auto", url=url, bandwidth=bandwidth)
        )
    variants.sort(key=lambda v: v.bandwidth, reverse=True)
    return tuple(variants)


def resolve_master_url(episode_id: int, client: httpx.Client, dub: bool = False) -> str:
    """Resolve an episode id to its master HLS playlist URL.

    This is the fast path (2 requests: languages, then the embed page) --
    kept separate from get_stream_variants() so playback can start as soon as
    possible instead of waiting on a 3rd request just to build the quality list.
    """
    lang_code = "eng" if dub else "jpn"
    resp = client.get(
        LANGUAGES_URL_TEMPLATE.format(episode_id=episode_id), headers={"User-Agent": USER_AGENT}
    )
    resp.raise_for_status()
    _check_not_cloudflare(resp.text)

    languages = resp.json().get("languages", [])
    embed_url = next((lang["embed_url"] for lang in languages if lang.get("code") == lang_code), None)
    if embed_url is None:
        track = "dub" if dub else "sub"
        raise NoStreamFoundError(f"No {track} audio available for this episode yet")

    embed_resp = client.get(embed_url, headers={"User-Agent": USER_AGENT})
    embed_resp.raise_for_status()
    _check_not_cloudflare(embed_resp.text)

    master_match = _M3U8_MASTER_RE.search(embed_resp.text)
    if master_match is None:
        raise NoStreamFoundError("No playable source found for this episode")
    return master_match.group(1)


def get_stream_variants(master_url: str, client: httpx.Client) -> tuple[StreamVariant, ...]:
    """Fetches and parses the per-quality variants out of a master HLS playlist."""
    master_resp = client.get(master_url, headers={"User-Agent": USER_AGENT})
    master_resp.raise_for_status()
    return _parse_variants(master_resp.text)


def resolve_stream(episode_id: int, client: httpx.Client, dub: bool = False) -> StreamInfo:
    """Resolve an episode id to its master HLS playlist plus per-quality variants.

    Convenience wrapper over resolve_master_url + get_stream_variants for
    callers that want both and don't care about the extra round trip (e.g. tests).
    """
    master_url = resolve_master_url(episode_id, client, dub=dub)
    variants = get_stream_variants(master_url, client)
    return StreamInfo(master_url=master_url, variants=variants)
