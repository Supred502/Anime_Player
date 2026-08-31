import httpx
import pytest
import respx

from animeplayer.sources import anidb_app as src

SEARCH_HTML = """
<div class="anime-grid">
<a href="https://anidb.app/anime/hunter-x-hunter-2293" class="anime-card block group" title="Hunter x Hunter">
  <div class="relative overflow-hidden rounded-xl" style="aspect-ratio:2/3">
    <img src="https://cdn.xlsbox.com/poster/small/1782735600/2293.jpg" alt="Hunter x Hunter" loading="lazy">
    <span class="badge badge-orange text-[9px]">TV</span>
    <span class="badge badge-gray flex items-center gap-0.5 text-[9px]">
      <svg class="w-2.5 h-2.5"></svg> 8.0 </span>
  </div>
  <p class="text-xs text-faint">Hunter x Hunter</p>
</a>
</div>
"""

EPISODES_JSON = {
    "episodes": [
        {"id": 50877, "number": 1, "number2": None, "filler": False},
        {"id": 50878, "number": 2, "number2": None, "filler": True},
    ]
}

LANGUAGES_JSON = {
    "languages": [
        {"code": "eng", "name": "English", "embed_url": "https://anidb.app/embed/eng-token"},
        {"code": "jpn", "name": "Japanese", "embed_url": "https://anidb.app/embed/jpn-token"},
    ]
}

EMBED_HTML = "<script>var config = { file: 'https://hls.anidb.app/stream/token/master.m3u8' };</script>"

MASTER_PLAYLIST = """#EXTM3U
#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=787214,RESOLUTION=1440x1080,CODECS="avc1.640033,mp4a.40.29"
https://hls.anidb.app/stream/token/index-f1-v1-a1.m3u8
#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=434190,RESOLUTION=960x720,CODECS="avc1.640033,mp4a.40.29"
https://hls.anidb.app/stream/token/index-f2-v1-a1.m3u8
#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=190330,RESOLUTION=480x360,CODECS="avc1.640033,mp4a.40.29"
https://hls.anidb.app/stream/token/index-f3-v1-a1.m3u8

#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=80154,RESOLUTION=1440x1080,URI="https://hls.anidb.app/stream/token/iframes-f1-v1-a1.m3u8"
"""


@respx.mock
def test_search_parses_results() -> None:
    respx.get(src.SEARCH_URL).mock(return_value=httpx.Response(200, text=SEARCH_HTML))
    with httpx.Client() as client:
        results = src.search("hunter x hunter", client)

    assert len(results) == 1
    result = results[0]
    assert result.slug_id == "hunter-x-hunter-2293"
    assert result.numeric_id == "2293"
    assert result.title == "Hunter x Hunter"
    assert result.kind == "TV"
    assert result.rating == "8.0"


@respx.mock
def test_get_episodes_parses_json() -> None:
    respx.get(src.EPISODES_URL_TEMPLATE.format(numeric_id="2293")).mock(
        return_value=httpx.Response(200, json=EPISODES_JSON)
    )
    with httpx.Client() as client:
        episodes = src.get_episodes("2293", client)

    assert episodes == [
        src.Episode(episode_id=50877, number=1, filler=False),
        src.Episode(episode_id=50878, number=2, filler=True),
    ]


@respx.mock
def test_resolve_stream_returns_master_and_variants() -> None:
    respx.get(src.LANGUAGES_URL_TEMPLATE.format(episode_id=50877)).mock(
        return_value=httpx.Response(200, json=LANGUAGES_JSON)
    )
    respx.get("https://anidb.app/embed/jpn-token").mock(return_value=httpx.Response(200, text=EMBED_HTML))
    respx.get("https://hls.anidb.app/stream/token/master.m3u8").mock(
        return_value=httpx.Response(200, text=MASTER_PLAYLIST)
    )

    with httpx.Client() as client:
        info = src.resolve_stream(50877, client)

    assert info.master_url == "https://hls.anidb.app/stream/token/master.m3u8"
    assert [v.resolution for v in info.variants] == ["1080p", "720p", "360p"]
    assert info.variants[0].bandwidth == 787214
    assert info.variants[0].url.endswith("index-f1-v1-a1.m3u8")


@respx.mock
def test_resolve_stream_dub_selects_english_track() -> None:
    respx.get(src.LANGUAGES_URL_TEMPLATE.format(episode_id=50877)).mock(
        return_value=httpx.Response(200, json=LANGUAGES_JSON)
    )
    respx.get("https://anidb.app/embed/eng-token").mock(return_value=httpx.Response(200, text=EMBED_HTML))
    respx.get("https://hls.anidb.app/stream/token/master.m3u8").mock(
        return_value=httpx.Response(200, text=MASTER_PLAYLIST)
    )

    with httpx.Client() as client:
        info = src.resolve_stream(50877, client, dub=True)

    assert info.master_url == "https://hls.anidb.app/stream/token/master.m3u8"


@respx.mock
def test_resolve_stream_raises_when_language_missing() -> None:
    respx.get(src.LANGUAGES_URL_TEMPLATE.format(episode_id=999)).mock(
        return_value=httpx.Response(
            200, json={"languages": [{"code": "eng", "embed_url": "https://anidb.app/embed/x"}]}
        )
    )
    with httpx.Client() as client, pytest.raises(src.NoStreamFoundError):
        src.resolve_stream(999, client, dub=False)


@respx.mock
def test_search_raises_on_cloudflare_challenge() -> None:
    respx.get(src.SEARCH_URL).mock(
        return_value=httpx.Response(200, text="<html><body>Just a moment...</body></html>")
    )
    with httpx.Client() as client, pytest.raises(src.CloudflareBlockedError):
        src.search("anything", client)
