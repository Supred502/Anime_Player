"""Matches titles between the streaming source and AniList, in both directions.

``resolve_media_id`` (source title -> AniList id) powers the search-page status
badges. ``find_source_result`` (AniList entry -> source result, the reverse)
powers clicking a Home-page AniList card through to something playable.

Both sides of this are messier than "compare two strings", and every rule
below came out of watching real lookups fail:

* **The two catalogs don't agree on which title is the title.** AniList shows
  a romaji title ("Kimetsu no Yaiba: Katanakaji no Sato-hen"); the source
  indexes the licensed English one ("Demon Slayer: Kimetsu no Yaiba
  Swordsmith Village Arc"). Searching one and scoring against the other finds
  nothing, so every lookup uses the *whole* set of titles AniList knows
  (romaji, English, synonyms) as both queries and scoring candidates.
* **Season numbers have to be compared, not blended into the similarity.**
  "Sousou no Frieren" scores 0.77 against "Sousou no Frieren 3rd Season" --
  high enough to win -- so clicking season 1 used to open season 3. Season
  (and part) numbers are now pulled out and compared as numbers.
* **A recap or a special has almost the same name as the thing it recaps.**
  "Bakemonogatari" resolved to "Bakemonogatari Recap"; season 2 of Arifureta
  resolved to its "Picture Drama". A side-story marker on one side only is
  penalised.
* **One catalog appends a qualifier the other omits.** "Bakemonogatari" vs
  "Bakemonogatari (The Monogatari Series)" is a poor similarity score but an
  exact prefix, so a long-enough prefix match is treated as a strong match.

Measured against 49 real entries from a live AniList list: 47 resolved before,
49 after, and five of the seven changed answers were previously matching the
wrong show (a recap, a picture drama, an OVA, or the wrong season).
"""

from __future__ import annotations

import difflib
import re
from typing import TYPE_CHECKING, Callable, Generic, Sequence, TypeVar

from animeplayer.anilist.client import AniListClient, MediaSummary
from animeplayer.storage.db import Database

if TYPE_CHECKING:
    from animeplayer.sources.hianime import SearchResult

_MATCH_THRESHOLD = 0.6

# A season mismatch has to outweigh the similarity a same-franchise title
# keeps: "Sousou no Frieren" vs "Sousou no Frieren 3rd Season" is 0.77, and
# 0.77 - 0.35 falls below the threshold while an exact match survives it.
_SEASON_PENALTY = 0.35
_PART_PENALTY = 0.15
_SIDE_STORY_PENALTY = 0.2
# A prefix match is worth more than its raw similarity, but not more than a
# genuine exact match, so an entry that really is "<name> Recap" can still
# lose to the entry that is just "<name>".
_PREFIX_SCORE = 0.92
# Shorter than this, a shared prefix is a coincidence ("Monster" in "Monster
# Eater") rather than the same show with extra words after it.
_MIN_PREFIX_LEN = 10

# How many of an entry's titles to actually search with. Each one is a round
# trip, and the first two (romaji and English) find the show in nearly every
# case; the rest are there for the handful that only match on a synonym.
_MAX_QUERIES = 4
# Stop searching more title variants once something is essentially an exact
# match -- nothing later can beat it.
_GOOD_ENOUGH = 0.95

T = TypeVar("T")

_PUNCT_RE = re.compile(r"[^\w\s]+")
_WS_RE = re.compile(r"\s+")
_LATIN_RE = re.compile(r"[a-z0-9]")
_SIDE_STORY_RE = re.compile(
    r"\b(recap|special|specials|extra|extras|picture drama|shorts?|mini anime|"
    r"preview|compilation|summary)\b"
)

