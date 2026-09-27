import json
import time

import httpx
import pytest
import respx

from animeplayer.anilist import client as client_module
from animeplayer.anilist.client import AniListClient, AniListError, build_authorize_url


def _media(media_id: int, romaji: str) -> dict:
    """One AniList media object with only the fields the client reads."""
    return {
        "id": media_id,
        "title": {"romaji": romaji, "english": None},
        "synonyms": [],
        "coverImage": {"large": None},
        "averageScore": None,
        "genres": [],
        "format": "TV",
        "episodes": None,
        "description": None,
    }



def test_build_authorize_url() -> None:
    url = build_authorize_url("12345")
    assert url == "https://anilist.co/api/v2/oauth/authorize?client_id=12345&response_type=token"


@respx.mock
def test_get_viewer() -> None:
    respx.post("https://graphql.anilist.co").mock(
        return_value=httpx.Response(200, json={"data": {"Viewer": {"id": 7, "name": "supred"}}})
    )
    with httpx.Client() as http_client:
        client = AniListClient(http_client, "token")
        viewer = client.get_viewer()

    assert viewer.id == 7
    assert viewer.name == "supred"


@respx.mock
def test_get_list_collection_parses_entries() -> None:
    respx.post("https://graphql.anilist.co").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "MediaListCollection": {
                        "lists": [
                            {
                                "entries": [
                                    {
                                        "status": "CURRENT",
                                        "progress": 12,
                                        "score": 8.5,
                                        "media": {
                                            "id": 2293,
                                            "title": {"romaji": "Hunter x Hunter", "english": None},
                                            "synonyms": ["HxH"],
                                            "coverImage": {"large": "https://example.com/hxh.jpg"},
                                        },
                                    }
                                ]
                            },
                            {
                                "entries": [
                                    {
                                        "status": "COMPLETED",
                                        "progress": 24,
                                        "score": 9.0,
                                        "media": {
                                            "id": 1,
                                            "title": {"romaji": "Cowboy Bebop", "english": "Cowboy Bebop"},
                                            "synonyms": [],
                                        },
                                    }
                                ]
                            },
                        ]
                    }
                }
            },
        )
    )
    with httpx.Client() as http_client:
        client = AniListClient(http_client, "token")
        entries = client.get_list_collection(user_id=7)

    assert len(entries) == 2
    hxh = next(e for e in entries if e.media_id == 2293)
    assert hxh.status == "CURRENT"
    assert hxh.progress == 12
    assert hxh.title == "Hunter x Hunter"
    assert hxh.cover_url == "https://example.com/hxh.jpg"
    assert "HxH" in hxh.titles
    assert "Hunter x Hunter" in hxh.titles

    bebop = next(e for e in entries if e.media_id == 1)
    assert bebop.cover_url is None


@respx.mock
def test_search_media() -> None:
    respx.post("https://graphql.anilist.co").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "Page": {
                        "media": [
                            {
                                "id": 2293,
                                "title": {"romaji": "Hunter x Hunter", "english": None},
                                "synonyms": [],
                                "coverImage": {"large": "https://example.com/hxh-large.jpg"},
                                "averageScore": 90,
                                "genres": ["Action", "Adventure"],
                                "format": "TV",
                                "episodes": 148,
                                "description": "A boy searches for his father.",
                            }
                        ]
                    }
                }
            },
        )
    )
    with httpx.Client() as http_client:
        client = AniListClient(http_client, "token")
        results = client.search_media("hunter x hunter")

    assert len(results) == 1
    result = results[0]
    assert result.id == 2293
    assert result.title == "Hunter x Hunter"
    assert result.titles == ("Hunter x Hunter",)
    assert result.cover_url == "https://example.com/hxh-large.jpg"
    assert result.average_score == 90
    assert result.genres == ("Action", "Adventure")
    assert result.format == "TV"
    assert result.episodes == 148
    assert result.description == "A boy searches for his father."


