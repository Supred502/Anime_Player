import httpx
import pytest
import respx

from animeplayer.anilist.client import AniListClient, AniListError, build_authorize_url


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
def test_get_sequel_relations_filters_to_sequel_edges() -> None:
    respx.post("https://graphql.anilist.co").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "Page": {
                        "media": [
                            {
                                "id": 100,
                                "relations": {
                                    "edges": [
                                        {
                                            "relationType": "SEQUEL",
                                            "node": {
                                                "id": 200,
                                                "title": {"romaji": "Show Season 3", "english": None},
                                                "synonyms": [],
                                                "coverImage": {"large": None},
                                                "averageScore": None,
                                                "genres": [],
                                                "format": "TV",
                                                "episodes": None,
                                                "description": None,
                                            },
                                        },
                                        {
                                            "relationType": "PREQUEL",
                                            "node": {
                                                "id": 99,
                                                "title": {"romaji": "Show Season 1", "english": None},
                                                "synonyms": [],
                                                "coverImage": {"large": None},
                                                "averageScore": None,
                                                "genres": [],
                                                "format": "TV",
                                                "episodes": None,
                                                "description": None,
                                            },
                                        },
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
        relations = client.get_sequel_relations([100])

    assert list(relations.keys()) == [100]
    assert len(relations[100]) == 1
    assert relations[100][0].id == 200
    assert relations[100][0].title == "Show Season 3"


def test_get_sequel_relations_empty_input_short_circuits() -> None:
    with httpx.Client() as http_client:
        client = AniListClient(http_client)
        assert client.get_sequel_relations([]) == {}


@respx.mock
def test_request_raises_on_graphql_errors() -> None:
    respx.post("https://graphql.anilist.co").mock(
        return_value=httpx.Response(200, json={"errors": [{"message": "Invalid token"}]})
    )
    with httpx.Client() as http_client:
        client = AniListClient(http_client, "bad-token")
        with pytest.raises(AniListError, match="Invalid token"):
            client.get_viewer()
