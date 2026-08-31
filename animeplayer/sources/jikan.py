"""Fallback source for episode filler flags, via Jikan (the unofficial
MyAnimeList API, https://jikan.moe).

anidb.app's own episode data doesn't reliably carry filler flags for every
show -- confirmed live: it has zero filler episodes marked for One Piece
(1176 episodes, genuinely none flagged) despite Naruto Shippuden being
correctly and extensively flagged (167 episodes). Used only as a fallback
when anidb.app reports no filler at all for a show and we know its MAL id
(from AniList's idMal field).
"""

from __future__ import annotations

import httpx

BASE_URL = "https://api.jikan.moe/v4"
_MAX_PAGES = 15  # One Piece is ~12 pages at ~100 episodes/page; a hard cap in case pagination ever misbehaves


def get_filler_episodes(mal_id: int, client: httpx.Client) -> set[int]:
    """Returns the set of episode numbers Jikan flags as filler for this show."""
    filler_numbers: set[int] = set()
    page = 1
    while page <= _MAX_PAGES:
        resp = client.get(f"{BASE_URL}/anime/{mal_id}/episodes", params={"page": page})
        resp.raise_for_status()
        data = resp.json()
        for ep in data.get("data", []):
            if ep.get("filler"):
                filler_numbers.add(ep["mal_id"])  # Jikan's per-episode "mal_id" is really the episode number
        if not data.get("pagination", {}).get("has_next_page"):
            break
        page += 1
    return filler_numbers