@respx.mock
def test_get_media_by_id() -> None:
    respx.post("https://graphql.anilist.co").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "Media": {
                        "id": 2293,
                        "title": {"romaji": "Hunter x Hunter", "english": None},
                        "synonyms": [],
                        "coverImage": {"large": None},
                        "averageScore": None,
                        "genres": [],
                        "format": "TV",
                        "episodes": None,
                        "description": None,
                    }
                }
            },
        )
    )
    with httpx.Client() as http_client:
        client = AniListClient(http_client, "token")
        result = client.get_media_by_id(2293)

    assert result.id == 2293
    assert result.episodes is None
    assert result.genres == ()


@respx.mock
def test_search_by_filters_returns_results_and_has_next_page() -> None:
    respx.post("https://graphql.anilist.co").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "Page": {
                        "pageInfo": {"hasNextPage": True},
                        "media": [
                            {
                                "id": 1,
                                "title": {"romaji": "Romance Anime", "english": None},
                                "synonyms": [],
                                "coverImage": {"large": None},
                                "averageScore": 70,
                                "genres": ["Romance"],
                                "format": "TV",
                                "episodes": 12,
                                "description": None,
                            }
                        ],
                    }
                }
            },
        )
    )
    with httpx.Client() as http_client:
        client = AniListClient(http_client)
        results, has_more = client.search_by_filters(
            "", ["Romance"], ["Isekai"], exclude_genres=["Horror"], exclude_tags=["Gore"], page=2
        )

    assert has_more is True
    assert len(results) == 1
    assert results[0].title == "Romance Anime"

    request_body = respx.calls.last.request.content
    assert b'"notGenres"' in request_body
    assert b'"notTags"' in request_body
    assert b'"page": 2' in request_body or b'"page":2' in request_body


@respx.mock
def test_search_by_filters_no_next_page_when_absent() -> None:
    respx.post("https://graphql.anilist.co").mock(
        return_value=httpx.Response(
            200, json={"data": {"Page": {"pageInfo": {"hasNextPage": False}, "media": []}}}
        )
    )
    with httpx.Client() as http_client:
        client = AniListClient(http_client)
        results, has_more = client.search_by_filters("query", [], [])

    assert results == []
    assert has_more is False


@respx.mock
def test_get_recommendation_sources_splits_sequels_from_similar() -> None:
    respx.post("https://graphql.anilist.co").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "Page": {
                        "media": [
                            {
                                "id": 100,
                                "title": {"romaji": "Show", "english": None},
                                "relations": {
                                    "edges": [
                                        {
                                            "relationType": "SEQUEL",
                                            "node": _media(200, "Show Season 3"),
                                        },
                                        {
                                            "relationType": "PREQUEL",
                                            "node": _media(99, "Show Season 1"),
                                        },
                                    ]
                                },
                                "recommendations": {
                                    "nodes": [
                                        {"rating": 412, "mediaRecommendation": _media(300, "Other Show")},
                                        {"rating": 7, "mediaRecommendation": None},
                                    ]
                                },
                            }
                        ]
                    }
                }
            },
        )
    )
    with httpx.Client() as http_client:
        client = AniListClient(http_client)
        rows = client.get_recommendation_sources([100])

    # The PREQUEL edge is dropped (it is not something to watch next), and so
    # is the recommendation whose media came back null -- AniList returns those
    # for entries that have since been deleted.
    assert [(kind, m.id, because, weight) for kind, m, because, weight in rows] == [
        ("sequel", 200, "Show", 0),
        ("similar", 300, "Show", 412),
    ]


def test_get_recommendation_sources_empty_input_makes_no_request() -> None:
    with httpx.Client() as http_client:
        client = AniListClient(http_client)
        # No respx mock installed: a request here would raise rather than pass.
        assert client.get_recommendation_sources([]) == []


