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

import hmac
import json
import secrets
import string
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

import httpx

from animeplayer.remote import relay

_REMOTE_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>Anime Player Remote</title>
<style>
  :root { color-scheme: dark; --accent: #4c8bf5; --accent-press: #3a75dd; --accent-soft: #2e3b52; }
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
  button.primary { background: var(--accent); }
  button.primary:active { background: var(--accent-press); }
  .grid3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 8px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
  .grid1 { display: grid; grid-template-columns: 1fr; gap: 8px; margin-bottom: 8px; }
  .grid4 { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 8px; }
  button.big { padding: 20px; font-size: 18px; }
  .dpad { display: grid; grid-template-columns: 1fr 1fr 1fr; grid-template-rows: 1fr 1fr 1fr; gap: 8px; width: 220px; margin: 8px auto; }
  .dpad button { padding: 18px 0; font-size: 20px; }
  .dpad .mid { grid-column: 2; grid-row: 2; background: var(--accent); }
  .tabs { display: flex; gap: 8px; margin-bottom: 12px; }
  .tabs button { flex: 1; background: #232326; }
  .tabs button.active { background: var(--accent); }
  .list-item {
    display: flex; align-items: center; gap: 10px; padding: 10px; border-radius: 8px; margin-bottom: 6px;
    background: #232326;
  }
  .list-item.selected { outline: 2px solid var(--accent); background: var(--accent-soft); }
  .list-item img { width: 40px; height: 56px; object-fit: cover; border-radius: 4px; background: #111; }
  .list-item .name { font-size: 14px; }
  .hidden { display: none !important; }
  input.search {
    width: 100%; font-size: 16px; padding: 12px; border-radius: 10px; border: none;
    background: #2a2a2e; color: #fff; margin-bottom: 10px;
  }
  .section-title { font-size: 13px; opacity: .6; margin: 12px 0 6px; text-transform: uppercase; letter-spacing: .5px; }
  .ep-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(56px, 1fr)); gap: 6px; }
  .ep-grid button { padding: 12px 0; font-size: 15px; }
  .ep-grid button.resume { outline: 2px solid var(--accent); }
  .ep-grid button.filler { background: #4a3a22; }
  .seg { display: flex; gap: 0; margin: 8px 0; }
  .seg button { flex: 1; border-radius: 0; background: #232326; }
  .seg button:first-child { border-radius: 10px 0 0 10px; }
  .seg button:last-child { border-radius: 0 10px 10px 0; }
  .seg button.active { background: var(--accent); }
  #watch { position: fixed; inset: 0; background: #000; z-index: 10; display: flex; flex-direction: column; }
  #watch video { flex: 1; width: 100%; background: #000; }
  #watch .bar { display: flex; gap: 8px; padding: 10px; background: #111; }
  #watch .bar button { flex: 1; }
  .toast {
    position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);
    background: #000; color: #fff; padding: 8px 16px; border-radius: 20px; opacity: 0; transition: opacity .2s;
    font-size: 13px; pointer-events: none;
  }
</style>
</head>
<body>

<div id="updateBanner" class="card hidden">
  <div style="margin-bottom:10px">A newer version of the remote app is on your PC.</div>
  <button class="primary" style="width:100%" onclick="getUpdate()">Update the app</button>
</div>

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
    <div class="grid1" id="phoneRow">
      <button class="primary big" onclick="watchOnPhone()">📱 Continue on phone</button>
    </div>
    <div class="card">
      <div class="grid1">
        <button class="primary big" onclick="cmd('play_pause')" id="playPauseBtn">Play / Pause</button>
      </div>
      <div class="grid2">
        <button onclick="cmd('prev_episode')">⏮ Previous episode</button>
        <button onclick="cmd('next_episode')">Next episode ⏭</button>
      </div>
      <div class="grid2">
        <button onclick="cmd('skip_intro')">Skip Intro</button>
        <button onclick="cmd('skip_outro')">Skip Outro</button>
      </div>
      <div class="grid4">
        <button onclick="cmd('seek', -10)">« 10s</button>
        <button onclick="cmd('seek', -5)">« 5s</button>
        <button onclick="cmd('seek', 5)">5s »</button>
        <button onclick="cmd('seek', 30)">30s »</button>
      </div>
      <div class="grid2">
        <button onclick="cmd('volume', -10)">🔉 Vol -</button>
        <button onclick="cmd('volume', 10)">🔊 Vol +</button>
      </div>
    </div>
  </div>

  <div id="browseTab" class="hidden">
    <div id="browseHome">
      <input class="search" id="searchBox" type="search" placeholder="Search anime…"
             onkeydown="if (event.key === 'Enter') search()">
      <div id="searchResults"></div>
      <div class="section-title">Your shows</div>
      <div id="browseList"><div style="opacity:.6">Loading...</div></div>
    </div>
    <div id="showView" class="hidden">
      <button onclick="closeShow()">‹ Back</button>
      <h1 id="showTitle" style="margin-top:12px"></h1>
      <div class="seg">
        <button id="segSub" onclick="setAudio(false)">Sub</button>
        <button id="segDub" onclick="setAudio(true)">Dub</button>
      </div>
      <div id="showInfo" style="opacity:.7; font-size:13px; margin-bottom:8px"></div>
      <div class="ep-grid" id="episodes"></div>
    </div>
  </div>
</div>

<div id="watch" class="hidden">
  <video id="phoneVideo" controls playsinline autoplay></video>
  <div class="bar">
    <button class="primary" onclick="backToPc()">🖥 Back to PC</button>
    <button onclick="stopPhone()">Close</button>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
// The PC's accent colour and the remote app it carries (/api/info). Inside
// the Android app, `AnimePlayerApp` is that app (see MainActivity's Bridge):
// it takes the colour for its own bar, and says its version, so a newer one
// can be offered. 1.0 had no bridge: a WebView without it is that version.
const APP = window.AnimePlayerApp;
function shade(hex, f) {
  const n = parseInt(hex.slice(1), 16);
  const c = [n >> 16, (n >> 8) & 255, n & 255].map((v) => Math.max(0, Math.min(255, Math.round(f < 0 ? v * (1 + f) : v + (255 - v) * f))));
  return '#' + c.map((v) => v.toString(16).padStart(2, '0')).join('');
}
function mix(hex, base, t) {
  const a = parseInt(hex.slice(1), 16), b = parseInt(base.slice(1), 16);
  const c = [16, 8, 0].map((s) => Math.round(((a >> s) & 255) * t + ((b >> s) & 255) * (1 - t)));
  return '#' + c.map((v) => v.toString(16).padStart(2, '0')).join('');
}
async function loadInfo() {
  try {
    const info = await (await fetch('/api/info')).json();
    if (info.accent && /^#[0-9a-fA-F]{6}$/.test(info.accent)) {
      const root = document.documentElement.style;
      root.setProperty('--accent', info.accent);
      root.setProperty('--accent-press', shade(info.accent, -0.15));
      root.setProperty('--accent-soft', mix(info.accent, '#232326', 0.3));
      if (APP && APP.setTheme) APP.setTheme(info.accent);
    }
    const inApp = !!APP || /; wv\)/.test(navigator.userAgent);
    const have = APP && APP.version ? APP.version() : 1;
    document.getElementById('updateBanner').classList.toggle('hidden',
      !(inApp && info.apk && info.app_version > have));
  } catch (e) { /* an older PC app: no colours, no update check */ }
}
function getUpdate() {
  const url = location.origin + '/app.apk';
  if (APP && APP.openExternal) APP.openExternal(url); else location.href = url;
}
loadInfo();
setInterval(loadInfo, 30000);

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
    const resp = await fetch('/api/state?t=' + encodeURIComponent(token));
    if (resp.status === 403) {
      // The PC no longer knows this phone: back to the PIN.
      token = null;
      localStorage.removeItem('remoteToken');
      location.reload();
      return;
    }
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

function esc(text) {
  return String(text == null ? '' : text).replace(/[&<>"']/g,
    (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}

function card(item, onclick) {
  return '<div class="list-item" onclick="' + onclick + '">'
    + '<img src="' + esc(item.poster_url || '') + '">'
    + '<div class="name">' + esc(item.title) + '<br><span style="opacity:.6">'
    + esc(item.subtitle || '') + '</span></div></div>';
}

function renderBrowse(items) {
  const signature = JSON.stringify(items.map((it) => it.title + it.subtitle));
  if (signature === renderBrowse.last) return;   // polled every 2s; don't redraw for nothing
  renderBrowse.last = signature;
  browseItems = items;
  const el = document.getElementById('browseList');
  if (items.length === 0) { el.innerHTML = '<div style="opacity:.6">Nothing here yet</div>'; return; }
  el.innerHTML = items.map((it, i) => card(it, 'openHomeItem(' + i + ')')).join('');
}

// Shows played on the PC have a source slug, so their episodes can be listed
// right here. AniList-only ones still open on the PC, which finds them.
function openHomeItem(i) {
  const item = browseItems[i];
  if (!item) return;
  if (item.open_cmd === 'open_continue_watching') {
    openShow({slug_id: item.open_arg, numeric_id: item.open_arg.split('-').pop(),
              title: item.title, poster_url: item.poster_url});
  } else {
    cmd(item.open_cmd, {id: item.open_arg, title: item.title});
    toast('Opening ' + item.title + ' on the PC');
  }
}

let searchResults = [];
async function search() {
  const q = document.getElementById('searchBox').value.trim();
  const el = document.getElementById('searchResults');
  if (!q) { el.innerHTML = ''; return; }
  el.innerHTML = '<div style="opacity:.6">Searching…</div>';
  try {
    const data = await (await fetch('/api/search?t=' + encodeURIComponent(token) + '&q=' + encodeURIComponent(q))).json();
    searchResults = data.results || [];
    el.innerHTML = searchResults.length
      ? searchResults.map((r, i) => card({title: r.title, poster_url: r.poster_url,
          subtitle: [r.kind, r.sub_count ? 'SUB ' + r.sub_count : '', r.dub_count ? 'DUB ' + r.dub_count : '']
            .filter(Boolean).join(' · ')}, 'openShow(searchResults[' + i + '])')).join('')
      : '<div style="opacity:.6">Nothing found</div>';
  } catch (e) { el.innerHTML = ''; toast('Could not reach PC'); }
}

let show = null, showData = null, showDub = false;
async function openShow(item) {
  show = item;
  document.getElementById('browseHome').classList.add('hidden');
  document.getElementById('showView').classList.remove('hidden');
  document.getElementById('showTitle').textContent = item.title;
  document.getElementById('episodes').innerHTML = '<div style="opacity:.6">Loading episodes…</div>';
  document.getElementById('showInfo').textContent = '';
  window.scrollTo(0, 0);
  try {
    showData = await (await fetch('/api/episodes?t=' + encodeURIComponent(token) + '&slug=' + encodeURIComponent(item.slug_id))).json();
    showDub = !!showData.prefer_dub && showData.dub > 0;
    renderEpisodes();
  } catch (e) { toast('Could not load episodes'); }
}

function closeShow() {
  document.getElementById('showView').classList.add('hidden');
  document.getElementById('browseHome').classList.remove('hidden');
}

function setAudio(dub) { showDub = dub; renderEpisodes(); }

// Same rule as the PC: the dub list is the first N episodes.
function renderEpisodes() {
  if (!showData) return;
  document.getElementById('segSub').classList.toggle('active', !showDub);
  document.getElementById('segDub').classList.toggle('active', showDub);
  const all = showData.episodes || [];
  const list = showDub ? all.slice(0, showData.dub) : all;
  document.getElementById('showInfo').textContent = showDub
    ? (showData.dub ? showData.dub + ' dubbed of ' + all.length : 'No dub yet')
    : all.length + ' episodes' + (showData.resume ? ' · up to ' + showData.resume : '');
  document.getElementById('episodes').innerHTML = list.map((ep, i) =>
    '<button class="' + (ep.number === showData.resume ? 'resume ' : '') + (ep.filler ? 'filler' : '')
    + '" onclick="playOnPc(' + i + ')">' + ep.number + '</button>').join('');
}

function playOnPc(i) {
  const ep = (showData.episodes || [])[i];
  if (!ep || !show) return;
  cmd('play_episode', {slug_id: show.slug_id, numeric_id: show.numeric_id, title: show.title,
                       poster_url: show.poster_url || '', episode_id: ep.id, number: ep.number, dub: showDub});
  toast('Playing episode ' + ep.number + ' on the PC');
  showTab('player');
}

// -- Continue on phone --------------------------------------------------------
// The PC pauses; this plays the same episode from the same second, through
// the PC (the video host won't serve a phone browser directly). "Back to PC"
// hands the position back.
let hls = null;
async function watchOnPhone() {
  let info;
  try {
    info = (await (await fetch('/stream/info?t=' + encodeURIComponent(token))).json()).stream;
  } catch (e) { toast('Could not reach PC'); return; }
  if (!info) { toast('Nothing is playing on the PC'); return; }
  await cmd('pause');
  const video = document.getElementById('phoneVideo');
  video.innerHTML = '';
  const t = encodeURIComponent(token);
  if (info.has_subtitle) {
    const track = document.createElement('track');
    track.kind = 'subtitles'; track.srclang = 'en'; track.label = 'English'; track.default = true;
    track.src = '/stream/sub.vtt?t=' + t;
    video.appendChild(track);
  }
  const start = () => { video.currentTime = info.position || 0; video.play().catch(() => {}); };
  document.getElementById('watch').classList.remove('hidden');
  if (info.kind === 'file') {
    video.src = '/stream/file?t=' + t;
    video.addEventListener('loadedmetadata', start, {once: true});
  } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
    video.src = '/stream/index.m3u8?t=' + t;
    video.addEventListener('loadedmetadata', start, {once: true});
  } else {
    await loadHlsJs();
    hls = new Hls({startPosition: info.position || 0});
    hls.loadSource('/stream/index.m3u8?t=' + t);
    hls.attachMedia(video);
    hls.on(Hls.Events.MANIFEST_PARSED, () => video.play().catch(() => {}));
  }
  if (video.textTracks.length) video.textTracks[0].mode = 'showing';
}

function loadHlsJs() {
  if (window.Hls) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/hls.js@1/dist/hls.min.js';
    s.onload = resolve; s.onerror = () => { toast('Could not load the video player'); reject(); };
    document.head.appendChild(s);
  });
}

function closePhoneVideo() {
  const video = document.getElementById('phoneVideo');
  video.pause();
  if (hls) { hls.destroy(); hls = null; }
  video.removeAttribute('src'); video.load();
  document.getElementById('watch').classList.add('hidden');
}

async function backToPc() {
  const at = document.getElementById('phoneVideo').currentTime || 0;
  closePhoneVideo();
  await cmd('resume_at', at);
  toast('Back on the PC at ' + fmtTime(at));
}

function stopPhone() { closePhoneVideo(); }

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


# The remote app's versionCode (android-remote/AndroidManifest.xml) of the
# APK in this package. A phone running an older one is offered this one.
REMOTE_APP_VERSION = 2


def _generate_pin() -> str:
    return "".join(secrets.choice(string.digits) for _ in range(4))


# Guessing the PIN. Four digits are 10,000 tries, which a script on the same
# Wi-Fi (a friend's laptop at school or in a cafe, where the remote starts
# with the app) gets through in seconds when nothing stops it. A device is
# shut out after a few wrong ones; many wrong ones from anywhere change the
# PIN, so spreading the guesses across devices gets nowhere either.
WRONG_PINS_PER_DEVICE = 5
DEVICE_LOCKOUT_SECONDS = 600
WRONG_PINS_BEFORE_NEW_PIN = 20


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
        stream_provider: Callable[[], dict[str, Any] | None] | None = None,
        search_provider: Callable[[str], list[dict[str, Any]]] | None = None,
        episodes_provider: Callable[[str], dict[str, Any]] | None = None,
        info_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        # The PC's accent colour, for the phone page to match (/api/info).
        self._info_provider = info_provider
        # The "second screen" half: what's playing on the PC (for continue
        # on phone), and searching / listing episodes from the phone. All
        # optional, so the server still stands up in tests without them.
        self._stream_provider = stream_provider
        self._search_provider = search_provider
        self._episodes_provider = episodes_provider
        self._relay_hosts: set[str] = set()
        self._relay_referer = ""
        self._relay_client = httpx.Client(timeout=30, follow_redirects=True)
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
        self._wrong_by_device: dict[str, tuple[int, float]] = {}   # ip -> (wrong PINs, locked until)
        self._wrong_total = 0
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def _check_pin(self, device: str, pin: str) -> tuple[bool, str]:
        """(right, what to tell the phone if not). See WRONG_PINS_PER_DEVICE."""
        now = time.monotonic()
        with self._lock:
            wrong, locked_until = self._wrong_by_device.get(device, (0, 0.0))
            if locked_until > now:
                minutes = int((locked_until - now) // 60) + 1
                return False, f"Too many wrong PINs -- try again in {minutes} min"
            if hmac.compare_digest(pin, self.pin):
                self._wrong_by_device.pop(device, None)
                return True, ""
            wrong += 1
            self._wrong_total += 1
            if self._wrong_total >= WRONG_PINS_BEFORE_NEW_PIN:
                self.pin = _generate_pin()
                self._wrong_total = 0
                self._wrong_by_device.clear()
                return False, "Wrong PIN -- the PIN has changed, check the PC"
            if wrong >= WRONG_PINS_PER_DEVICE:
                self._wrong_by_device[device] = (0, now + DEVICE_LOCKOUT_SECONDS)
                return False, "Too many wrong PINs -- try again in 10 min"
            self._wrong_by_device[device] = (wrong, 0.0)
            return False, "Wrong PIN"

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

            def _authorised(self, query: dict) -> bool:
                token = (query.get("t") or [""])[0]
                with server._lock:
                    return token in server._tokens

            def _relay_get(self, url: str, is_playlist: bool, token: str) -> None:
                if not relay.allowed(url, server._relay_hosts):
                    self._send_json(403, {"error": "not part of the current episode"})
                    return
                headers = {"Referer": server._relay_referer} if server._relay_referer else {}
                if is_playlist:
                    resp = server._relay_client.get(url, headers=headers)
                    body = relay.rewrite_playlist(resp.text, str(resp.url), token,
                                                  server._relay_hosts).encode()
                    self.send_response(resp.status_code)
                    self.send_header("Content-Type", "application/vnd.apple.mpegurl")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                with server._relay_client.stream("GET", url, headers=headers) as resp:
                    self.send_response(resp.status_code)
                    for name in ("Content-Type", "Content-Length"):
                        if resp.headers.get(name):
                            self.send_header(name, resp.headers[name])
                    self.end_headers()
                    try:
                        for chunk in resp.iter_bytes(64 * 1024):
                            self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        pass  # the phone seeked or stopped; nothing to do

            def _serve_file(self, path: Path, content_type: str) -> None:
                """A saved episode, with Range support: a phone's video
                player seeks by asking for byte ranges, and won't seek at
                all without them."""
                size = path.stat().st_size
                start, end = 0, size - 1
                range_header = self.headers.get("Range")
                if range_header and range_header.startswith("bytes="):
                    try:
                        first, last = range_header[6:].split("-", 1)
                        start = int(first) if first else 0
                        end = min(int(last), size - 1) if last else size - 1
                    except ValueError:
                        start, end = 0, size - 1
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                else:
                    self.send_response(200)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(end - start + 1))
                self.end_headers()
                try:
                    with path.open("rb") as f:
                        f.seek(start)
                        remaining = end - start + 1
                        while remaining > 0:
                            chunk = f.read(min(256 * 1024, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _second_screen(self, route: str, query: dict) -> bool:
                """Everything under /stream and /api/search|episodes. Returns
                False for paths it doesn't own."""
                if not (route.startswith("/stream/") or route in ("/api/search", "/api/episodes")):
                    return False
                if not self._authorised(query):
                    self._send_json(403, {"error": "Not paired -- enter the PIN again"})
                    return True
                token = query["t"][0]
                arg = lambda name: (query.get(name) or [""])[0]  # noqa: E731

                if route == "/api/search" and server._search_provider:
                    self._send_json(200, {"results": server._search_provider(arg("q"))})
                elif route == "/api/episodes" and server._episodes_provider:
                    self._send_json(200, server._episodes_provider(arg("slug")))
                elif route == "/stream/info":
                    current = server._stream_provider() if server._stream_provider else None
                    if current and current.get("kind") == "hls":
                        # A new episode resets what may be fetched.
                        server._relay_hosts = {relay.host_of(current["url"])}
                        server._relay_referer = current.get("referer") or ""
                    self._send_json(200, {"stream": current and {
                        "kind": current["kind"], "position": current.get("position", 0),
                        "title": current.get("title", ""), "episode": current.get("episode", 0),
                        "has_subtitle": bool(current.get("subtitle_url") or current.get("subtitle_path")),
                    }})
                elif route == "/stream/index.m3u8":
                    current = server._stream_provider() if server._stream_provider else None
                    if not current or current.get("kind") != "hls":
                        self._send_json(404, {"error": "nothing streaming"})
                    else:
                        server._relay_hosts.add(relay.host_of(current["url"]))
                        server._relay_referer = current.get("referer") or ""
                        self._relay_get(current["url"], True, token)
                elif route in ("/stream/pl", "/stream/seg"):
                    self._relay_get(arg("u"), route == "/stream/pl", token)
                elif route == "/stream/file":
                    current = server._stream_provider() if server._stream_provider else None
                    if not current or current.get("kind") != "file":
                        self._send_json(404, {"error": "no saved file playing"})
                    else:
                        self._serve_file(Path(current["path"]), "video/mp4")
                elif route == "/stream/sub.vtt":
                    current = server._stream_provider() if server._stream_provider else None
                    if current and current.get("subtitle_path"):
                        self._serve_file(Path(current["subtitle_path"]), "text/vtt")
                    elif current and current.get("subtitle_url"):
                        resp = server._relay_client.get(
                            current["subtitle_url"],
                            headers={"Referer": current.get("referer") or ""})
                        body = resp.content
                        self.send_response(resp.status_code)
                        self.send_header("Content-Type", "text/vtt")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    else:
                        self._send_json(404, {"error": "no subtitles"})
                else:
                    self._send_json(404, {"error": "not found"})
                return True

            def do_GET(self) -> None:  # noqa: N802 -- required BaseHTTPRequestHandler name
                parts = urlsplit(self.path)
                try:
                    if self._second_screen(parts.path, parse_qs(parts.query)):
                        return
                except (httpx.HTTPError, OSError) as e:
                    try:
                        self._send_json(502, {"error": str(e)})
                    except OSError:
                        pass
                    return
                if self.path == "/":
                    body = _REMOTE_PAGE.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif parts.path == "/api/state":
                    # Paired phones only: it says what's playing and what's
                    # on your lists, to anything on the same network otherwise.
                    if self._authorised(parse_qs(parts.query)):
                        self._send_json(200, server._state_provider())
                    else:
                        self._send_json(403, {"error": "Not paired -- enter the PIN again"})
                elif self.path == "/api/info":
                    # Unpaired too: the colours and the app version are for
                    # the PIN screen as much as anything.
                    info = dict(server._info_provider()) if server._info_provider else {}
                    has_apk = server._apk_path is not None and server._apk_path.is_file()
                    info.update({"apk": has_apk, "app_version": REMOTE_APP_VERSION if has_apk else 0})
                    self._send_json(200, info)
                elif self.path == "/app.apk":
                    self._serve_apk(include_body=True)
                else:
                    self._send_json(404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                if self.path == "/api/pair":
                    data = self._read_json_body()
                    pin = str(data.get("pin", "")).strip()
                    ok, error = server._check_pin(self.client_address[0], pin)
                    if ok:
                        token = secrets.token_urlsafe(18)
                        with server._lock:
                            server._tokens.add(token)
                        if server._on_new_token is not None:
                            server._on_new_token(token)
                        self._send_json(200, {"ok": True, "token": token})
                    else:
                        self._send_json(200, {"ok": False, "error": error})
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
        # Stopping doesn't wait for requests still being answered. It did, and
        # a phone mid-request -- relaying a video segment, a slow search --
        # held the app's quit for as long as that took: 42 seconds, measured,
        # with a paired phone polling. The app exits right after anyway.
        self._httpd.daemon_threads = True
        self._httpd.block_on_close = False
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
            self._thread = None
