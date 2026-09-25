"""Relaying the PC's current episode to the phone, for "continue on phone".

A phone browser can't play the stream straight from the video host: the host
wants a Referer the browser won't send (see sources/hianime.py), and a page
served from the PC isn't allowed to fetch another site's playlist anyway. So
the PC fetches on the phone's behalf. The playlist is rewritten so every URL
in it points back at the PC's own /stream routes, and each segment is fetched
with the right headers and passed straight through.

Only hosts the current episode actually uses are relayed -- the server is
reachable by anything on the LAN with a pairing token, and must not become a
general-purpose proxy.
"""

from __future__ import annotations

import re
from urllib.parse import quote, urljoin, urlsplit

# URI="..." inside tags such as #EXT-X-KEY and #EXT-X-MEDIA.
_TAG_URI_RE = re.compile(r'URI="([^"]+)"')


def rewrite_playlist(text: str, playlist_url: str, token: str, hosts: set[str]) -> str:
    """Points every URL in an HLS playlist at the relay. Nested playlists
    (a master's variants) go to /stream/pl so they are rewritten in turn;
    everything else -- segments, keys -- goes to /stream/seg.

    Every host the playlist points at is added to `hosts`: segments are
    often served from a different CDN host than the playlist listing them,
    and those are exactly the hosts the relay may then fetch from."""
    is_master = "#EXT-X-STREAM-INF" in text

    def relay(url: str, nested: bool) -> str:
        absolute = urljoin(playlist_url, url.strip())
        hosts.add(host_of(absolute))
        route = "pl" if nested else "seg"
        return f"/stream/{route}?t={quote(token)}&u={quote(absolute, safe='')}"

    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            out.append(line)
        elif stripped.startswith("#"):
            # Audio/subtitle renditions in a master are playlists too.
            nested = stripped.startswith("#EXT-X-MEDIA")
            out.append(_TAG_URI_RE.sub(lambda m: f'URI="{relay(m.group(1), nested)}"', line))
        else:
            out.append(relay(stripped, is_master))
    return "\n".join(out) + "\n"


def host_of(url: str) -> str:
    return urlsplit(url).hostname or ""


def allowed(url: str, hosts: set[str]) -> bool:
    """Whether the relay may fetch this URL: http(s), on a host the current
    episode's own playlist is served from."""
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and (parts.hostname or "") in hosts
