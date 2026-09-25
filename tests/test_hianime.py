"""Fixtures here are trimmed from real hianime.at / ZokoAnime responses
captured while writing sources/hianime.py, not invented -- the parsers lean on
attribute order and exact class names, so hand-written markup would pass while
the real page failed."""

import base64
import json

import httpx
import pytest
import respx

from animeplayer.sources import hianime as src

SEARCH_HTML = """
<div class="film_list-wrap">
    <div class="flw-item flw-item-big">
    <div class="film-poster">
                <div class="tick ltr">
                        <div class="tick-item tick-sub"><i class="fas fa-closed-captioning mr-1"></i>12</div>
                                    <div class="tick-item tick-dub"><i class="fas fa-microphone mr-1"></i>12</div>
                                    <div class="tick-item tick-eps">12</div>
                    </div>
        <img src="https://cdn.example.co/thumbnail/dc912a25.jpg"
            class="film-poster-img"
            alt="Dorohedoro"
            loading="lazy"
            decoding="async">
        <a href="https://hianime.at/watch/dorohedoro-2691"
            class="film-poster-ahref item-qtip"
            title="Dorohedoro"
            data-id="2691">
        </a>
    </div>
    <div class="film-detail">
        <h3 class="film-name">
            <a href="https://hianime.at/dorohedoro-2691"
                title="Dorohedoro"
                class="dynamic-name"
                data-jname="Dorohedoro">
                Dorohedoro
            </a>
        </h3>
        <div class="fd-infor">
            <span class="fdi-item">TV</span>
                        <span class="dot"></span>
            <span class="fdi-item fdi-duration">23m</span>
                    </div>
    </div>
</div>
    <div class="flw-item flw-item-big">
    <div class="film-poster">
                <div class="tick ltr">
                        <div class="tick-item tick-sub"><i class="fas fa-closed-captioning mr-1"></i>6</div>
                                    <div class="tick-item tick-eps">6</div>
                    </div>
        <img src="https://cdn.example.co/thumbnail/8a50bae2.jpg"
            class="film-poster-img"
            alt="Ma no Omake">
        <a href="https://hianime.at/watch/dorohedoro-ma-no-omake-2692"
            class="film-poster-ahref item-qtip"
            title="Dorohedoro: Ma no Omake"
            data-id="2692">
        </a>
    </div>
    <div class="film-detail">
        <h3 class="film-name">
            <a href="https://hianime.at/dorohedoro-ma-no-omake-2692"
                title="Dorohedoro: Ma no Omake"
                class="dynamic-name">
                Dorohedoro: Ma no Omake
            </a>
        </h3>
        <div class="fd-infor">
            <span class="fdi-item">SPECIAL</span>
            <span class="fdi-item fdi-duration">30m</span>
        </div>
    </div>
</div>
<div id="main-sidebar">
    <div class="flw-item flw-item-big">
    <div class="film-detail">
        <h3 class="film-name">
            <a href="https://hianime.at/one-piece-100" title="ONE PIECE" class="dynamic-name">ONE PIECE</a>
        </h3>
    </div>
</div>
</div>
"""

EPISODES_JSON = {
    "status": True,
    "totalItems": 1,
    "html": (
        '<div class="ss-list">'
        '<a title="Night of the Hunter" class="ssl-item ep-item" data-number="1" '
        'data-id="35826" href="https:\\/\\/hianime.at\\/watch\\/dorohedoro-2691?ep=35826">'
        '<div class="ssli-order">1<\\/div><\\/a>'
        '<a title="Episode 2" class="ssl-item ep-item" data-number="2" '
        'data-id="35827" href="https:\\/\\/hianime.at\\/watch\\/dorohedoro-2691?ep=35827">'
        '<div class="ssli-order">2<\\/div><\\/a>'
    ),
}

SUB_EMBED = "https://zokoanime.video/stream/mal/38668/1/sub"
DUB_EMBED = "https://zokoanime.video/stream/mal/38668/1/dub"


def _hash(url: str) -> str:
    return base64.b64encode(url.encode()).decode()


SERVERS_JSON = {
    "status": True,
    "html": (
        '<div class="ps_-block servers-sub"><div class="ps__-list">'
        f'<div class="item server-item" data-type="sub" data-server-name="ZokoAnime" data-hash="{_hash(SUB_EMBED)}">'
        '<a href="javascript:;" class="btn">ZokoAnime</a></div>'
        '<div class="item server-item" data-type="sub" data-server-name="HD-1" data-hash="b3RoZXI=">'
        '<a href="javascript:;" class="btn">HD-1</a></div>'
        '</div></div>'
        '<div class="ps_-block servers-dub"><div class="ps__-list">'
        f'<div class="item server-item" data-type="dub" data-server-name="ZokoAnime" data-hash="{_hash(DUB_EMBED)}">'
        '<a href="javascript:;" class="btn">ZokoAnime</a></div>'
        '</div></div>'
    ),
}

