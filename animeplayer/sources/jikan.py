"""Fallback source for episode filler flags, via Jikan (the unofficial
MyAnimeList API, https://jikan.moe).

The streaming source's own episode data doesn't carry filler flags for every
show -- confirmed live: it has zero filler episodes marked for One Piece
(1176 episodes, genuinely none flagged) despite Naruto Shippuden being
correctly and extensively flagged (167 episodes). Used only as a fallback
when the source reports no filler at all for a show and we know its MAL id
(from AniList's idMal field).
"""

from __future__ import annotations

import time

import httpx

BASE_URL = "https://api.jikan.moe/v4"
_MAX_PAGES = 15  # One Piece is ~12 pages at ~100 episodes/page; a hard cap in case pagination ever misbehaves

# Jikan allows 3 requests a second. Pages fetched back to back hit that on
# the fourth -- measured: pages 1-3 answered 200 and 4-12 all 429 -- and one
# failed page used to throw the whole list away, which is why One Piece (12
# pages) never showed any filler while short shows did.
_SECONDS_BETWEEN_PAGES = 0.4
_RETRIES = 3


def _get_page(client: httpx.Client, mal_id: int, page: int, sleep) -> dict:
    for attempt in range(_RETRIES + 1):
        resp = client.get(f"{BASE_URL}/anime/{mal_id}/episodes", params={"page": page})
        if resp.status_code == 429 and attempt < _RETRIES:
            sleep(1.0 + attempt)
            continue
        resp.raise_for_status()
        return resp.json()
    return {}


def get_filler_episodes(mal_id: int, client: httpx.Client, sleep=time.sleep) -> set[int]:
    """Returns the set of episode numbers Jikan flags as filler for this show."""
    filler_numbers: set[int] = set()
    page = 1
    while page <= _MAX_PAGES:
        if page > 1:
            sleep(_SECONDS_BETWEEN_PAGES)
        data = _get_page(client, mal_id, page, sleep)
        for ep in data.get("data", []):
            if ep.get("filler"):
                filler_numbers.add(ep["mal_id"])  # Jikan's per-episode "mal_id" is really the episode number
        if not data.get("pagination", {}).get("has_next_page"):
            break
        page += 1
    return filler_numbers
