import io
import zipfile

import httpx
import pytest
import respx

from animeplayer.learn import japanese, jimaku, subtitles

SRT = "1\n00:00:01,500 --> 00:00:03,000\nお前は<i>もう</i>\n死んでいる\n\n2\n00:01:02,000 --> 00:01:04,250\nなに？\n"
ASS = """[Script Info]
Title: x

[V4+ Styles]
Format: Name, Fontname

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:05.10,0:00:07.00,Default,,0,0,0,,{\\an8}私の名前は\\Nフリーレン、です
Dialogue: 0,0:00:01.00,0:00:02.00,Sign,,0,0,0,,{\\p1}m 0 0 l 10 10{\\p0}
"""
VTT = "WEBVTT\n\n00:00.500 --> 00:02.000\nこんにちは\n"


def test_srt_parses_times_and_strips_tags() -> None:
    cues = subtitles.parse("ep01.srt", SRT.encode())
    assert cues[0] == subtitles.Cue(1.5, 3.0, "お前はもう\n死んでいる")
    assert cues[1].start == 62.0 and cues[1].end == 64.25


def test_ass_keeps_dialogue_drops_drawings_and_sorts() -> None:
    cues = subtitles.parse("ep01.ass", ASS.encode())
    assert cues == [subtitles.Cue(5.1, 7.0, "私の名前は\nフリーレン、です")]


def test_vtt_short_timestamps() -> None:
    assert subtitles.parse("a.vtt", VTT.encode()) == [subtitles.Cue(0.5, 2.0, "こんにちは")]


def test_shift_jis_files_decode() -> None:
    assert subtitles.parse("old.srt", SRT.encode("cp932"))[0].text.startswith("お前")


@pytest.mark.parametrize("name, episode", [
    ("[SubsPlease] Sousou no Frieren - 03 (1080p).srt", 3),
    ("Frieren.S01E12.WEB.ja.srt", 12),
    ("葬送のフリーレン 第7話.ass", 7),
    ("One Piece #1153.srt", 1153),
    ("show [05].ass", 5),
    ("show_2023_1080p.srt", None),
])
def test_episode_numbers_from_filenames(name, episode) -> None:
    assert subtitles.episode_in_name(name) == episode


def _zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buffer.getvalue()


def test_the_right_episode_comes_out_of_a_season_zip() -> None:
    data = _zip({"Show - 01.srt": SRT, "Show - 02.srt": SRT.replace("なに", "えっ"), "readme.txt": "hi"})
    name, content = subtitles.pick_from_zip(data, 2)
    assert name == "Show - 02.srt" and "えっ" in content.decode()
    assert subtitles.pick_from_zip(data, 9) is None


@respx.mock
def test_jimaku_finds_the_episode_through_a_season_zip() -> None:
    api = jimaku.BASE_URL
    respx.get(f"{api}/entries/search").mock(return_value=httpx.Response(200, json=[{"id": 77}]))
    files = respx.get(f"{api}/entries/77/files")
    files.side_effect = [
        httpx.Response(200, json=[]),  # nothing matched the episode filter
        httpx.Response(200, json=[{"name": "Show S1.zip", "url": "https://jimaku.cc/f/1.zip", "size": 1}]),
    ]
    respx.get("https://jimaku.cc/f/1.zip").mock(return_value=httpx.Response(
        200, content=_zip({"Show - 01.srt": SRT, "Show - 02.srt": SRT})))
    with httpx.Client() as client:
        name, cues = jimaku.fetch_episode(client, "key", 154587, 2)
    assert name == "Show - 02.srt" and len(cues) == 2
    assert files.calls[0].request.headers["Authorization"] == "key"


@respx.mock
def test_jimaku_errors_say_what_to_do() -> None:
    with httpx.Client() as client:
        with pytest.raises(jimaku.JimakuError, match="API key"):
            jimaku.fetch_episode(client, "", 1, 1)
        respx.get(f"{jimaku.BASE_URL}/entries/search").mock(return_value=httpx.Response(401))
        with pytest.raises(jimaku.JimakuError, match="didn't accept"):
            jimaku.fetch_episode(client, "bad", 1, 1)


