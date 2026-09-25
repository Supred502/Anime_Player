"""Reading subtitle files into timed lines: SRT, ASS/SSA and WebVTT -- the
three formats Japanese subtitles on Jimaku come in -- plus the zip archives
many of them are bundled as, one per season.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Cue:
    start: float  # seconds
    end: float
    text: str


SUBTITLE_EXTENSIONS = (".srt", ".ass", ".ssa", ".vtt")

_SRT_TIME = r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})"
_SRT_RANGE_RE = re.compile(_SRT_TIME + r"\s*-->\s*" + _SRT_TIME)
_VTT_TIME = r"(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})"
_VTT_RANGE_RE = re.compile(_VTT_TIME + r"\s*-->\s*" + _VTT_TIME)
_TAG_RE = re.compile(r"<[^>]+>")
# ASS override blocks ({\an8}, {\pos(..)}, {\c&H..&}) and drawing commands.
_ASS_OVERRIDE_RE = re.compile(r"\{[^}]*\}")


def _seconds(h, m, s, ms) -> float:
    ms = (ms or "0").ljust(3, "0")
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def _clean(text: str) -> str:
    text = _TAG_RE.sub("", text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def parse_srt(text: str) -> list[Cue]:
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            match = _SRT_RANGE_RE.search(line)
            if match:
                g = match.groups()
                body = _clean("\n".join(lines[i + 1:]))
                if body:
                    cues.append(Cue(_seconds(*g[:4]), _seconds(*g[4:]), body))
                break
    return cues


def parse_vtt(text: str) -> list[Cue]:
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            match = _VTT_RANGE_RE.search(line)
            if match:
                g = match.groups()
                body = _clean("\n".join(lines[i + 1:]))
                if body:
                    cues.append(Cue(_seconds(*g[:4]), _seconds(*g[4:]), body))
                break
    return cues


def parse_ass(text: str) -> list[Cue]:
    """Dialogue lines only, in the order the [Events] Format line gives.
    Signs and karaoke are usually on their own styles; drawings ({\\p1})
    produce no readable text and are dropped."""
    cues = []
    fields: list[str] = []
    in_events = False
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if line.startswith("["):
            in_events = line.lower() == "[events]"
            continue
        if not in_events:
            continue
        if line.lower().startswith("format:"):
            fields = [f.strip().lower() for f in line[7:].split(",")]
            continue
        if not line.lower().startswith("dialogue:") or not fields:
            continue
        values = line[9:].split(",", len(fields) - 1)
        row = dict(zip(fields, (v.strip() for v in values)))
        body = row.get("text", "")
        if "\\p1" in body or "\\p2" in body:
            continue
        body = _ASS_OVERRIDE_RE.sub("", body).replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
        body = _clean(body)
        start = _ass_time(row.get("start", ""))
        end = _ass_time(row.get("end", ""))
        if body and start is not None and end is not None:
            cues.append(Cue(start, end, body))
    cues.sort(key=lambda c: c.start)
    return cues


def _ass_time(value: str) -> float | None:
    match = re.match(r"(\d+):(\d{2}):(\d{2})[.,](\d{1,3})", value)
    if not match:
        return None
    h, m, s, cs = match.groups()
    # ASS times are in centiseconds.
    return int(h) * 3600 + int(m) * 60 + int(s) + int(cs.ljust(2, "0")[:2]) / 100


def decode(data: bytes) -> str:
    """Japanese subtitle files turn up in UTF-8 (with or without a BOM),
    UTF-16, and the older Shift-JIS."""
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16")
    for encoding in ("utf-8-sig", "cp932", "euc-jp"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse(name: str, data: bytes) -> list[Cue]:
    text = decode(data)
    lower = name.lower()
    if lower.endswith((".ass", ".ssa")):
        return parse_ass(text)
    if lower.endswith(".vtt"):
        return parse_vtt(text)
    return parse_srt(text)


# Episode numbers as they appear in subtitle filenames: "- 03", "E03",
# "#03", "第3話", "[03]", "_03.", " 03 ". Tried in this order; the first
# pattern to match wins, since the looser ones also match years and
# resolutions.
_EPISODE_PATTERNS = [
    re.compile(r"第\s*(\d{1,4})\s*[話回]"),
    re.compile(r"[Ss]\d{1,2}[Ee](\d{1,4})"),
    re.compile(r"(?:^|[\s_.\[(-])[Ee][Pp]?\s*(\d{1,4})(?![\dp])"),
    re.compile(r"\s-\s*(\d{1,4})(?:v\d)?(?:\s|\.|\[|\(|$)"),
    re.compile(r"#(\d{1,4})\b"),
    re.compile(r"\[(\d{1,4})(?:v\d)?\]"),
    re.compile(r"[\s_.](\d{1,4})(?:v\d)?\.(?:srt|ass|ssa|vtt)$", re.IGNORECASE),
]


def episode_in_name(name: str) -> int | None:
    base = name.rsplit("/", 1)[-1]
    for pattern in _EPISODE_PATTERNS:
        match = pattern.search(base)
        if match:
            number = int(match.group(1))
            # 1080, 720, 2023: resolutions and years, not episodes.
            if number in (480, 720, 1080, 2160) or 1900 <= number <= 2100:
                continue
            return number
    return None


def _preference(name: str) -> int:
    lower = name.lower()
    # SRT and VTT are plain dialogue; ASS often carries signs and songs as
    # extra lines -- still fine, just noisier.
    return {".srt": 0, ".vtt": 1, ".ass": 2, ".ssa": 3}.get(lower[lower.rfind("."):], 9)


def pick_from_zip(data: bytes, episode: int) -> tuple[str, bytes] | None:
    """The subtitle for `episode` inside a season archive, if it has one."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [n for n in archive.namelist()
                 if n.lower().endswith(SUBTITLE_EXTENSIONS) and not n.startswith("__MACOSX")]
        matching = [n for n in names if episode_in_name(n) == episode]
        if not matching and len(names) == 1 and episode == 1:
            matching = names
        if not matching:
            return None
        best = min(matching, key=_preference)
        return best, archive.read(best)
