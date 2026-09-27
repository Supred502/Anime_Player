import json
import socket
import struct
import threading
import time

from animeplayer import discord_presence as dp


def _fake_discord(path, frames, ready):
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)
    ready.set()
    conn, _ = server.accept()

    def read(n):
        out = b""
        while len(out) < n:
            chunk = conn.recv(n - len(out))
            if not chunk:
                raise OSError
            out += chunk
        return out

    try:
        while True:
            op, length = struct.unpack("<ii", read(8))
            payload = json.loads(read(length))
            frames.append((op, payload))
            reply = json.dumps({"cmd": payload.get("cmd", "DISPATCH"), "evt": "READY" if op == 0 else None,
                                "nonce": payload.get("nonce")}).encode()
            conn.sendall(struct.pack("<ii", 1, len(reply)) + reply)
    except OSError:
        pass


def test_handshake_then_activity(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    frames, ready = [], threading.Event()
    threading.Thread(target=_fake_discord, args=(tmp_path / "discord-ipc-0", frames, ready), daemon=True).start()
    ready.wait(2)

    presence = dp.DiscordPresence("123")
    presence.update(dp.activity_for("Frieren", 5, 60, 1440, False, "https://img/p.jpg", now=1000))
    deadline = time.time() + 3
    while len(frames) < 2 and time.time() < deadline:
        time.sleep(0.05)

    assert frames[0] == (0, {"v": 1, "client_id": "123"})
    activity = frames[1][1]["args"]["activity"]
    assert activity["details"] == "Frieren"
    assert activity["state"] == "Episode 5"
    assert activity["timestamps"] == {"start": 940, "end": 2380}
    assert activity["assets"]["large_image"] == "https://img/p.jpg"


def test_paused_has_no_bar_and_small_drift_is_not_resent():
    paused = dp.activity_for("Frieren", 5, 60, 1440, True, now=1000)
    assert "timestamps" not in paused and paused["state"] == "Episode 5 · Paused"
    a = dp.activity_for("Frieren", 5, 60, 1440, False, now=1000)
    b = dp.activity_for("Frieren", 5, 62, 1440, False, now=1003)   # a normal tick
    c = dp.activity_for("Frieren", 5, 600, 1440, False, now=1003)  # a seek
    assert not dp.DiscordPresence._worth_sending(a, b)
    assert dp.DiscordPresence._worth_sending(a, c)
    assert dp.DiscordPresence._worth_sending(a, paused)


def test_no_discord_is_quietly_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    presence = dp.DiscordPresence("123")
    presence.update(dp.activity_for("Frieren", 5, 60, 1440, False))
    time.sleep(0.3)  # the thread tried, failed, and is waiting to retry
    assert presence._sent is None
