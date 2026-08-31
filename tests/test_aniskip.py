import httpx
import respx

from animeplayer.aniskip.client import get_skip_times


@respx.mock
def test_get_skip_times_parses_op_and_ed() -> None:
    respx.get("https://api.aniskip.com/v2/skip-times/1535/1").mock(
        return_value=httpx.Response(
            200,
            json={
                "found": True,
                "results": [
                    {"skipType": "op", "interval": {"startTime": 10.0, "endTime": 100.0}},
                    {"skipType": "ed", "interval": {"startTime": 1300.0, "endTime": 1380.0}},
                ],
            },
        )
    )
    with httpx.Client() as client:
        times = get_skip_times(1535, 1, client)

    assert times["op"].start == 10.0
    assert times["op"].end == 100.0
    assert times["ed"].start == 1300.0
    assert times["ed"].end == 1380.0


@respx.mock
def test_get_skip_times_not_found_returns_empty() -> None:
    respx.get("https://api.aniskip.com/v2/skip-times/1/1").mock(
        return_value=httpx.Response(200, json={"found": False, "results": []})
    )
    with httpx.Client() as client:
        assert get_skip_times(1, 1, client) == {}


@respx.mock
def test_get_skip_times_server_error_returns_empty() -> None:
    respx.get("https://api.aniskip.com/v2/skip-times/1/1").mock(
        return_value=httpx.Response(500, json={"statusCode": 500, "message": "Internal server error"})
    )
    with httpx.Client() as client:
        assert get_skip_times(1, 1, client) == {}


@respx.mock
def test_get_skip_times_ignores_unknown_skip_types() -> None:
    respx.get("https://api.aniskip.com/v2/skip-times/1/1").mock(
        return_value=httpx.Response(
            200,
            json={
                "found": True,
                "results": [
                    {"skipType": "recap", "interval": {"startTime": 0.0, "endTime": 30.0}},
                    {"skipType": "op", "interval": {"startTime": 30.0, "endTime": 90.0}},
                ],
            },
        )
    )
    with httpx.Client() as client:
        times = get_skip_times(1, 1, client)

    assert list(times.keys()) == ["op"]
