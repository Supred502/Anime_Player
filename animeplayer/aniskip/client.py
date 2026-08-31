"""Client for the Aniskip API (https://api.aniskip.com) -- crowd-sourced
opening/ending skip timestamps.

Keyed by MyAnimeList id, not AniList id -- confirmed against the service's
own Swagger schema (GET https://api.aniskip.com/api-docs-json, both the v1
and v2 skip-times paths document their id path param as "MAL id of the
anime"). This is why callers need id_mal (already resolved via AniList's
idMal field, see anilist/client.py's MediaSummary) rather than the AniList
media id used everywhere else in this app.

Note: live-checked during development against several MAL ids (including
very popular shows like Death Note, MAL id 1535) and the service returned
HTTP 500 for every request tried, including ones matching the documented
request shape exactly. That looks like a server-side outage rather than a
request-shape bug here, but it means this integration could not be verified
end-to-end against real skip data. Failures are swallowed on purpose (see
get_skip_times below) so an Aniskip outage never affects playback -- skip
times are a nice-to-have, not core functionality.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

API_URL = "https://api.aniskip.com/v2/skip-times"


@dataclass(frozen=True, slots=True)
class SkipInterval:
    start: float  # seconds into the episode
    end: float


def get_skip_times(mal_id: int, episode_number: float, client: httpx.Client) -> dict[str, SkipInterval]:
    """Returns {"op": SkipInterval, "ed": SkipInterval} for whichever of the
    two exist for this episode -- either or both keys may be absent. Returns
    an empty dict on any error (network, non-200, unparseable body, or the
    API reporting nothing found): skip times are a nice-to-have overlay, so a
    failure here should never surface as an error to the user or block
    playback."""
    try:
        resp = client.get(
            f"{API_URL}/{mal_id}/{episode_number}",
            params=[("types", "op"), ("types", "ed"), ("episodeLength", "0")],
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return {}

    if not data.get("found"):
        return {}

    out: dict[str, SkipInterval] = {}
    for result in data.get("results", []):
        skip_type = result.get("skipType")
        if skip_type not in ("op", "ed"):
            continue
        interval = result.get("interval") or {}
        start, end = interval.get("startTime"), interval.get("endTime")
        if start is None or end is None:
            continue
        out[skip_type] = SkipInterval(start=float(start), end=float(end))
    return out