@respx.mock
def test_get_popular_page_returns_results_and_last_page() -> None:
    respx.post("https://graphql.anilist.co").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "Page": {
                        "pageInfo": {"lastPage": 87},
                        "media": [_media(1, "Popular Show")],
                    }
                }
            },
        )
    )
    with httpx.Client() as http_client:
        client = AniListClient(http_client)
        results, last_page = client.get_popular_page(3, ["TV"])

    assert last_page == 87
    assert [m.title for m in results] == ["Popular Show"]


@respx.mock
def test_request_raises_on_graphql_errors() -> None:
    respx.post("https://graphql.anilist.co").mock(
        return_value=httpx.Response(200, json={"errors": [{"message": "Invalid token"}]})
    )
    with httpx.Client() as http_client:
        client = AniListClient(http_client, "bad-token")
        with pytest.raises(AniListError, match="Invalid token"):
            client.get_viewer()


def _relation_media(media_id: int, romaji: str, year: int = 2020) -> dict:
    return {
        "id": media_id,
        "idMal": None,
        "title": {"romaji": romaji, "english": None},
        "synonyms": [],
        "coverImage": {"large": "cover.jpg"},
        "bannerImage": None,
        "averageScore": 80,
        "popularity": 1,
        "genres": [],
        "format": "TV",
        "episodes": 12,
        "description": None,
        "startDate": {"year": year},
        "status": "FINISHED",
    }


def test_get_media_extras_splits_relations_recommendations_and_reviews() -> None:
    payload = {
        "data": {
            "Media": {
                "relations": {
                    "edges": [
                        {"relationType": "SEQUEL", "node": _relation_media(2, "Season 2")},
                        {"relationType": "SOURCE", "node": _relation_media(3, "The Manga")},
                        {"relationType": "PREQUEL", "node": {}},
                    ]
                },
                "recommendations": {
                    "nodes": [
                        {"rating": 90, "mediaRecommendation": _relation_media(4, "Something Else")},
                        {"rating": 5, "mediaRecommendation": None},
                    ]
                },
                "reviews": {
                    "nodes": [
                        {
                            "id": 11,
                            "summary": "  Great follow-up.  ",
                            "score": 88,
                            "rating": 40,
                            "ratingAmount": 50,
                            "user": {"name": "someone"},
                        },
                        # A review with no summary is dropped: the summary is
                        # the only part shown, and the only part that is
                        # reliably spoiler-free.
                        {"id": 12, "summary": "", "score": 10, "rating": 1,
                         "ratingAmount": 1, "user": {"name": "quiet"}},
                    ]
                },
            }
        }
    }
    with respx.mock:
        respx.post(client_module.API_URL).mock(return_value=httpx.Response(200, json=payload))
        with httpx.Client() as http:
            extras = AniListClient(http).get_media_extras(1)

    # The node with no id is skipped rather than producing a broken entry.
    assert [(r.relation_type, r.media.title) for r in extras.relations] == [
        ("SEQUEL", "Season 2"),
        ("SOURCE", "The Manga"),
    ]
    assert [m.title for m in extras.recommendations] == ["Something Else"]
    assert len(extras.reviews) == 1
    assert extras.reviews[0].summary == "Great follow-up."
    assert extras.reviews[0].user == "someone"


def _chain_media(media_id: int, romaji: str, edges: list[tuple[str, int]]) -> dict:
    return {
        "id": media_id,
        "title": {"romaji": romaji, "english": None},
        "format": "TV",
        "episodes": 12,
        "startDate": {"year": 2020},
        "status": "FINISHED",
        "coverImage": {"large": "cover.jpg"},
        "relations": {
            "edges": [
                {"relationType": kind, "node": {"id": other}} for kind, other in edges
            ]
        },
    }