def test_a_line_splits_into_words_with_readings_and_lookup_forms() -> None:
    line = japanese.analyse("ピザを食べたい！")
    words = {t["surface"]: t for t in line["tokens"]}
    assert words["食べ"]["lemma"] == "食べる" and words["食べ"]["reading"] == "たべ"
    assert words["食べ"]["furigana"] and not words["ピザ"]["furigana"]
    assert not words["！"]["lookup"]
    assert line["romaji"] == "Pizza wo tabetai!"


def test_everyday_readings_beat_the_formal_ones() -> None:
    line = japanese.analyse("私の名前")
    assert line["tokens"][0]["reading"] == "わたし"
    assert line["romaji"].lower().startswith("watashi")


# -- lining Japanese up with the English ----------------------------------------

import random  # noqa: E402

from animeplayer.learn import sync  # noqa: E402
from animeplayer.storage.db import Database  # noqa: E402


def test_the_offset_between_two_releases_is_found() -> None:
    random.seed(7)
    english = sorted(random.uniform(0, 1400) for _ in range(300))
    # Same dialogue, 9.8 seconds late, with lines split and merged a little
    # differently: most, not all, start together.
    japanese = [t + 9.8 for t in english[::1] if random.random() < 0.8] + \
               [random.uniform(0, 1400) for _ in range(40)]
    # Within the matching tolerance -- closer than anyone can see.
    assert sync.best_offset(japanese, english) == pytest.approx(-9.8, abs=0.3)


def test_no_offset_is_guessed_for_subtitles_that_dont_match() -> None:
    random.seed(3)
    english = sorted(random.uniform(0, 1400) for _ in range(300))
    unrelated = [random.uniform(0, 1400) for _ in range(300)]
    assert sync.best_offset(unrelated, english) is None


def test_speakers_inline_readings_and_sound_captions_are_separated() -> None:
    line = japanese.analyse("（松村(まつむら)）ああ…")
    assert line["speaker"] == "松村" and line["text"] == "ああ…" and not line["caption"]
    assert japanese.analyse("（松村のうめき声）")["caption"]
    assert japanese.analyse("(カイマン)何だ\n(ニカイドウ)えっ？")["speaker"] == "カイマン / ニカイドウ"
    # A clipped ending (っ) is not a letter in romaji.
    assert japanese.analyse("クソッ てめえ 放せ！")["romaji"] == "Kuso temee hanase!"


def test_saving_the_same_word_from_the_same_line_twice_is_one_save(tmp_path) -> None:
    db = Database(tmp_path / "t.db")
    word = {"word": "放す", "reading": "はなす", "meaning": "to let go", "sentence": "放せ！"}
    first = db.save_word(word)
    assert db.save_word(word) == first
    db.save_word({**word, "sentence": "放してくれ"})
    assert len(db.saved_words()) == 2
    db.delete_saved_word(first)
    assert [w["sentence"] for w in db.saved_words()] == ["放してくれ"]


def test_anki_deck_has_the_words_and_their_audio(tmp_path):
    import sqlite3
    import zipfile
    from animeplayer.learn import anki

    clip = tmp_path / "line-1.mp3"
    clip.write_bytes(b"ID3fake")
    words = [
        {"id": 1, "word": "魔法", "reading": "まほう", "meaning": "magic", "pos": "noun",
         "sentence": "魔法は好きだ", "translation": "I like magic", "title": "Frieren", "episode": 2.0},
        {"id": 2, "word": "旅", "reading": "たび", "meaning": "journey", "pos": "noun",
         "sentence": "旅は終わった", "translation": "", "title": "Frieren", "episode": 1.0},
    ]
    out = tmp_path / "deck.apkg"
    assert anki.build_deck(words, out, audio={1: clip}) == 2

    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        z.extract("collection.anki2", tmp_path)
        media_map = z.read("media").decode()
    assert "line-1.mp3" in media_map
    fields = [r[0] for r in sqlite3.connect(tmp_path / "collection.anki2").execute("select flds from notes")]
    first = next(f for f in fields if f.startswith("魔法"))
    assert "<b>魔法</b>は好きだ" in first and "[sound:line-1.mp3]" in first and "Frieren · episode 2" in first


def test_exporting_again_keeps_the_same_notes(tmp_path):
    from animeplayer.learn import anki
    import genanki
    w = {"id": 1, "word": "旅", "reading": "たび", "meaning": "journey", "sentence": "旅は終わった"}
    assert genanki.guid_for(w["word"], w["sentence"]) == genanki.guid_for("旅", "旅は終わった")