SUB_ONLY_SERVERS_JSON = {
    "status": True,
    "html": (
        '<div class="ps_-block servers-sub"><div class="ps__-list">'
        f'<div class="item server-item" data-type="sub" data-server-name="ZokoAnime" data-hash="{_hash(SUB_EMBED)}">'
        '<a href="javascript:;" class="btn">ZokoAnime</a></div>'
        '</div></div>'
    ),
}

MASTER_URL = "https://hls2.example.uk/v/abc/def/master.m3u8"

PLAYER_CONFIG = {
    "src": MASTER_URL,
    "subtitles": [
        {"lang": "es", "label": "Spanish", "default": False, "src": "https://hls2.example.uk/v/abc/def/subs/es.vtt"},
        {"lang": "en", "label": "English", "default": True, "src": "https://hls2.example.uk/v/abc/def/subs/en.vtt"},
    ],
    "skip": {"intro": {"start": 143, "end": 233}, "outro": {"start": 1316, "end": 1405}},
}

MASTER_PLAYLIST = """#EXTM3U
#EXT-X-VERSION:4
#EXT-X-STREAM-INF:BANDWIDTH=1500000,RESOLUTION=854x480
480/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=5300000,RESOLUTION=1920x1080
1080/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1280x720
720/index.m3u8
"""


def _obfuscate(config: dict) -> str:
    """Inverse of src._deobfuscate -- XOR is symmetric, so this is the same op."""
    raw = json.dumps(config).encode()
    key = src._EMBED_XOR_KEY
    return base64.b64encode(bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))).decode()


def _embed_html(config: dict = PLAYER_CONFIG) -> str:
    return f'<script>window.__P="{_obfuscate(config)}";</script>'


@pytest.fixture
def client():
    with httpx.Client(follow_redirects=True) as c:
        yield c


@respx.mock
def test_search_parses_cards(client) -> None:
    respx.get(src.SEARCH_URL).mock(return_value=httpx.Response(200, text=SEARCH_HTML))

    results = src.search("Dorohedoro", client)

    assert [r.slug_id for r in results] == ["dorohedoro-2691", "dorohedoro-ma-no-omake-2692"]
    first = results[0]
    assert first.numeric_id == "2691"
    assert first.title == "Dorohedoro"
    assert first.poster_url == "https://cdn.example.co/thumbnail/dc912a25.jpg"
    assert first.kind == "TV"
    assert first.duration == "23m"
    assert (first.sub_count, first.dub_count) == (12, 12)


@respx.mock
def test_search_ignores_the_sidebar_and_marks_sub_only_entries(client) -> None:
    """The "top 10" sidebar repeats the same card markup, so an unbounded
    parse duplicates results and invents matches the user didn't search for."""
    respx.get(src.SEARCH_URL).mock(return_value=httpx.Response(200, text=SEARCH_HTML))

    results = src.search("Dorohedoro", client)

    assert all(r.title != "ONE PIECE" for r in results)
    assert results[1].dub_count == 0


@respx.mock
def test_get_episodes_parses_the_embedded_html(client) -> None:
    respx.get(src.EPISODES_URL_TEMPLATE.format(numeric_id="2691")).mock(
        return_value=httpx.Response(200, json=EPISODES_JSON)
    )

    episodes = src.get_episodes("dorohedoro-2691", client)

    assert [(e.episode_id, e.number) for e in episodes] == [(35826, 1.0), (35827, 2.0)]
    assert episodes[0].title == "Night of the Hunter"


@respx.mock
def test_get_episodes_rejects_an_id_belonging_to_another_anime(client) -> None:
    """The endpoint answers for any number it knows, so a stale id from a
    different backend returns an unrelated show's episodes rather than an
    error -- confirmed live, where the old backend's "one-piece-3880" came
    back as High School DxD Hero. The slug in each episode link is the only
    thing that catches it."""
    respx.get(src.EPISODES_URL_TEMPLATE.format(numeric_id="2691")).mock(
        return_value=httpx.Response(200, json=EPISODES_JSON)
    )

    assert src.get_episodes("some-other-anime-2691", client) == []


def _mock_stream(servers=SERVERS_JSON, embed=None):
    respx.get(src.SERVERS_URL).mock(return_value=httpx.Response(200, json=servers))
    respx.get(SUB_EMBED).mock(return_value=httpx.Response(200, text=embed or _embed_html()))
    respx.get(DUB_EMBED).mock(return_value=httpx.Response(200, text=embed or _embed_html()))
    respx.get(MASTER_URL).mock(return_value=httpx.Response(200, text=MASTER_PLAYLIST))


