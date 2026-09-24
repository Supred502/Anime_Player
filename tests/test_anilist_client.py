import json

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