_ROMAN = {"ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9}
_ROMAN_RE = "ii|iii|iv|vi{0,3}|ix|v"
_ORDINAL_WORDS = {"second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6}


def _normalize(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def _words(title: str) -> str:
    """Punctuation flattened to spaces, for the season/part patterns below."""
    return _WS_RE.sub(" ", _PUNCT_RE.sub(" ", title)).strip().lower()


def _numbered(text: str, word: str) -> int | None:
    """The number attached to `word`, written any of the ways these two
    catalogs write it: "season 2", "season2", "2nd season", "season II",
    "second season"."""
    for pattern, convert in (
        (rf"\b{word}\s*0*(\d+)\b", int),
        (rf"\b(\d+)(?:st|nd|rd|th)\s+{word}\b", int),
        (rf"\b{word}\s+({_ROMAN_RE})\b", _ROMAN.get),
        (rf"\b(\w+)\s+{word}\b", _ORDINAL_WORDS.get),
    ):
        match = re.search(pattern, text)
        if match:
            number = convert(match.group(1))
            if number:
                return number
    return None


def _season_of(title: str) -> int | None:
    text = _words(title)
    for word in ("season", "cour"):
        number = _numbered(text, word)
        if number:
            return number
    # A bare trailing 2-9 or II-IX is a season ("Overlord II", "Psycho-Pass 3").
    # Deliberately neither 0/1 nor multi-digit: "Steins;Gate 0", "Mob Psycho
    # 100" and "86" end in numbers that are part of the name.
    match = re.search(rf"\b([2-9]|{_ROMAN_RE})$", text)
    if match:
        return int(match.group(1)) if match.group(1).isdigit() else _ROMAN[match.group(1)]
    return None


def _part_of(title: str) -> int | None:
    return _numbered(_words(title), "part")


def _pair_score(left: str, right: str) -> float:
    a, b = _normalize(left), _normalize(right)
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= _MIN_PREFIX_LEN and long.startswith(short):
        return max(ratio, _PREFIX_SCORE)
    return ratio


def _as_titles(titles: str | Sequence[str]) -> Sequence[str]:
    """Guards the one mistake this module's API invites: a plain string IS a
    Sequence[str] in Python, so passing a single title where a list of them is
    expected iterates it into characters and compares letter-by-letter. Silent,
    and every score comes back nonsense."""
    return (titles,) if isinstance(titles, str) else titles


def title_score(left: str | Sequence[str], right: str | Sequence[str]) -> float:
    """How well two sets of names for an anime agree, 0..1.

    Either side may hold several names for the same show (AniList's romaji /
    English / synonyms); the best-agreeing pair decides, since a show only
    needs to be recognisable under one of its names.
    """
    left, right = _as_titles(left), _as_titles(right)
    left_side_story = any(_SIDE_STORY_RE.search(t.lower()) for t in left)
    right_side_story = any(_SIDE_STORY_RE.search(t.lower()) for t in right)
    # A recap/special has nearly the name of the thing it recaps, so this is
    # the single most common way a lookup lands on the wrong entry.
    side_story_mismatch = left_side_story != right_side_story

    best = 0.0
    for a in left:
        season_a, part_a = _season_of(a), _part_of(a)
        for b in right:
            score = _pair_score(a, b)
            if (season_a or 1) != (_season_of(b) or 1):
                score -= _SEASON_PENALTY
            part_b = _part_of(b)
            if part_a is not None and part_b is not None and part_a != part_b:
                score -= _PART_PENALTY
            elif (part_a is None) != (part_b is None):
                # Split-cour shows are inconsistently labelled between the two
                # catalogs, so a missing part number is only a hint.
                score -= _PART_PENALTY / 2
            if side_story_mismatch:
                score -= _SIDE_STORY_PENALTY
            best = max(best, score)
    return best


def _best_match(
    titles: str | Sequence[str], candidates: Sequence[tuple[T, Sequence[str]]]
) -> T | None:
    best_item: T | None = None
    best_score = 0.0
    for item, candidate_titles in candidates:
        score = title_score(titles, candidate_titles)
        if score > best_score:
            best_score = score
            best_item = item
    return best_item if best_score >= _MATCH_THRESHOLD else None


def best_named_match(
    titles: str | Sequence[str], candidates: Sequence[tuple[T, Sequence[str]]]
) -> T | None:
    """The best of a set of already-known candidates, or None if none is close
    enough. The same scoring every other match here uses, exposed for callers
    that hold their own candidate list -- badging a page of results against the
    locally mirrored AniList list, for instance, rather than asking AniList to
    resolve each title over the network.
    """
    return _best_match(titles, candidates)


class TitleIndex(Generic[T]):
    """A prebuilt index over a fixed candidate set, for matching many titles
    against the same list.

    best_named_match() on its own is O(titles x candidates) difflib
    comparisons, and difflib is not cheap: badging one page of 30 browse
    results against a 900-entry AniList list measured at six seconds, which is
    no better than the per-title network lookup it replaced.

    Two things make it fast. Almost every match is exact once the titles are
    normalised, so that is a dict lookup. What's left only gets compared
    against candidates sharing a word with it, which is a handful rather than
    the whole list -- and a title sharing no word at all could never have
    scored above the threshold anyway.
    """

    def __init__(self, candidates: Sequence[tuple[T, Sequence[str]]]) -> None:
        self._exact: dict[str, T] = {}
        self._by_word: dict[str, list[tuple[T, Sequence[str]]]] = {}
        for item, titles in candidates:
            names = _as_titles(titles)
            for name in names:
                self._exact.setdefault(_normalize(name), item)
            for word in {w for name in names for w in _words(name).split() if len(w) > 2}:
                self._by_word.setdefault(word, []).append((item, names))

    def match(self, titles: str | Sequence[str]) -> T | None:
        names = _as_titles(titles)
        for name in names:
            found = self._exact.get(_normalize(name))
            if found is not None:
                return found

        # Deduplicated by identity: one candidate shares many words with the
        # query, and scoring it once per shared word is the cost this index
        # exists to avoid.
        seen: dict[int, tuple[T, Sequence[str]]] = {}
        for name in names:
            for word in set(_words(name).split()):
                for entry in self._by_word.get(word, ()):
                    seen.setdefault(id(entry[0]), entry)
        if not seen:
            return None
        return _best_match(names, list(seen.values()))


def search_queries(titles: str | Sequence[str]) -> list[str]:
    """The title variants worth actually searching the source with.

    Native-script titles are dropped: the source's index is romaji/English, so
    searching a Japanese or Thai synonym is a guaranteed-empty round trip.
    """
    queries: list[str] = []
    seen: set[str] = set()
    for title in _as_titles(titles):
        words = _words(title)
        key = _normalize(title)
        if not words or not key or not _LATIN_RE.search(words) or key in seen:
            continue
        seen.add(key)
        queries.append(words)
    return queries[:_MAX_QUERIES]


def resolve_media_id(title: str, client: AniListClient, db: Database) -> int | None:
    if db.has_title_mapping(title):
        return db.get_title_mapping(title)

    candidates = client.search_media(title)
    resolved = _best_match((title,), [(m.id, m.titles) for m in candidates])
    db.save_title_mapping(title, resolved)
    return resolved


def resolve_media_summary(title: str, client: AniListClient, db: Database) -> MediaSummary | None:
    """Like resolve_media_id, but returns the full AniList details (rating,
    genres, description, ...) for DetailPage enrichment, not just the id."""
    if db.has_title_mapping(title):
        media_id = db.get_title_mapping(title)
        return client.get_media_by_id(media_id) if media_id is not None else None

    candidates = client.search_media(title)
    resolved = _best_match((title,), [(m, m.titles) for m in candidates])
    db.save_title_mapping(title, resolved.id if resolved else None)
    return resolved


def best_source_result(
    titles: str | Sequence[str], results: Sequence["SearchResult"]
) -> "SearchResult | None":
    """Picks the source result that best matches an AniList entry's names."""
    return _best_match(titles, [(r, (r.title,)) for r in results])


def find_source_result(
    titles: str | Sequence[str], search: Callable[[str], list["SearchResult"]]
) -> "SearchResult | None":
    """Searches the source under each of an AniList entry's names and returns
    the best match across all of them.

    Several searches rather than one because the source finds a show under the
    name *it* indexes and no other -- searching AniList's romaji title returns
    nothing at all for a show the source lists under its English title, so a
    single query can't be fixed by better scoring. Stops early as soon as
    something scores near-perfect, which is the common case on the first query.
    """
    titles = _as_titles(titles)
    candidates: dict[str, SearchResult] = {}
    best: SearchResult | None = None
    best_score = 0.0
    for query in search_queries(titles):
        for result in search(query):
            if result.slug_id in candidates:
                continue
            candidates[result.slug_id] = result
            score = title_score(titles, (result.title,))
            if score > best_score:
                best, best_score = result, score
        if best_score >= _GOOD_ENOUGH:
            break
    return best if best_score >= _MATCH_THRESHOLD else None
