"""Lining Japanese subtitles up with the video being played.

Japanese subtitles on Jimaku are usually timed to some other release of the
episode than the one the source streams -- a different encode, with or
without a logo or recap in front -- so they run early or late by a few
seconds. Measured on a real episode: 9.8 seconds late.

The stream's own English subtitles are timed correctly for it, and a line of
dialogue starts at the same moment in both languages. So: slide the Japanese
start times along, and keep the offset at which the most of them land on an
English start. On that episode the right offset matched 232 of 334 lines;
offsets two seconds either side matched about 50.
"""

from __future__ import annotations

import bisect

SEARCH_SECONDS = 120.0
STEP = 0.1
TOLERANCE = 0.35


def _matches(jp_starts: list[float], en_starts: list[float], offset: float) -> int:
    hits = 0
    for start in jp_starts:
        t = start + offset
        i = bisect.bisect_left(en_starts, t - TOLERANCE)
        if i < len(en_starts) and en_starts[i] <= t + TOLERANCE:
            hits += 1
    return hits


def best_offset(jp_starts: list[float], en_starts: list[float]) -> float | None:
    """Seconds to add to the Japanese times, or None when no offset stands
    out -- then the subtitles are left alone rather than moved to a guess."""
    if len(jp_starts) < 10 or len(en_starts) < 10:
        return None
    en = sorted(en_starts)
    steps = int(SEARCH_SECONDS / STEP)
    scored = [(_matches(jp_starts, en, i * STEP), round(i * STEP, 1)) for i in range(-steps, steps + 1)]
    hits = max(s[0] for s in scored)
    # Within the matching tolerance several neighbouring offsets score the
    # same; the true one is the middle of that run, not its edge.
    tied = [o for h, o in scored if h == hits]
    offset = tied[len(tied) // 2]
    # Background: what a wrong offset scores, by chance alone. A real match
    # stands well clear of it.
    typical = sorted(s[0] for s in scored)[len(scored) // 2]
    if hits < 10 or hits < 2 * max(typical, 1) or hits < 0.25 * len(jp_starts):
        return None
    return offset
