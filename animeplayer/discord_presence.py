"""Shows what's playing on the user's Discord profile ("Watching Frieren,
Episode 5, 12:03 left"), through the Discord app running on the same PC.

Discord's local RPC is a socket (a named pipe on Windows) carrying frames of
a little-endian opcode and length followed by JSON: a handshake with the
application's id, then SET_ACTIVITY commands. Small enough to speak directly
rather than pull in a library and an asyncio loop.

Everything runs on one background thread and never blocks or fails the app:
Discord not running, not installed, or closed mid-episode just means nothing
is shown, and the thread tries again a little later.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import sys
import threading
import time
import uuid
from pathlib import Path

_HANDSHAKE, _FRAME, _CLOSE = 0, 1, 2
RETRY_SECONDS = 30


def _socket_paths() -> list[str]:
    """Where a running Discord listens: its usual spot plus the Flatpak and
    Snap ones on Linux, and the named pipes on Windows."""
    if sys.platform == "win32":
        return [rf"\\?\pipe\discord-ipc-{i}" for i in range(10)]
    base = os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"
    folders = [base, f"{base}/app/com.discordapp.Discord", f"{base}/.flatpak/com.discordapp.Discord/xdg-run",
               f"{base}/snap.discord"]
    return [f"{folder}/discord-ipc-{i}" for folder in folders for i in range(10)]


class _Connection:
    def __init__(self, client_id: str) -> None:
        self._client_id = client_id
        self._sock: socket.socket | None = None
        self._pipe = None
        for path in _socket_paths():
            try:
                if sys.platform == "win32":
                    self._pipe = open(path, "r+b", buffering=0)  # noqa: SIM115 -- closed in close()
                else:
                    if not Path(path).exists():
                        continue
                    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    sock.settimeout(5)
                    sock.connect(path)
                    self._sock = sock
                break
            except OSError:
                continue
        if self._sock is None and self._pipe is None:
            raise OSError("Discord isn't running")
        self._send(_HANDSHAKE, {"v": 1, "client_id": client_id})
        self._receive()

    def _write(self, data: bytes) -> None:
        if self._sock is not None:
            self._sock.sendall(data)
        else:
            self._pipe.write(data)

    def _read(self, count: int) -> bytes:
        out = b""
        while len(out) < count:
            chunk = self._sock.recv(count - len(out)) if self._sock is not None else self._pipe.read(count - len(out))
            if not chunk:
                raise OSError("Discord closed the connection")
            out += chunk
        return out

    def _send(self, op: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self._write(struct.pack("<ii", op, len(body)) + body)

    def _receive(self) -> dict:
        op, length = struct.unpack("<ii", self._read(8))
        data = json.loads(self._read(length) or b"{}")
        if op == _CLOSE or data.get("evt") == "ERROR":
            raise OSError(f"Discord refused: {data.get('message') or data.get('data')}")
        return data

    def set_activity(self, activity: dict | None) -> None:
        self._send(_FRAME, {"cmd": "SET_ACTIVITY", "args": {"pid": os.getpid(), "activity": activity},
                            "nonce": str(uuid.uuid4())})
        self._receive()

    def close(self) -> None:
        for handle in (self._sock, self._pipe):
            try:
                if handle is not None:
                    handle.close()
            except OSError:
                pass


def activity_for(title: str, episode: float, position: float, duration: float, paused: bool,
                 poster_url: str = "", now: float | None = None) -> dict:
    """The activity Discord shows. While playing, start/end timestamps make
    Discord draw the elapsed/remaining bar itself; paused, there's no bar."""
    now = time.time() if now is None else now
    activity: dict = {
        "type": 3,  # "Watching"
        "details": title[:128] or "Anime",
        "state": (f"Episode {episode:g}" if episode else "Watching") + (" · Paused" if paused else ""),
        "assets": {"large_image": poster_url or "logo", "large_text": title[:128] or "Anime Player"},
    }
    if not paused and duration > 0:
        start = int(now - position)
        activity["timestamps"] = {"start": start, "end": int(start + duration)}
    return activity


class DiscordPresence:
    """update() from anywhere, as often as you like: only changes that matter
    are sent, from a background thread."""

    def __init__(self, client_id: str) -> None:
        self._client_id = client_id
        self._wanted: dict | None = None
        self._sent: dict | None = None
        self._changed = threading.Event()
        self._enabled = bool(client_id)
        self._thread: threading.Thread | None = None

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled and bool(self._client_id)
        if not self._enabled:
            self.update(None)
        self._changed.set()

    def update(self, activity: dict | None) -> None:
        self._wanted = activity
        if self._thread is None and self._enabled:
            self._thread = threading.Thread(target=self._run, name="discord-presence", daemon=True)
            self._thread.start()
        self._changed.set()

    @staticmethod
    def _worth_sending(old: dict | None, new: dict | None) -> bool:
        """Timestamps drift by a second or two between progress reports;
        only a real seek (or anything else changing) is worth a message."""
        if old is None or new is None:
            return old is not new
        if {k: v for k, v in old.items() if k != "timestamps"} != {k: v for k, v in new.items() if k != "timestamps"}:
            return True
        a, b = old.get("timestamps") or {}, new.get("timestamps") or {}
        return abs(a.get("start", 0) - b.get("start", 0)) > 5

    def _run(self) -> None:
        connection: _Connection | None = None
        while True:
            self._changed.wait(timeout=RETRY_SECONDS)
            self._changed.clear()
            wanted = self._wanted if self._enabled else None
            if not self._worth_sending(self._sent, wanted) and connection is not None:
                continue
            if wanted is None and connection is None:
                self._sent = None
                continue
            try:
                if connection is None:
                    connection = _Connection(self._client_id)
                connection.set_activity(wanted)
                self._sent = wanted
            except (OSError, ValueError, struct.error):
                if connection is not None:
                    connection.close()
                connection = None
                self._sent = None