def test_get_watch_order_walks_back_to_the_start_and_forward() -> None:
    """Started from the middle of a trilogy, the chain must come back in story
    order -- not in the order the server happened to mention the entries."""
    chain = {
        1: _chain_media(1, "First", [("SEQUEL", 2)]),
        2: _chain_media(2, "Second", [("PREQUEL", 1), ("SEQUEL", 3)]),
        3: _chain_media(3, "Third", [("PREQUEL", 2)]),
    }

    def respond(request: httpx.Request) -> httpx.Response:
        ids = json.loads(request.content)["variables"]["ids"]
        return httpx.Response(
            200,
            json={"data": {"Page": {"media": [chain[i] for i in ids if i in chain]}}},
        )

    with respx.mock:
        respx.post(client_module.API_URL).mock(side_effect=respond)
        with httpx.Client() as http:
            order = AniListClient(http).get_watch_order(2)

    assert [e.title for e in order] == ["First", "Second", "Third"]


def test_get_watch_order_ignores_side_stories() -> None:
    """A side story or spin-off is related viewing, not a position in the
    watch order -- putting one in the chain is how an OVA gets announced as
    'season 2'."""
    chain = {
        1: _chain_media(1, "Main", [("SIDE_STORY", 9), ("SPIN_OFF", 8), ("SEQUEL", 2)]),
        2: _chain_media(2, "Main 2", [("PREQUEL", 1)]),
    }

    def respond(request: httpx.Request) -> httpx.Response:
        ids = json.loads(request.content)["variables"]["ids"]
        return httpx.Response(
            200,
            json={"data": {"Page": {"media": [chain[i] for i in ids if i in chain]}}},
        )

    with respx.mock:
        respx.post(client_module.API_URL).mock(side_effect=respond)
        with httpx.Client() as http:
            order = AniListClient(http).get_watch_order(1)

    assert [e.title for e in order] == ["Main", "Main 2"]


def _chain_media_full(media_id: int, romaji: str, fmt: str, episodes: int,
                      edges: list[tuple[str, int]]) -> dict:
    return {
        "id": media_id,
        "title": {"romaji": romaji, "english": None},
        "format": fmt,
        "episodes": episodes,
        "startDate": {"year": 2020},
        "status": "FINISHED",
        "coverImage": {"large": "cover.jpg"},
        "relations": {
            "edges": [
                {"relationType": kind, "node": {"id": other}} for kind, other in edges
            ]
        },
    }


def _chain_responder(chain: dict[int, dict]):
    def respond(request: httpx.Request) -> httpx.Response:
        ids = json.loads(request.content)["variables"]["ids"]
        return httpx.Response(
            200,
            json={"data": {"Page": {"media": [chain[i] for i in ids if i in chain]}}},
        )

    return respond


def test_watch_order_drops_an_ova_prequel() -> None:
    """AniList files plenty of side content as a PREQUEL. "Attack on Titan:
    No Regrets" is an OVA, and it turned up as step 1 of Attack on Titan's
    watch order."""
    chain = {
        1: _chain_media_full(1, "Main", "TV", 25, [("PREQUEL", 9), ("SEQUEL", 2)]),
        2: _chain_media_full(2, "Main 2", "TV", 12, [("PREQUEL", 1)]),
        9: _chain_media_full(9, "Side OVA", "OVA", 2, [("SEQUEL", 1)]),
    }
    with respx.mock:
        respx.post(client_module.API_URL).mock(side_effect=_chain_responder(chain))
        with httpx.Client() as http:
            order = AniListClient(http).get_watch_order(1)

    assert [e.title for e in order] == ["Main", "Main 2"]


def test_watch_order_drops_a_one_shot_in_another_format() -> None:
    """The other shape it takes: One Piece's chain began with a
    single-episode ONA prequel to an 1100-episode TV series."""
    chain = {
        1: _chain_media_full(1, "Long Runner", "TV", 1100, [("PREQUEL", 9)]),
        9: _chain_media_full(9, "One Shot", "ONA", 1, [("SEQUEL", 1)]),
    }
    with respx.mock:
        respx.post(client_module.API_URL).mock(side_effect=_chain_responder(chain))
        with httpx.Client() as http:
            order = AniListClient(http).get_watch_order(1)

    assert [e.title for e in order] == ["Long Runner"]


