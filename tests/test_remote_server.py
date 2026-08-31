import json
import urllib.request

import pytest

from animeplayer.remote.server import RemoteServer


@pytest.fixture
def server():
    commands = []
    srv = RemoteServer(
        state_provider=lambda: {"title": "Test Anime", "episode_number": 3, "position": 10.0,
                                 "duration": 100.0, "paused": False, "home": []},
        command_handler=lambda cmd, args: commands.append((cmd, args)),
        port=0,
    )
    # port=0 would let the OS pick a free port, but ThreadingHTTPServer needs
    # the actual bound port back out -- start() binds it, then read it off
    # the real socket.
    srv._port = 18787
    srv.start()
    srv.commands = commands
    yield srv
    srv.stop()


def _get(srv, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{srv.port}{path}", timeout=5) as resp:
        return resp.status, json.loads(resp.read())


def _post(srv, path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{srv.port}{path}", data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read())


def test_root_serves_html(server):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/", timeout=5) as resp:
        assert resp.status == 200
        body = resp.read().decode()
        assert "<title>Anime Player Remote</title>" in body


def test_state_endpoint_reflects_provider(server):
    status, data = _get(server, "/api/state")
    assert status == 200
    assert data["title"] == "Test Anime"
    assert data["episode_number"] == 3


def test_pair_with_wrong_pin_fails(server):
    status, data = _post(server, "/api/pair", {"pin": "0000"})
    assert data["ok"] is False


def test_pair_with_correct_pin_returns_token(server):
    status, data = _post(server, "/api/pair", {"pin": server.pin})
    assert data["ok"] is True
    assert data["token"]


def test_command_without_token_rejected(server):
    status, data = _post(server, "/api/command", {"token": "bogus", "cmd": "play_pause"})
    assert data["ok"] is False
    assert server.commands == []


def test_command_with_valid_token_dispatches(server):
    _, pair_data = _post(server, "/api/pair", {"pin": server.pin})
    token = pair_data["token"]
    status, data = _post(server, "/api/command", {"token": token, "cmd": "seek", "args": 5})
    assert data["ok"] is True
    assert server.commands == [("seek", 5)]
