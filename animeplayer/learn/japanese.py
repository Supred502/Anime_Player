"""Breaking a Japanese subtitle line into words a beginner can read.

Japanese is written without spaces, so the first job is splitting a line into
words at all. fugashi (a MeCab binding) does that with the UniDic dictionary,
and for each word also gives its reading and its dictionary form -- 食べた
comes back as 食べ + た, with 食べる as the form to look up. cutlet turns the
line into Hepburn romaji, handling the spelling-vs-sound cases a naive kana
table gets wrong (the particle は is "wa", not "ha").
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from functools import lru_cache

# UniDic's first-level part of speech, in words a beginner knows.
_POS = {
    "名詞": "noun", "代名詞": "pronoun", "動詞": "verb", "形容詞": "adjective",
    "形状詞": "na-adjective", "副詞": "adverb", "助詞": "particle",
    "助動詞": "auxiliary", "接続詞": "conjunction", "感動詞": "interjection",
    "連体詞": "pre-noun adjectival", "接頭辞": "prefix", "接尾辞": "suffix",
    "補助記号": "punctuation", "記号": "symbol", "空白": "space",
}

# UniDic picks the formal reading for a few everyday words, which is not
# what a beginner will hear in anime: 私 is almost always わたし, not わたくし.
_READING_OVERRIDES = {"私": "わたし"}
_ROMAJI_OVERRIDES = {"私": "watashi"}

_KANJI_RE = re.compile(r"[一-鿿㐀-䶿々〆ヵヶ]")
_KATAKANA_TO_HIRAGANA = {code: code - 0x60 for code in range(ord("ァ"), ord("ヶ") + 1)}


def to_hiragana(text: str) -> str:
    return text.translate(_KATAKANA_TO_HIRAGANA)


def has_kanji(text: str) -> bool:
    return bool(_KANJI_RE.search(text))


@dataclass(frozen=True, slots=True)
class Token:
    surface: str       # as written in the line
    reading: str       # hiragana; "" for punctuation and unknown words
    lemma: str         # dictionary form to look up, e.g. 食べる for 食べ
    pos: str           # "verb", "particle", ...
    furigana: bool     # whether the reading is worth showing above it
    lookup: bool       # whether hovering it should look anything up


@lru_cache(maxsize=1)
def _tagger():
    import fugashi
    return fugashi.Tagger()


@lru_cache(maxsize=1)
def _romanizer():
    import cutlet
    katsu = cutlet.Cutlet()
    # Foreign words in katakana come out as their English spelling ("pizza"
    # rather than "piza") -- friendlier for someone who reads English.
    katsu.use_foreign_spelling = True
    for word, reading in _ROMAJI_OVERRIDES.items():
        katsu.add_exception(word, reading)
    return katsu


def tokens(line: str) -> list[Token]:
    out = []
    for word in _tagger()(line):
        feature = word.feature
        surface = word.surface
        pos_ja = feature.pos1 or ""
        pos = _POS.get(pos_ja, "")
        # UniDic writes some lemmas with a disambiguation tag: "私-代名詞".
        lemma = (feature.lemma or surface).split("-")[0]
        reading = _READING_OVERRIDES.get(surface) or to_hiragana(feature.kana or "")
        if surface == to_hiragana(surface) and not has_kanji(surface):
            # Already kana: its reading is itself (katakana shown as is).
            reading = to_hiragana(surface)
        punctuation = pos in ("punctuation", "symbol", "space")
        out.append(Token(
            surface=surface,
            reading="" if punctuation else reading,
            lemma=lemma,
            pos=pos,
            furigana=has_kanji(surface) and bool(reading),
            lookup=not punctuation,
        ))
        # Leading whitespace MeCab swallowed would otherwise vanish.
        if word.white_space:
            out.insert(len(out) - 1, Token(word.white_space, "", "", "space", False, False))
    return out


# A small っ at the end of a word is a clipped, cut-off sound ("クソッ!") with
# no letter of its own; cutlet renders it as a stray "t" or "?".
_TRAILING_SOKUON_RE = re.compile(r"[っッ]+(?=[\s、。！？!?…‥」』）)～〜]|$)")


def romaji(line: str) -> str:
    """Row by row, so a two-row subtitle stays two rows ("... / ...")."""
    rows = [_TRAILING_SOKUON_RE.sub("", row) for row in line.split("\n")]
    return " / ".join(_romanizer().romaji(row) for row in rows if row.strip())


# Japanese subtitles, especially closed-caption style ones, carry extras a
# beginner would trip over:
#   (藤田)松村！        a speaker label before the line
#   松村(まつむら)       a reading written inline -- furigana already does this
#   (松村のうめき声)     a whole line describing a sound
_INLINE_READING_RE = re.compile(r"([\u4e00-\u9fff\u3400-\u4dbf々〆ヵヶ]+)[（(]([\u3041-\u3096ー]+)[)）]")
_SPEAKER_RE = re.compile(r"^[（(]([^（()）\n]{1,20})[)）]\s*(?=\S)")
_CAPTION_RE = re.compile(r"^[（(\[［＜<][^\n]*[)）\]］＞>]$")


def clean_line(text: str) -> tuple[str, str, bool]:
    """(speaker, line, is_caption). A two-speaker line gives both names,
    "カイマン / ニカイドウ", in row order."""
    speakers = []
    rows = []
    for row in text.split("\n"):
        row = _INLINE_READING_RE.sub(r"\1", row.strip())
        match = _SPEAKER_RE.match(row)
        if match:
            speakers.append(_INLINE_READING_RE.sub(r"\1", match.group(1)))
            row = row[match.end():]
        rows.append(row.replace("\u3000", " ").strip())
    line = "\n".join(r for r in rows if r)
    return " / ".join(speakers), line, bool(_CAPTION_RE.match(line))


def analyse(line: str) -> dict:
    """A subtitle line, ready for the player: the words, the romaji, who
    says it, and whether it's a sound description rather than speech."""
    speaker, cleaned, caption = clean_line(line)
    return {"tokens": [asdict(t) for t in tokens(cleaned)], "romaji": romaji(cleaned),
            "speaker": speaker, "caption": caption, "text": cleaned}