def test_watch_order_keeps_a_movie_that_is_part_of_the_story() -> None:
    """The rule must not swallow real entries: a full-length film between two
    seasons is part of the order, not an aside."""
    chain = {
        1: _chain_media_full(1, "Season 1", "TV", 12, [("SEQUEL", 2)]),
        2: _chain_media_full(2, "The Movie", "MOVIE", 1, [("PREQUEL", 1), ("SEQUEL", 3)]),
        3: _chain_media_full(3, "Season 2", "TV", 12, [("PREQUEL", 2)]),
    }
    with respx.mock:
        respx.post(client_module.API_URL).mock(side_effect=_chain_responder(chain))
        with httpx.Client() as http:
            order = AniListClient(http).get_watch_order(3)

    # The film is a one-episode MOVIE next to a TV show, which is exactly the
    # shape the one-shot rule targets -- so it is trimmed from the *ends*
    # only, and here it sits between two kept entries.
    assert [e.title for e in order] == ["Season 1", "The Movie", "Season 2"]


# -- Rate limiting, caching and 429 handling --------------------------------
#
# AniList serves a 429 once the app goes over its per-minute budget, and the
# user hit one just by moving between Home and Browse a few times. These cover
# the three halves of the fix: don't ask twice for the same thing, wait when
# told to, and say something useful when waiting doesn't help.


@respx.mock
def test_identical_reads_are_served_from_cache() -> None:
    route = respx.post(client_module.API_URL).mock(
        return_value=httpx.Response(200, json={"data": {"GenreCollection": ["Action"]}})
    )
    with httpx.Client() as http:
        client = AniListClient(http)
        assert client.get_genre_collection() == ["Action"]
        assert client.get_genre_collection() == ["Action"]

    # Navigating away and back must not cost a second request.
    assert route.call_count == 1


@respx.mock
def test_a_different_token_does_not_share_a_cache_entry() -> None:
    """One user's list must never be answered out of another's cached read."""
    responses = [
        httpx.Response(200, json={"data": {"Viewer": {"id": 1, "name": "first"}}}),
        httpx.Response(200, json={"data": {"Viewer": {"id": 2, "name": "second"}}}),
    ]
    respx.post(client_module.API_URL).mock(side_effect=responses)
    with httpx.Client() as http:
        assert AniListClient(http, token="a").get_viewer().name == "first"
        assert AniListClient(http, token="b").get_viewer().name == "second"


@pytest.fixture
def fake_clock(monkeypatch):
    """A clock the limiter's waiting can be measured against.

    Both monotonic and sleep have to be faked together. Stubbing sleep alone
    leaves real time standing still while the limiter re-checks whether its
    back-off has elapsed, so it spins on a wall that never comes down -- the
    suite took two minutes on real 429 back-offs before this existed.
    """
    now = [1000.0]
    monkeypatch.setattr(client_module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(client_module.time, "sleep", lambda s: now.__setitem__(0, now[0] + s))
    return now


@respx.mock
def test_a_429_is_retried_after_the_servers_own_delay(fake_clock) -> None:
    started = fake_clock[0]
    respx.post(client_module.API_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, json={"data": {"GenreCollection": ["Action"]}}),
        ]
    )
    with httpx.Client() as http:
        assert AniListClient(http).get_genre_collection() == ["Action"]

    # Waited rather than failed, and waited as long as it was told to rather
    # than for a hardcoded guess of our own.
    assert fake_clock[0] - started >= 2


@respx.mock
def test_a_persistent_429_explains_itself(fake_clock) -> None:
    respx.post(client_module.API_URL).mock(return_value=httpx.Response(429))
    with httpx.Client() as http:
        with pytest.raises(AniListError) as excinfo:
            AniListClient(http).get_genre_collection()

    # The user should be told to wait, not shown a bare HTTP status.
    assert "rate-limiting" in str(excinfo.value)


