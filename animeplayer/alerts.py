"""New-episode alerts: which shows you're watching have aired something you
haven't seen, and which of those are news since the last check.

Pure logic over plain values, so it is testable without AniList, a database
or Qt. The backend supplies:

- airing:  what AniList says has aired (anilist/client.AiringState)
- watched: anilist id -> episodes watched, from the AniList list and local
  playback, whichever is further along
- seen:    anilist id -> newest episode already announced
"""

from __future__ import annotations

from dataclasses import dataclass

from animeplayer.anilist.client import AiringState


@dataclass(frozen=True, slots=True)
class NewEpisodes:
    state: AiringState
    watched: int

    @property
    def unwatched(self) -> int:
        return max(0, self.state.latest_aired - self.watched)


def find_new_episodes(
    airing: list[AiringState],
    watched: dict[int, int],
    seen: dict[int, int],
) -> tuple[list[NewEpisodes], list[NewEpisodes], dict[int, int]]:
    """Returns (waiting, announce, seen_updates).

    waiting:  every still-airing show with an aired episode you haven't
              watched -- what the home page row shows.
    announce: the subset that aired since the last check -- what gets a
              desktop notification. A show seen for the first time is only
              recorded, never announced: otherwise turning alerts on (or a
              fresh install) would fire one for every show at once.
    seen_updates: the new high-water marks to store.
    """
    waiting, announce, updates = [], [], {}
    for state in airing:
        media_id = state.media.id
        latest = state.latest_aired
        if latest <= 0:
            continue
        behind = NewEpisodes(state=state, watched=watched.get(media_id, 0))
        previously = seen.get(media_id)

        # A finished show you stopped halfway through isn't "new episodes";
        # it's a backlog. Only airing shows go in the row -- but a finale
        # that aired since the last check is still worth announcing.
        if behind.unwatched > 0 and state.next_episode is not None:
            waiting.append(behind)
        if previously is not None and latest > previously and behind.unwatched > 0:
            announce.append(behind)
        if previously is None or latest > previously:
            updates[media_id] = latest

    waiting.sort(key=lambda n: -(n.state.next_airing_at or 0))
    return waiting, announce, updates
