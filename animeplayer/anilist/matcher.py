"""Matches titles between the streaming source and AniList, in both directions.

``resolve_media_id`` (source title -> AniList id) powers the search-page status
badges. ``best_source_result`` (AniList title -> source result, the reverse)
powers clicking a Home-page AniList card through to something playable. Both
use the same difflib scoring and AniList's own search is fuzzy on its end
already, so results are picked from a small candidate set rather than scored
against the whole catalog.
"""

from __future__ import annotations

import difflib
import re
from typing import TYPE_CHECKING, Sequence, TypeVar

from animeplayer.anilist.client import AniListClient, MediaSummary
from animeplayer.storage.db import Database

if TYPE_CHECKING:
    from animeplayer.sources.hianime import SearchResult

_MATCH_THRESHOLD = 0.6

T = TypeVar("T")


def _normalize(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def _best_match(target_title: str, candidates: Sequence[tuple[T, Sequence[str]]]) -> T | None:
    target = _normalize(target_title)
    best_item: T | None = None
    best_score = 0.0
    for item, titles in candidates:
        for candidate_title in titles:
            score = difflib.SequenceMatcher(None, target, _normalize(candidate_title)).ratio()
            if score > best_score:
                best_score = score
                best_item = item
    return best_item if best_score >= _MATCH_THRESHOLD else None


def resolve_media_id(title: str, client: AniListClient, db: Database) -> int | None:
    if db.has_title_mapping(title):
        return db.get_title_mapping(title)

    candidates = client.search_media(title)
    resolved = _best_match(title, [(m.id, m.titles) for m in candidates])
    db.save_title_mapping(title, resolved)
    return resolved


def resolve_media_summary(title: str, client: AniListClient, db: Database) -> MediaSummary | None:
    """Like resolve_media_id, but returns the full AniList details (rating,
    genres, description, ...) for DetailPage enrichment, not just the id."""
    if db.has_title_mapping(title):
        media_id = db.get_title_mapping(title)
        return client.get_media_by_id(media_id) if media_id is not None else None

    candidates = client.search_media(title)
    resolved = _best_match(title, [(m, m.titles) for m in candidates])
    db.save_title_mapping(title, resolved.id if resolved else None)
    return resolved


def best_source_result(title: str, results: list["SearchResult"]) -> "SearchResult | None":
    """Picks the source result whose title best matches an AniList title."""
    return _best_match(title, [(r, (r.title,)) for r in results])
