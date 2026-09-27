"""Saved words as an Anki deck (.apkg), which Anki on a PC, AnkiDroid and
AnkiMobile all import.

Front: the word, and the line it came from with the word picked out.
Back: its reading, meaning and part of speech, the English line, the show
and episode -- and, when there is one, the audio of the line itself.

Each note's id comes from the word and its sentence, so exporting again
later and importing the new file updates the cards already in Anki rather
than adding the same ones twice.
"""

from __future__ import annotations

import html
from pathlib import Path

import genanki

# Fixed forever: Anki recognises a deck and a note type by these numbers,
# which is what lets a later export update the cards from an earlier one.
MODEL_ID = 1_761_442_901
DECK_ID = 1_761_442_902

_CSS = """
.card { font-family: "Noto Sans CJK JP", "Hiragino Sans", "Yu Gothic", sans-serif;
        text-align: center; font-size: 22px; color: #eee; background: #202326; }
.word { font-size: 56px; margin: 12px 0; }
.sentence { font-size: 22px; opacity: .9; }
.sentence b { color: #ffb347; }
.reading { font-size: 28px; color: #ffb347; }
.meaning { font-size: 24px; margin: 8px 0; }
.pos, .source { font-size: 14px; opacity: .6; }
.translation { font-size: 18px; opacity: .8; margin-top: 10px; font-style: italic; }
"""

_MODEL = genanki.Model(
    MODEL_ID,
    "Anime Player word",
    fields=[{"name": n} for n in ("Word", "Reading", "Meaning", "PartOfSpeech", "Sentence",
                                   "Translation", "Source", "Audio")],
    templates=[{
        "name": "Recognise",
        "qfmt": '<div class="word">{{Word}}</div><div class="sentence">{{Sentence}}</div>',
        "afmt": '{{FrontSide}}<hr id="answer">'
                '<div class="reading">{{Reading}}</div><div class="meaning">{{Meaning}}</div>'
                '<div class="pos">{{PartOfSpeech}}</div><div class="translation">{{Translation}}</div>'
                '<div class="source">{{Source}}</div>{{Audio}}',
    }],
    css=_CSS,
)


def _sentence_with_word(sentence: str, word: str, reading: str) -> str:
    text = html.escape(sentence)
    for form in (word, reading):
        if form and html.escape(form) in text:
            return text.replace(html.escape(form), f"<b>{html.escape(form)}</b>", 1)
    return text


def build_deck(words: list[dict], out_path: Path, audio: dict[int, Path] | None = None,
               deck_name: str = "Anime Player — Japanese") -> int:
    """Writes the .apkg; `audio` maps a word's id to a sound file of its
    line. Returns how many cards went in."""
    audio = audio or {}
    deck = genanki.Deck(DECK_ID, deck_name)
    media: list[str] = []
    for w in words:
        source = w.get("title") or ""
        if w.get("episode"):
            source += f" · episode {w['episode']:g}"
        sound = ""
        if w.get("id") in audio:
            clip = audio[w["id"]]
            media.append(str(clip))
            sound = f"[sound:{clip.name}]"
        deck.add_note(genanki.Note(
            model=_MODEL,
            fields=[
                html.escape(w["word"]),
                html.escape(w.get("reading") or "" if w.get("reading") != w["word"] else ""),
                html.escape(w.get("meaning") or ""),
                html.escape(w.get("pos") or ""),
                _sentence_with_word(w.get("sentence") or "", w["word"], w.get("reading") or ""),
                html.escape(w.get("translation") or ""),
                html.escape(source),
                sound,
            ],
            guid=genanki.guid_for(w["word"], w.get("sentence") or ""),
        ))
    package = genanki.Package(deck)
    package.media_files = media
    out_path.parent.mkdir(parents=True, exist_ok=True)
    package.write_to_file(str(out_path))
    return len(deck.notes)