@respx.mock
def test_a_write_is_never_cached_and_drops_what_was(fake_clock) -> None:
    route = respx.post(client_module.API_URL).mock(
        return_value=httpx.Response(200, json={"data": {"GenreCollection": ["Action"]}})
    )
    with httpx.Client() as http:
        client = AniListClient(http, token="t")
        client.get_genre_collection()
        client.set_list_status(1, "PLANNING")
        # The read after a write must reach the server: the whole point of the
        # write was to change what the read answers.
        client.get_genre_collection()

    assert route.call_count == 3


def test_the_limiter_blocks_once_the_window_is_full(fake_clock) -> None:
    now = fake_clock
    limiter = client_module._RateLimiter(limit=3, window=60.0)
    for _ in range(3):
        limiter.acquire()
    # The fourth has to wait for the first to age out of the window.
    limiter.acquire()
    assert now[0] >= 1060.0


@respx.mock
def test_identical_concurrent_requests_become_one() -> None:
    """Three filter toggles in a second all miss the cache, because none of
    them has come back yet to populate it. Without collapsing them, rapid use
    of the filter panel is one AniList request per click -- measured live at
    three requests for three identical searches, and one after this.
    """
    import threading

    release = threading.Event()

    arrived = threading.Event()

    def responder(_request):
        # Hold the first request open so the others are genuinely in flight.
        arrived.set()
        release.wait(timeout=5)
        return httpx.Response(200, json={"data": {"GenreCollection": ["Action"]}})

    route = respx.post(client_module.API_URL).mock(side_effect=responder)

    results: list[list[str]] = []

    def ask():
        with httpx.Client() as http:
            results.append(AniListClient(http).get_genre_collection())

    leader = threading.Thread(target=ask)
    leader.start()
    # Wait for the leader to actually be mid-request rather than guessing with
    # a sleep, so the followers below are certain to find it in flight.
    assert arrived.wait(timeout=5)

    followers = [threading.Thread(target=ask) for _ in range(2)]
    for thread in followers:
        thread.start()
    # Give the followers a moment to register as waiters before the leader is
    # allowed to answer and clear the in-flight marker.
    time.sleep(0.2)
    release.set()
    for thread in [leader, *followers]:
        thread.join(timeout=10)

    assert route.call_count == 1
    # ...and every caller still got the answer.
    assert results == [["Action"]] * 3


@respx.mock
def test_a_failing_leader_does_not_strand_the_followers() -> None:
    """If the request that others are waiting on fails, they must go and ask
    themselves rather than waiting out the timeout and returning nothing."""
    respx.post(client_module.API_URL).mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(200, json={"data": {"GenreCollection": ["Action"]}}),
        ]
    )
    with httpx.Client() as http:
        client = AniListClient(http)
        with pytest.raises(httpx.HTTPStatusError):
            client.get_genre_collection()
        # The in-flight marker was released, so this is a fresh attempt rather
        # than a wait on something that will never arrive.
        assert client.get_genre_collection() == ["Action"]


def test_the_client_identifies_itself() -> None:
    """AniList asks third-party clients to say who they are, so they can reach
    an app that misbehaves instead of blocking it."""
    assert "AnimePlayer" in client_module.USER_AGENT


@respx.mock
def test_plan_to_watch_never_sends_a_null_progress() -> None:
    """AniList rejects progress: null with a 400 -- which is what broke the
    Plan to Watch button. Leaving progress out is what keeps it untouched."""
    route = respx.post(client_module.API_URL).mock(
        return_value=httpx.Response(200, json={"data": {"SaveMediaListEntry": {"id": 1}}})
    )
    AniListClient(httpx.Client(), "t").set_list_status(21, "PLANNING")
    body = json.loads(route.calls.last.request.content)
    assert "progress" not in body["query"]
    assert "progress" not in body["variables"]


