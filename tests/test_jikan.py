import httpx
import respx

from animeplayer.sources import jikan


@respx.mock
def test_get_filler_episodes_single_page() -> None:
    respx.get("https://api.jikan.moe/v4/anime/21/episodes", params={"page": "1"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "pagination": {"has_next_page": False},
                "data": [
                    {"mal_id": 1, "filler": False},
                    {"mal_id": 2, "filler": True},
                    {"mal_id": 3, "filler": True},
                ],
            },
        )
    )
    with httpx.Client() as client:
        fillers = jikan.get_filler_episodes(21, client, sleep=lambda _s: None)

    assert fillers == {2, 3}


@respx.mock
def test_get_filler_episodes_paginates() -> None:
    respx.get("https://api.jikan.moe/v4/anime/21/episodes", params={"page": "1"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "pagination": {"has_next_page": True},
                "data": [{"mal_id": 1, "filler": False}, {"mal_id": 2, "filler": True}],
            },
        )
    )
    respx.get("https://api.jikan.moe/v4/anime/21/episodes", params={"page": "2"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "pagination": {"has_next_page": False},
                "data": [{"mal_id": 3, "filler": True}],
            },
        )
    )
    with httpx.Client() as client:
        fillers = jikan.get_filler_episodes(21, client, sleep=lambda _s: None)

    assert fillers == {2, 3}


@respx.mock
def test_a_rate_limited_page_is_retried_not_dropped() -> None:
    """One 429 used to lose every page -- One Piece showed no filler at all."""
    route = respx.get("https://api.jikan.moe/v4/anime/21/episodes", params={"page": "1"})
    route.side_effect = [
        httpx.Response(429),
        httpx.Response(200, json={"pagination": {"has_next_page": False},
                                  "data": [{"mal_id": 7, "filler": True}]}),
    ]
    waits = []
    with httpx.Client() as client:
        assert jikan.get_filler_episodes(21, client, sleep=waits.append) == {7}
    assert waits == [1.0]
