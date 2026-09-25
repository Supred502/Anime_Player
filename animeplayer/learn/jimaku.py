"""Japanese subtitles from Jimaku (https://jimaku.cc), a community archive of
them for anime.

API as documented at https://jimaku.cc/api/docs (checked against the live
OpenAPI spec): an account's API key goes in the Authorization header;
entries are looked up by AniList id; an entry's files can be filtered by
episode number, which Jimaku guesses from the filenames. Rate limited per IP
with HTTP 429.

Only ever asked for the episode being watched, and each answer is cached by
the caller, so a whole season costs a handful of requests.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from animeplayer.learn import subtitles

BASE_URL = "https://jimaku.cc/api"


class JimakuError(Exception):
    """Something the user can act on: no key, a bad key, nothing uploaded."""


@dataclass(frozen=True, slots=True)
class SubtitleFile:
    name: str
    url: str
    size: int


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": api_key.strip(), "Accept": "application/json"}


def _get(client: httpx.Client, api_key: str, path: str, params: dict | None = None):
    if not api_key.strip():
        raise JimakuError("Add your Jimaku API key in Settings to get Japanese subtitles.")
    resp = client.get(f"{BASE_URL}{path}", params=params, headers=_headers(api_key), timeout=20)
    if resp.status_code == 401:
        raise JimakuError("Jimaku didn't accept the API key -- check it in Settings.")
    if resp.status_code == 429:
        raise JimakuError("Jimaku is rate-limiting us -- try again in a moment.")
    resp.raise_for_status()
    return resp.json()


def find_entry(client: httpx.Client, api_key: str, anilist_id: int) -> int | None:
    entries = _get(client, api_key, "/entries/search", {"anilist_id": anilist_id, "anime": "true"})
    return entries[0]["id"] if entries else None


def files_for(client: httpx.Client, api_key: str, entry_id: int, episode: int) -> list[SubtitleFile]:
    """Files for this episode, falling back to the whole listing -- where
    season zips live, since their names carry no single episode number."""
    def listing(params):
        return [SubtitleFile(f["name"], f["url"], f.get("size") or 0)
                for f in _get(client, api_key, f"/entries/{entry_id}/files", params)]

    exact = listing({"episode": episode})
    return exact or listing(None)


def fetch_episode(client: httpx.Client, api_key: str, anilist_id: int,
                  episode: int) -> tuple[str, list[subtitles.Cue]]:
    """(file name, cues) for one episode. Raises JimakuError with a message
    fit for the user when there is nothing to show."""
    entry_id = find_entry(client, api_key, anilist_id)
    if entry_id is None:
        raise JimakuError("Jimaku has no Japanese subtitles for this show yet.")
    candidates = files_for(client, api_key, entry_id, episode)

    # Plain subtitle files named for this episode first, then archives.
    direct = [f for f in candidates if f.name.lower().endswith(subtitles.SUBTITLE_EXTENSIONS)
              and subtitles.episode_in_name(f.name) in (episode, None)]
    direct.sort(key=lambda f: (subtitles.episode_in_name(f.name) != episode,
                               subtitles._preference(f.name)))
    for f in direct:
        data = client.get(f.url, headers=_headers(api_key), timeout=30, follow_redirects=True)
        data.raise_for_status()
        cues = subtitles.parse(f.name, data.content)
        if cues:
            return f.name, cues

    for f in (f for f in candidates if f.name.lower().endswith(".zip")):
        data = client.get(f.url, headers=_headers(api_key), timeout=60, follow_redirects=True)
        data.raise_for_status()
        picked = subtitles.pick_from_zip(data.content, episode)
        if picked:
            cues = subtitles.parse(*picked)
            if cues:
                return picked[0], cues

    raise JimakuError(f"Jimaku has this show, but no Japanese subtitles for episode {episode}.")