@respx.mock
def test_a_rejected_request_says_why() -> None:
    """A 400's body names the field AniList objected to; showing the user a
    bare "400 Bad Request" instead hides the one useful fact."""
    respx.post(client_module.API_URL).mock(return_value=httpx.Response(400, json={
        "errors": [{"message": "validation", "status": 400,
                    "validation": {"progress": ["The progress must be an integer."]}}],
        "data": None,
    }))
    with pytest.raises(AniListError, match="progress must be an integer"):
        AniListClient(httpx.Client(), "t").set_list_status(21, "PLANNING")


@respx.mock
def test_get_schedule_pages_through_the_week_and_skips_adult() -> None:
    def page(n, items, more):
        return {"data": {"Page": {"pageInfo": {"hasNextPage": more}, "airingSchedules": items}}}

    adult = dict(_media(3, "Adult"), isAdult=True)
    responses = iter([
        httpx.Response(200, json=page(1, [{"episode": 5, "airingAt": 100, "media": dict(_media(1, "A"), isAdult=False)},
                                          {"episode": 1, "airingAt": 110, "media": adult}], True)),
        httpx.Response(200, json=page(2, [{"episode": 12, "airingAt": 200, "media": dict(_media(2, "B"), isAdult=False)}], False)),
    ])
    route = respx.post("https://graphql.anilist.co").mock(side_effect=lambda request: next(responses))
    with httpx.Client() as http_client:
        schedule = AniListClient(http_client).get_schedule(0, 1000)
    assert [(s.media.id, s.episode, s.airing_at) for s in schedule] == [(1, 5, 100), (2, 12, 200)]
    assert route.call_count == 2


def _list_entry(status: str, media_id: int, romaji: str, custom: dict | None = None) -> dict:
    return {"status": status, "progress": 0, "score": 0, "customLists": custom,
            "media": _media(media_id, romaji)}


@respx.mock
def test_get_list_collection_counts_an_anime_in_a_custom_list_once() -> None:
    # A custom list repeats entries that are also in a status list.
    respx.post("https://graphql.anilist.co").mock(return_value=httpx.Response(200, json={"data": {
        "MediaListCollection": {"lists": [
            {"entries": [_list_entry("PLANNING", 1, "Frieren")]},
            {"entries": [_list_entry("PLANNING", 1, "Frieren")]},
        ]}}}))
    client = AniListClient(httpx.Client(), token="t")
    assert [e.media_id for e in client.get_list_collection(7)] == [1]


@respx.mock
def test_get_custom_lists() -> None:
    respx.post("https://graphql.anilist.co").mock(return_value=httpx.Response(200, json={"data": {
        "Viewer": {"mediaListOptions": {"animeList": {"customLists": ["Favourites", "Comfy"]}}},
        "MediaListCollection": {"lists": [
            {"entries": [_list_entry("PLANNING", 1, "Frieren", {"Favourites": True, "Comfy": False}),
                         _list_entry("COMPLETED", 2, "Mushishi", None)]},
            {"entries": [_list_entry("PLANNING", 1, "Frieren", {"Favourites": True, "Comfy": False})]},
        ]}}}))
    lists = AniListClient(httpx.Client(), token="t").get_custom_lists(7)
    assert lists.names == ("Favourites", "Comfy")
    assert lists.entries[1].lists == {"Favourites"} and lists.entries[1].title == "Frieren"
    assert lists.entries[2].lists == frozenset() and lists.entries[2].status == "COMPLETED"


@respx.mock
def test_set_entry_custom_lists_sends_status_only_when_given() -> None:
    route = respx.post("https://graphql.anilist.co").mock(
        return_value=httpx.Response(200, json={"data": {"SaveMediaListEntry": {"id": 1}}}))
    client = AniListClient(httpx.Client(), token="t")
    client.set_entry_custom_lists(5, ["Favourites"], "PLANNING")
    client.set_entry_custom_lists(5, [])
    first, second = (json.loads(c.request.content) for c in route.calls)
    assert first["variables"] == {"mediaId": 5, "names": ["Favourites"], "status": "PLANNING"}
    assert second["variables"] == {"mediaId": 5, "names": []}
    assert "status" not in second["query"]
