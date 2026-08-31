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
        fillers = jikan.get_filler_episodes(21, client)

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
        fillers = jikan.get_filler_episodes(21, client)

    assert fillers == {2, 3}
