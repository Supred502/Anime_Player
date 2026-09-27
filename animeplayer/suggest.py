""""Did you mean ...?" for searches that found nothing.

Neither the streaming site nor AniList forgives a typo -- "freiren", "one
peice" and "demon slayr" all come back empty -- so the suggestion comes
from comparing the search against a list of known titles (the most popular
on AniList, plus anything the app has already seen): every name a show goes
by, romaji and English and synonyms, and the closest spelling wins.
"""

from __future__ import annotations

import difflib
import re

_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    return _NON_WORD.sub(" ", text.lower()).strip()


def closest_title(query: str, catalog: list[tuple[str, tuple[str, ...]]],
                  cutoff: float = 0.78) -> str | None:
    """The display title of the entry in `catalog` -- (display title, every
    name it goes by) -- whose name is spelled most like `query`, or None if
    nothing is close enough to be worth suggesting. A query that is already
    one of the names returns None: there's nothing to correct."""
    wanted = normalize(query)
    if len(wanted) < 3:
        return None
    best: tuple[float, str] | None = None
    for display, names in catalog:
        for name in names:
            candidate = normalize(name)
            if not candidate:
                continue
            if candidate == wanted:
                return None
            # Against the whole name, and against its start: "jujutsu kaisn"
            # is a misspelt start of "jujutsu kaisen 0" as much as of
            # "jujutsu kaisen".
            # By whole words: "demon slayr" against "demon slayer", the first
            # two words of "demon slayer kimetsu no yaiba".
            prefix = " ".join(candidate.split()[:len(wanted.split())])
            ratio = max(difflib.SequenceMatcher(None, wanted, candidate).ratio(),
                        difflib.SequenceMatcher(None, wanted, prefix).ratio())
            if ratio >= cutoff and (best is None or ratio > best[0]):
                best = (ratio, display)
    return best[1] if best else None
