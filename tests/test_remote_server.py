import http.client
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from animeplayer.remote.server import RemoteServer


@pytest.fixture
def server(tmp_path):
    commands = []
    fake_apk = tmp_path / "AnimePlayerRemote.apk"
    fake_apk.write_bytes(b"fake apk bytes")
    srv = RemoteServer(
        state_provider=lambda: {"title": "Test Anime", "episode_number": 3, "position": 10.0,
                                 "duration": 100.0, "paused": False, "home": []},
        command_handler=lambda cmd, args: commands.append((cmd, args)),
        port=0,
        apk_path=fake_apk,
    )
    # port=0 would let the OS pick a free port, but ThreadingHTTPServer needs
    # the actual bound port back out -- start() binds it, then read it off
    # the real socket.
    srv._port = 18787
    srv.start()
    srv.commands = commands
    srv.fake_apk_bytes = b"fake apk bytes"
    yield srv
    srv.stop()


@pytest.fixture
def server_no_apk():
    srv = RemoteServer(
        state_provider=lambda: {},
        command_handler=lambda cmd, args: None,
        port=18788,
        apk_path=None,
    )
    srv.start()
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


def test_pairing_calls_on_new_token(tmp_path):
    seen = []
    srv = RemoteServer(
        state_provider=lambda: {},
        command_handler=lambda cmd, args: None,
        port=18789,
        on_new_token=seen.append,
    )
    srv.start()
    try:
        _, pair_data = _post(srv, "/api/pair", {"pin": srv.pin})
        assert seen == [pair_data["token"]]
    finally:
        srv.stop()


def test_preloaded_token_works_without_repairing(tmp_path):
    # A previously-paired phone's saved token should keep working across a PC
    # app restart -- Backend reloads persisted tokens and passes them in here
    # rather than starting every RemoteServer with an empty token set.
    srv = RemoteServer(
        state_provider=lambda: {},
        command_handler=lambda cmd, args: None,
        port=18790,
        initial_tokens={"already-paired-token"},
    )
    srv.start()
    try:
        status, data = _post(
            srv, "/api/command", {"token": "already-paired-token", "cmd": "play_pause"}
        )
        assert data["ok"] is True
    finally:
        srv.stop()


def test_apk_download_serves_file_bytes(server):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/app.apk", timeout=5) as resp:
        assert resp.status == 200
        assert resp.headers["Content-Type"] == "application/vnd.android.package-archive"
        assert resp.read() == server.fake_apk_bytes


def test_apk_download_404s_when_not_built(server_no_apk):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"http://127.0.0.1:{server_no_apk.port}/app.apk", timeout=5)
    assert exc_info.value.code == 404


def test_apk_head_request_reports_full_size_no_body(server):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    try:
        conn.request("HEAD", "/app.apk")
        resp = conn.getresponse()
        assert resp.status == 200
        assert resp.getheader("Content-Length") == str(len(server.fake_apk_bytes))
        assert resp.getheader("Accept-Ranges") == "bytes"
        assert resp.read() == b""
    finally:
        conn.close()


def test_apk_range_request_serves_partial_content(server):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    try:
        conn.request("GET", "/app.apk", headers={"Range": "bytes=5-9"})
        resp = conn.getresponse()
        assert resp.status == 206
        assert resp.getheader("Content-Range") == f"bytes 5-9/{len(server.fake_apk_bytes)}"
        assert resp.read() == server.fake_apk_bytes[5:10]
    finally:
        conn.close()


def test_apk_range_request_beyond_size_is_416(server):
    size = len(server.fake_apk_bytes)
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    try:
        conn.request("GET", "/app.apk", headers={"Range": f"bytes={size + 10}-{size + 20}"})
        resp = conn.getresponse()
        assert resp.status == 416
        resp.read()
    finally:
        conn.close()
