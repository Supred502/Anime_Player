from urllib.parse import parse_qs, urlsplit

from animeplayer.remote import relay
from animeplayer.storage.db import Database


def _target(line: str) -> str:
    return parse_qs(urlsplit(line).query)["u"][0]


def test_segments_point_back_at_the_pc_with_absolute_urls() -> None:
    hosts: set[str] = set()
    text = "#EXTM3U\n#EXTINF:4.0,\nseg_00000.ts\n#EXTINF:4.0,\nhttps://cdn2.example/seg_00001.ts\n"
    out = relay.rewrite_playlist(text, "https://hls.example/v/1080/index.m3u8", "tok", hosts).splitlines()
    assert out[2].startswith("/stream/seg?t=tok&u=")
    assert _target(out[2]) == "https://hls.example/v/1080/seg_00000.ts"
    assert _target(out[4]) == "https://cdn2.example/seg_00001.ts"
    # Segments on another CDN host become fetchable -- and nothing else.
    assert hosts == {"hls.example", "cdn2.example"}


def test_a_master_playlists_variants_are_rewritten_as_playlists() -> None:
    text = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\n1080/index.m3u8\n"
    out = relay.rewrite_playlist(text, "https://hls.example/v/master.m3u8", "tok", set())
    assert "/stream/pl?t=tok" in out


def test_key_uris_are_relayed_too() -> None:
    text = '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n#EXTINF:4,\ns.ts\n'
    out = relay.rewrite_playlist(text, "https://hls.example/v/index.m3u8", "tok", set())
    assert 'URI="/stream/seg?t=tok&u=https%3A%2F%2Fhls.example%2Fv%2Fkey.bin"' in out


def test_the_relay_is_not_an_open_proxy() -> None:
    hosts = {"hls.example"}
    assert relay.allowed("https://hls.example/x.ts", hosts)
    assert not relay.allowed("https://evil.example/x.ts", hosts)
    assert not relay.allowed("file:///etc/passwd", hosts)


def test_show_prefs_remember_audio_and_filler_separately(tmp_path) -> None:
    db = Database(tmp_path / "t.db")
    assert db.get_show_prefs("one-piece-1") == (None, False)
    db.set_show_dub("one-piece-1", True)
    db.set_skip_filler("one-piece-1", True)
    db.set_show_dub("one-piece-1", False)
    assert db.get_show_prefs("one-piece-1") == (False, True)
