"""Local HTTP server powering the phone remote control.

Deliberately simple, matching what was actually asked for: pairing is a
4-digit PIN typed once on the phone (no QR code library, no TLS, no
per-request auth beyond a bearer token handed out at pairing time) -- this is
a LAN-only convenience feature, not something exposed to the internet, so
that's an intentional tradeoff, not an oversight.

Runs on a background thread (ThreadingHTTPServer, its own thread separate
from Qt's event loop) so it never blocks the GUI. Everything it learns from
an HTTP request that needs to reach Qt -- a remote button press -- crosses
over via a plain callback function supplied by Backend, which itself emits a
Qt signal; Qt auto-queues that delivery onto the GUI thread the same way the
existing QThreadPool workers already do (see ui/backend.py's _Worker).
"""

from __future__ import annotations

import json
import random
import string
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

_REMOTE_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>Anime Player Remote</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  body {
    margin: 0; font-family: -apple-system, system-ui, sans-serif;
    background: #1d1d1f; color: #f0f0f0; padding: 16px; padding-bottom: 48px;
  }
  h1 { font-size: 18px; margin: 4px 0 12px; opacity: 0.85; }
  .card { background: #2a2a2e; border-radius: 12px; padding: 14px; margin-bottom: 14px; }
  .now-playing { font-size: 15px; }
  .now-playing .title { font-weight: 600; font-size: 17px; margin-bottom: 4px; }
  .now-playing .sub { opacity: 0.7; }
  #pairBox { text-align: center; }
  #pairBox input {
    font-size: 28px; letter-spacing: 6px; text-align: center; width: 140px;
    padding: 10px; border-radius: 8px; border: none; background: #1d1d1f; color: #fff;
  }
  button {
    font-size: 16px; padding: 14px; border-radius: 10px; border: none;
    background: #3a3a3f; color: #fff; font-weight: 600;
  }
  button:active { background: #4e4e55; }
  button.primary { background: #4c8bf5; }
  button.primary:active { background: #3a75dd; }
  .grid3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 8px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
  .dpad { display: grid; grid-template-columns: 1fr 1fr 1fr; grid-template-rows: 1fr 1fr 1fr; gap: 8px; width: 220px; margin: 8px auto; }
  .dpad button { padding: 18px 0; font-size: 20px; }
  .dpad .mid { grid-column: 2; grid-row: 2; background: #4c8bf5; }
  .tabs { display: flex; gap: 8px; margin-bottom: 12px; }
  .tabs button { flex: 1; background: #232326; }
  .tabs button.active { background: #4c8bf5; }
  .list-item {
    display: flex; align-items: center; gap: 10px; padding: 10px; border-radius: 8px; margin-bottom: 6px;
    background: #232326;
  }
  .list-item.selected { outline: 2px solid #4c8bf5; background: #2e3b52; }
  .list-item img { width: 40px; height: 56px; object-fit: cover; border-radius: 4px; background: #111; }
  .list-item .name { font-size: 14px; }
  .hidden { display: none !important; }
  .toast {
    position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);
    background: #000; color: #fff; padding: 8px 16px; border-radius: 20px; opacity: 0; transition: opacity .2s;
    font-size: 13px; pointer-events: none;
  }
</style>
</head>
<body>

<div id="pairBox" class="card">
  <h1>Pair with Anime Player</h1>
  <p style="opacity:.7">Enter the PIN shown on the PC's Settings page.</p>
  <input id="pinInput" inputmode="numeric" maxlength="4" placeholder="0000">
  <div style="margin-top:12px"><button class="primary" onclick="pair()">Connect</button></div>
</div>

<div id="app" class="hidden">
  <div class="card now-playing">
    <div class="title" id="npTitle">Nothing playing</div>
    <div class="sub" id="npSub"></div>
  </div>

  <div class="tabs">
    <button id="tabPlayer" class="active" onclick="showTab('player')">Player</button>
    <button id="tabBrowse" onclick="showTab('browse')">Browse</button>
  </div>

  <div id="playerTab">
    <div class="card">
      <div class="grid3">
        <button onclick="cmd('prev_episode')">⏮ Prev Ep</button>
        <button class="primary" onclick="cmd('play_pause')" id="playPauseBtn">Play/Pause</button>
        <button onclick="cmd('next_episode')">Next Ep ⏭</button>
      </div>
      <div class="grid2">
        <button onclick="cmd('seek', -5)">« 5s</button>
        <button onclick="cmd('seek', 5)">5s »</button>
      </div>
      <div class="grid2">
        <button onclick="cmd('skip_intro')">Skip Intro</button>
        <button onclick="cmd('skip_outro')">Skip Outro</button>
      </div>
      <div class="grid2">
        <button onclick="cmd('seek', -85)">« 85s</button>
        <button onclick="cmd('seek', 85)">85s »</button>
      </div>
      <div class="grid2">
        <button onclick="cmd('volume', -10)">🔉 Vol -</button>
        <button onclick="cmd('volume', 10)">🔊 Vol +</button>
      </div>
    </div>
  </div>

  <div id="browseTab" class="hidden">
    <div class="dpad">
      <div></div><button onclick="moveSelection(-1)">▲</button><div></div>
      <button onclick="moveSelection(-1)" style="visibility:hidden"></button>
      <button class="mid" onclick="selectCurrent()">OK</button>
      <button onclick="moveSelection(1)" style="visibility:hidden"></button>
      <div></div><button onclick="moveSelection(1)">▼</button><div></div>
    </div>
    <div class="card" id="browseList"><div style="opacity:.6">Loading...</div></div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
let token = localStorage.getItem('remoteToken') || null;
let browseItems = [];
let selIndex = 0;

if (token) showApp();

async function pair() {
  const pin = document.getElementById('pinInput').value.trim();
  try {
    const resp = await fetch('/api/pair', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({pin})
    });
    const data = await resp.json();
    if (data.ok) {
      token = data.token;
      localStorage.setItem('remoteToken', token);
      showApp();
    } else {
      toast(data.error || 'Wrong PIN');
    }
  } catch (e) { toast('Could not reach PC'); }
}

function showApp() {
  document.getElementById('pairBox').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  poll();
  setInterval(poll, 2000);
}

function showTab(name) {
  document.getElementById('playerTab').classList.toggle('hidden', name !== 'player');
  document.getElementById('browseTab').classList.toggle('hidden', name !== 'browse');
  document.getElementById('tabPlayer').classList.toggle('active', name === 'player');
  document.getElementById('tabBrowse').classList.toggle('active', name === 'browse');
}

async function cmd(name, args) {
  if (!token) return;
  try {
    const resp = await fetch('/api/command', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({token, cmd: name, args: args === undefined ? null : args})
    });
    const data = await resp.json();
    if (!data.ok) {
      toast(data.error || 'Command failed');
      // A token the server no longer recognizes (e.g. its DB was reset)
      // -- drop it and fall back to the PIN screen instead of silently
      // failing every button press forever.
      if (data.error && data.error.indexOf('Not paired') !== -1) {
        token = null;
        localStorage.removeItem('remoteToken');
        document.getElementById('app').classList.add('hidden');
        document.getElementById('pairBox').classList.remove('hidden');
      }
    }
  } catch (e) { toast('Could not reach PC'); }
}

function fmtTime(s) {
  if (!s || s < 0) s = 0;
  const m = Math.floor(s / 60), sec = Math.floor(s % 60);
  return m + ':' + (sec < 10 ? '0' : '') + sec;
}

async function poll() {
  try {
    const resp = await fetch('/api/state');
    const data = await resp.json();
    if (data.title) {
      document.getElementById('npTitle').textContent = data.title;
      document.getElementById('npSub').textContent =
        'Episode ' + data.episode_number + ' · ' + fmtTime(data.position) + ' / ' + fmtTime(data.duration)
        + (data.paused ? ' · Paused' : '');
    } else {
      document.getElementById('npTitle').textContent = 'Nothing playing';
      document.getElementById('npSub').textContent = '';
    }
    renderBrowse(data.home || []);
  } catch (e) { /* transient network hiccup, ignore -- next poll will retry */ }
}

function renderBrowse(items) {
  browseItems = items;
  const el = document.getElementById('browseList');
  if (items.length === 0) { el.innerHTML = '<div style="opacity:.6">Nothing here yet</div>'; return; }
  el.innerHTML = items.map((it, i) =>
    '<div class="list-item' + (i === selIndex ? ' selected' : '') + '" onclick="selIndex=' + i + ';selectCurrent()">'
    + '<img src="' + (it.poster_url || '') + '">'
    + '<div class="name">' + it.title + '<br><span style="opacity:.6">' + it.subtitle + '</span></div>'
    + '</div>'
  ).join('');
}

function moveSelection(delta) {
  if (browseItems.length === 0) return;
  selIndex = Math.max(0, Math.min(browseItems.length - 1, selIndex + delta));
  renderBrowse(browseItems);
}

function selectCurrent() {
  const item = browseItems[selIndex];
  if (!item) return;
  const arg = item.open_cmd === 'open_anime' ? {id: item.open_arg, title: item.title} : item.open_arg;
  cmd(item.open_cmd, arg);
  toast('Opening ' + item.title + ' on the PC');
}

let toastTimer = null;
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.style.opacity = '1';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.style.opacity = '0'; }, 2000);
}
</script>
</body>
</html>
"""


def _generate_pin() -> str:
    return "".join(random.choices(string.digits, k=4))


class RemoteServer:
    """Owns the HTTP server thread. state_provider/command_handler are plain
    callables supplied by Backend -- this module has no Qt dependency at all,
    keeping it independently testable."""

    def __init__(
        self,
        state_provider: Callable[[], dict[str, Any]],
        command_handler: Callable[[str, Any], None],
        port: int = 8787,
        apk_path: Path | None = None,
        initial_tokens: set[str] | None = None,
        on_new_token: Callable[[str], None] | None = None,
    ) -> None:
        self._state_provider = state_provider
        self._command_handler = command_handler
        self._port = port
        # Pairing tokens are handed back to the caller (Backend persists them
        # to the local DB) and can be preloaded here on the next launch --
        # otherwise every PC-app restart would wipe the in-memory token set
        # and force re-entering the PIN on a phone that already paired once,
        # which is exactly the friction this was built to avoid.
        self._on_new_token = on_new_token
        # Serving the remote app's APK from this same LAN server -- rather
        # than only from the GitHub release -- turned out to matter in
        # practice: a mobile browser downloading straight from GitHub's
        # release-asset redirect chain reported the download as stuck at
        # 100% and never actually installed. A same-origin, single-hop
        # download over the LAN sidesteps that whole class of redirect/CDN
        # quirk. See /app.apk in do_GET below.
        self._apk_path = apk_path
        self.pin = _generate_pin()
        self._tokens: set[str] = set(initial_tokens) if initial_tokens else set()
        self._lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> None:
        if self._httpd is not None:
            return
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # noqa: D401 -- silence default stderr logging
                pass

            def _send_json(self, status: int, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_json_body(self) -> dict:
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0:
                    return {}
                raw = self.rfile.read(length)
                try:
                    return json.loads(raw)
                except ValueError:
                    return {}

            def _serve_apk(self, include_body: bool) -> None:
                # Confirmed live via adb logcat against a real phone: Chromium
                # (Brave)'s download manager reported an internal error
                # ("ADM threw while trying to remove a download... 'ids'
                # can't be null") right around when the download should have
                # finished, and the UI sat stuck at 100%. http.server doesn't
                # implement HEAD at all (a bare BaseHTTPRequestHandler 501s
                # it) and never advertised Range support -- both of which
                # Android's DownloadManager / Chromium commonly use to verify
                # a completed download before finalizing it. Answering HEAD
                # properly and advertising (plus honoring) Accept-Ranges is
                # the standard fix for exactly this "stuck at 100%, never
                # installs" symptom.
                if server._apk_path is None or not server._apk_path.is_file():
                    self._send_json(404, {"error": "APK not built on this machine"})
                    return
                size = server._apk_path.stat().st_size
                range_header = self.headers.get("Range")
                if range_header and range_header.startswith("bytes="):
                    try:
                        start_s, end_s = range_header[len("bytes="):].split("-", 1)
                        start = int(start_s) if start_s else 0
                        end = int(end_s) if end_s else size - 1
                        end = min(end, size - 1)
                    except ValueError:
                        start, end = 0, size - 1
                    if start > end or start >= size:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.end_headers()
                        return
                    chunk_len = end - start + 1
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.send_header("Content-Length", str(chunk_len))
                else:
                    start, end = 0, size - 1
                    self.send_response(200)
                    self.send_header("Content-Length", str(size))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Type", "application/vnd.android.package-archive")
                self.send_header("Content-Disposition", 'attachment; filename="AnimePlayerRemote.apk"')
                self.end_headers()
                if include_body:
                    with server._apk_path.open("rb") as f:
                        f.seek(start)
                        self.wfile.write(f.read(end - start + 1))

            def do_HEAD(self) -> None:  # noqa: N802
                if self.path == "/app.apk":
                    self._serve_apk(include_body=False)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_GET(self) -> None:  # noqa: N802 -- required BaseHTTPRequestHandler name
                if self.path == "/":
                    body = _REMOTE_PAGE.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/api/state":
                    self._send_json(200, server._state_provider())
                elif self.path == "/app.apk":
                    self._serve_apk(include_body=True)
                else:
                    self._send_json(404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                if self.path == "/api/pair":
                    data = self._read_json_body()
                    pin = str(data.get("pin", "")).strip()
                    if pin == server.pin:
                        token = "".join(random.choices(string.ascii_letters + string.digits, k=24))
                        with server._lock:
                            server._tokens.add(token)
                        if server._on_new_token is not None:
                            server._on_new_token(token)
                        self._send_json(200, {"ok": True, "token": token})
                    else:
                        self._send_json(200, {"ok": False, "error": "Wrong PIN"})
                elif self.path == "/api/command":
                    data = self._read_json_body()
                    token = data.get("token")
                    with server._lock:
                        valid = token in server._tokens
                    if not valid:
                        self._send_json(200, {"ok": False, "error": "Not paired -- enter the PIN again"})
                        return
                    server._command_handler(data.get("cmd", ""), data.get("args"))
                    self._send_json(200, {"ok": True})
                else:
                    self._send_json(404, {"error": "not found"})

        self._httpd = ThreadingHTTPServer(("0.0.0.0", self._port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
            self._thread = None