@respx.mock
def test_resolve_stream_returns_everything_playback_needs(client) -> None:
    _mock_stream()

    info = src.resolve_stream(35826, client)

    assert info.master_url == MASTER_URL
    # The stream host 403s playlist requests without this, so it has to be the
    # embed's *origin*, not the full embed URL.
    assert info.referer == "https://zokoanime.video/"
    assert info.subtitle_url == "https://hls2.example.uk/v/abc/def/subs/en.vtt"
    assert info.mal_id == 38668
    assert info.skip_intro == (143.0, 233.0)
    assert info.skip_outro == (1316.0, 1405.0)


@respx.mock
def test_resolve_stream_sorts_variants_best_first_and_absolutizes_urls(client) -> None:
    _mock_stream()

    info = src.resolve_stream(35826, client)

    assert [v.resolution for v in info.variants] == ["1080p", "720p", "480p"]
    assert info.variants[0].url == "https://hls2.example.uk/v/abc/def/1080/index.m3u8"


@respx.mock
def test_resolve_source_picks_the_requested_audio_track(client) -> None:
    _mock_stream()

    assert src.resolve_source(35826, client, dub=True).mal_id == 38668
    assert respx.calls.last.request.url == DUB_EMBED


@respx.mock
def test_resolve_source_reports_a_missing_dub_specifically(client) -> None:
    _mock_stream(servers=SUB_ONLY_SERVERS_JSON)

    with pytest.raises(src.NoStreamFoundError, match="dubbed"):
        src.resolve_source(35826, client, dub=True)


@respx.mock
def test_resolve_source_raises_when_the_config_is_missing(client) -> None:
    _mock_stream(embed="<script>var nothing = 1;</script>")

    with pytest.raises(src.NoStreamFoundError):
        src.resolve_source(35826, client)


@respx.mock
def test_skip_times_are_dropped_when_the_range_is_empty(client) -> None:
    _mock_stream(embed=_embed_html({**PLAYER_CONFIG, "skip": {"intro": {"start": 0, "end": 0}}}))

    info = src.resolve_source(35826, client)

    assert info.skip_intro is None
    assert info.skip_outro is None


@respx.mock
def test_maintenance_page_is_reported_as_an_outage(client) -> None:
    """The previous backend died behind exactly this: a site-wide 503
    maintenance page on every path, which surfaced as a raw httpx error
    string in the UI."""
    respx.get(src.SEARCH_URL).mock(
        return_value=httpx.Response(503, text="<title>Under Maintenance</title><h1>Under maintenance</h1>")
    )

    with pytest.raises(src.SourceUnavailableError):
        src.search("Dorohedoro", client)


@respx.mock
def test_cloudflare_challenge_is_reported_distinctly(client) -> None:
    respx.get(src.SEARCH_URL).mock(
        return_value=httpx.Response(200, text="<title>Just a moment...</title>")
    )

    with pytest.raises(src.CloudflareBlockedError):
        src.search("Dorohedoro", client)


def _anime_page(stats: str) -> str:
    card = '<div class="tick-item tick-sub"><i></i>99</div><div class="tick-item tick-dub"><i></i>77</div>'
    return ('<div class="anisc-detail"><h2 class="film-name">Show</h2>'
            f'<div class="film-stats"><div class="tick">{stats}</div></div>'
            '<div class="film-description">About it.</div></div>'
            f'<div class="recommendations">{card}{card}</div>')


@respx.mock
def test_audio_counts_come_from_the_header_not_the_cards_below_it() -> None:
    respx.get(f"{src.BASE_URL}/one-piece-1").mock(return_value=httpx.Response(200, text=_anime_page(
        '<div class="tick-item tick-sub"> <i></i>1179 </div><div class="tick-item tick-dub"> <i></i>1155 </div>'
    )))
    with httpx.Client() as client:
        assert src.get_audio_counts("one-piece-1", client) == (1179, 1155)


@respx.mock
def test_a_show_with_no_dub_tick_has_no_dub() -> None:
    """The recommendation cards further down do have dub ticks -- reading
    past the header would report one of theirs."""
    respx.get(f"{src.BASE_URL}/sub-only-5").mock(return_value=httpx.Response(200, text=_anime_page(
        '<div class="tick-item tick-sub"><i></i>13</div>'
    )))
    with httpx.Client() as client:
        assert src.get_audio_counts("sub-only-5", client) == (13, 0)
