"""The Japanese-English dictionary behind hover-to-look-up: JMdict.

JMdict is the standard free Japanese-English dictionary, maintained by the
Electronic Dictionary Research and Development Group and published under
CC BY-SA 4.0 (https://www.edrdg.org/edrdg/licence.html) -- the attribution
is shown in the app wherever definitions appear.

It ships as one ~10 MB gzipped XML file, updated daily. That is downloaded
the first time learning mode is used and converted once into a small SQLite
database beside the app's own, indexed by every way each word can be
written (kanji forms and kana readings alike), so a lookup while a
subtitle is on screen is a single indexed query.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import httpx

JMDICT_URL = "https://www.edrdg.org/pub/Nihongo/JMdict_e.gz"

# Priority tags JMdict uses for words in everyday use (news, ichimango and
# spec lists). A word carrying any of them is ranked above rare homographs:
# looking up 見る should put "to see" first, not an obscure namesake.
_COMMON_TAGS = {"news1", "ichi1", "spec1", "spec2", "gai1"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id       INTEGER PRIMARY KEY,
    kanji    TEXT NOT NULL,   -- JSON list of written forms
    readings TEXT NOT NULL,   -- JSON list of kana readings
    senses   TEXT NOT NULL,   -- JSON list of {"pos": [...], "glosses": [...]}
    common   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS forms (
    form     TEXT NOT NULL,
    entry_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS forms_form ON forms(form);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


@dataclass(frozen=True, slots=True)
class Definition:
    kanji: tuple[str, ...]
    readings: tuple[str, ...]
    senses: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]  # (parts of speech, glosses)
    common: bool


def build(source_gz: Path, target: Path) -> int:
    """Converts JMdict_e.gz into the lookup database. Returns the number of
    entries. Written to a temporary file and renamed, so an interrupted
    build never leaves a half-empty dictionary behind."""
    partial = target.with_suffix(".building")
    partial.unlink(missing_ok=True)
    conn = sqlite3.connect(partial)
    conn.executescript(_SCHEMA)
    count = 0
    entries, forms = [], []
    with gzip.open(source_gz) as xml:
        for _event, element in ET.iterparse(xml, events=("end",)):
            if element.tag != "entry":
                continue
            entry_id = int(element.findtext("ent_seq"))
            kanji = [k.findtext("keb") for k in element.findall("k_ele")]
            readings = [r.findtext("reb") for r in element.findall("r_ele")]
            priorities = {p.text for p in element.iter() if p.tag in ("ke_pri", "re_pri")}
            senses = []
            last_pos: list[str] = []
            for sense in element.findall("sense"):
                pos = [p.text for p in sense.findall("pos")] or last_pos
                last_pos = pos  # JMdict states the part of speech once for a run of senses
                glosses = [g.text for g in sense.findall("gloss") if g.text]
                if glosses:
                    senses.append({"pos": pos, "glosses": glosses})
            entries.append((entry_id, json.dumps(kanji, ensure_ascii=False),
                            json.dumps(readings, ensure_ascii=False),
                            json.dumps(senses, ensure_ascii=False),
                            1 if priorities & _COMMON_TAGS else 0))
            forms.extend((form, entry_id) for form in set(kanji + readings) if form)
            count += 1
            element.clear()
            if len(entries) >= 5000:
                conn.executemany("INSERT INTO entries VALUES (?,?,?,?,?)", entries)
                conn.executemany("INSERT INTO forms VALUES (?,?)", forms)
                entries, forms = [], []
    conn.executemany("INSERT INTO entries VALUES (?,?,?,?,?)", entries)
    conn.executemany("INSERT INTO forms VALUES (?,?)", forms)
    conn.execute("INSERT INTO meta VALUES ('entries', ?)", (str(count),))
    conn.commit()
    conn.close()
    partial.replace(target)
    return count


class Dictionary:
    """Lookups against the built database. Safe to share between threads."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    @property
    def ready(self) -> bool:
        return self._path.exists()

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._path, check_same_thread=False)
        return self._conn

    def lookup(self, *forms: str, limit: int = 3) -> list[Definition]:
        """Entries written or read as any of `forms`, tried in order -- the
        dictionary form first, so 食べた finds 食べる -- with everyday words
        ahead of rare ones."""
        if not self.ready:
            return []
        seen: set[int] = set()
        found: list[Definition] = []
        with self._lock:
            conn = self._connection()
            for form in forms:
                if not form:
                    continue
                rows = conn.execute(
                    "SELECT e.id, e.kanji, e.readings, e.senses, e.common FROM forms f "
                    "JOIN entries e ON e.id = f.entry_id WHERE f.form = ? "
                    "ORDER BY e.common DESC, e.id LIMIT ?",
                    (form, limit),
                ).fetchall()
                for entry_id, kanji, readings, senses, common in rows:
                    if entry_id in seen:
                        continue
                    seen.add(entry_id)
                    found.append(Definition(
                        kanji=tuple(json.loads(kanji)),
                        readings=tuple(json.loads(readings)),
                        senses=tuple((tuple(s["pos"]), tuple(s["glosses"])) for s in json.loads(senses)),
                        common=bool(common),
                    ))
                if len(found) >= limit:
                    break
        return found[:limit]


def download(target_gz: Path, client: httpx.Client, on_progress=None) -> None:
    """Fetches JMdict_e.gz. `on_progress(fraction)` is called as it arrives."""
    partial = target_gz.with_suffix(".part")
    with client.stream("GET", JMDICT_URL, timeout=120) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length") or 0)
        written = 0
        with partial.open("wb") as out:
            for chunk in response.iter_bytes(256 * 1024):
                out.write(chunk)
                written += len(chunk)
                if on_progress and total:
                    on_progress(written / total)
    partial.replace(target_gz)
