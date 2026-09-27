"""Saving episodes to disk, so they play without the network and without
re-resolving a stream that expires.

ffmpeg does the work rather than a Python HLS client: the source hands out an
m3u8 whose segments need the same Referer the player uses, and ffmpeg already
knows how to follow a playlist, reassemble it and remux to mp4 without
re-encoding. Measured live against a real episode: `-c copy` runs at about 75x
realtime, so a 24-minute episode lands in roughly twenty seconds.

One download at a time, deliberately. Three parallel ffmpeg processes pulling
from the same CDN is how an IP gets rate-limited, and the queue finishes in the
same total time either way.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import httpx

from animeplayer.platform_setup import NO_WINDOW
from animeplayer.storage.db import DEFAULT_DB_PATH

# Beside the database rather than in the user's Videos folder: these are the
# app's own cache of something re-downloadable, and they get deleted
# automatically once watched. Putting self-deleting files in a folder the user
# curates themselves is how you eventually delete something they meant to keep.
DEFAULT_DOWNLOAD_DIR = DEFAULT_DB_PATH.parent / "downloads"
# Where new downloads go. Settings can point it elsewhere (a bigger drive);
# episodes already saved keep the path they were saved to, which the
# database holds, so changing it never loses anything.
DOWNLOAD_DIR = DEFAULT_DOWNLOAD_DIR


def set_download_dir(path: str | Path | None) -> None:
    global DOWNLOAD_DIR
    DOWNLOAD_DIR = Path(path) if path else DEFAULT_DOWNLOAD_DIR

# ffmpeg reports progress as key=value lines on stdout with -progress. This is
# the one that matters: microseconds of output written so far.
_OUT_TIME_RE = re.compile(rb"out_time_us=(\d+)")
_TOTAL_SIZE_RE = re.compile(rb"total_size=(\d+)")


class DownloadError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class DownloadRequest:
    episode_id: int
    dub: bool
    slug_id: str
    numeric_id: str
    anime_title: str
    poster_url: str
    episode_number: float


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _safe_name(text: str) -> str:
    """A filename that survives every filesystem. Titles arrive with colons,
    slashes and full-width punctuation straight from the source."""
    cleaned = re.sub(r"[^\w\-. ]+", "_", text, flags=re.UNICODE).strip()
    return (cleaned or "anime")[:80]


def target_path(request: DownloadRequest) -> Path:
    number = request.episode_number
    # 12 rather than 12.0 for whole episodes, but x.5 specials keep their half.
    label = str(int(number)) if float(number).is_integer() else str(number)
    audio = "dub" if request.dub else "sub"
    folder = DOWNLOAD_DIR / f"{_safe_name(request.anime_title)}-{request.slug_id}"
    return folder / f"episode-{label}-{audio}.mp4"


def probe_duration(url: str, referer: str) -> float:
    """Total seconds, so progress can be a fraction rather than a stopwatch.
    Returns 0 when it can't be determined -- the caller then reports bytes
    written instead of a percentage, which is still honest movement."""
    if shutil.which("ffprobe") is None:
        return 0.0
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-headers", _headers(referer),
             "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", url],
            capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW,
        )
        return float(result.stdout.strip() or 0)
    except (subprocess.SubprocessError, ValueError):
        return 0.0


def _headers(referer: str) -> str:
    # Both, not just Referer: the CDN 403s a segment request that carries one
    # without the other, which shows up as a download that starts and then
    # stops at zero bytes.
    origin = referer.rstrip("/")
    return f"Referer: {referer}\r\nOrigin: {origin}\r\n"


def download_subtitle(url: str, destination: Path, client: httpx.Client,
                      referer: str = "") -> Path | None:
    """Subtitles are a separate WebVTT file, not a track inside the stream, so
    an offline copy needs them fetched alongside. A failure here is not a
    failed download -- the episode is still watchable.

    The Referer matters: the host refuses some subtitle files without it
    (measured: episode 1 of a show 200 either way, episode 3 403 bare and
    200 with it), which left saved episodes silently without subtitles."""
    try:
        response = client.get(url, timeout=30, headers={"Referer": referer} if referer else None)
        response.raise_for_status()
        destination.write_bytes(response.content)
        return destination
    except (httpx.HTTPError, OSError):
        return None


class Downloader:
    """Runs one ffmpeg at a time. `on_progress(fraction, bytes)` is called from
    the worker thread, so callers marshal to the GUI thread themselves (the
    Qt signals in ui/backend.py already do).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: subprocess.Popen | None = None
        self._cancelled: set[tuple[int, bool]] = set()

    def cancel(self, episode_id: int, dub: bool) -> None:
        with self._lock:
            self._cancelled.add((episode_id, dub))
            process = self._current
        # Terminating whatever is running is right even if it is a different
        # episode: the queue re-checks the cancelled set before each item, so
        # the worst case is one item restarting.
        if process is not None and process.poll() is None:
            process.terminate()

    def is_cancelled(self, episode_id: int, dub: bool) -> bool:
        with self._lock:
            return (episode_id, dub) in self._cancelled

    def clear_cancelled(self, episode_id: int, dub: bool) -> None:
        with self._lock:
            self._cancelled.discard((episode_id, dub))

    def fetch(self, url: str, referer: str, destination: Path, duration: float,
              on_progress, readrate: float = 0.0) -> None:
        """Pulls one stream to `destination`. Raises DownloadError on failure.

        Writes to a .part file and renames on success, so a half-finished
        download can never be mistaken for a playable episode -- which matters
        here because the database row is what decides whether to play locally.
        """
        if not ffmpeg_available():
            raise DownloadError("ffmpeg is not installed, so episodes can't be saved.")

        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(".part.mp4")

        command = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-headers", _headers(referer),
            # Read at most this many times realtime; 0 means as fast as the
            # network allows.
            *(["-readrate", f"{readrate:g}"] if readrate > 0 else []),
            # A connection that goes quiet fails after 30s (then the app
            # retries it) instead of hanging the queue; a dropped one is
            # reconnected.
            "-rw_timeout", "30000000",
            "-reconnect", "1", "-reconnect_on_network_error", "1", "-reconnect_delay_max", "5",
            "-i", url,
            # No re-encode: the segments are already h264/aac, and copying is
            # what makes this run faster than realtime. aac_adtstoasc is
            # required to put ADTS audio from HLS into an mp4 container.
            "-c", "copy", "-bsf:a", "aac_adtstoasc",
            "-progress", "pipe:1", "-nostats",
            str(partial),
        ]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=NO_WINDOW)
        with self._lock:
            self._current = process

        # stderr is drained as it comes. Read only at the end, a download
        # that ran into trouble filled the pipe with ffmpeg's retry warnings
        # (~64 KB) and then blocked on it forever: the download crawled or
        # hung, and the queue behind it with it.
        errors: deque[str] = deque(maxlen=20)

        def drain() -> None:
            for raw in process.stderr:
                errors.append(raw.decode("utf-8", "replace").rstrip())

        drainer = threading.Thread(target=drain, daemon=True)
        drainer.start()

        # ffmpeg emits a block of progress lines several times a second, and
        # each one is a cross-thread Qt signal and a UI update at the other
        # end. Reporting only on a visible change keeps a 100-second download
        # to about a hundred updates instead of several thousand.
        fraction, written, last_reported = 0.0, 0, -1.0
        try:
            for line in process.stdout:
                match = _OUT_TIME_RE.search(line)
                if match and duration > 0:
                    fraction = min(1.0, (int(match.group(1)) / 1_000_000) / duration)
                size = _TOTAL_SIZE_RE.search(line)
                if size:
                    written = int(size.group(1))
                if fraction - last_reported >= 0.01:
                    last_reported = fraction
                    on_progress(fraction, written)
            process.wait()
        finally:
            with self._lock:
                self._current = None

        drainer.join(timeout=5)
        if process.returncode != 0:
            stderr = "\n".join(line for line in errors if line)
            partial.unlink(missing_ok=True)
            # Terminated by cancel() rather than having actually failed.
            if process.returncode < 0:
                raise DownloadError("cancelled")
            raise DownloadError(stderr.splitlines()[-1] if stderr else "ffmpeg failed")

        partial.replace(destination)


def skip_times_path(media: str | Path) -> Path:
    """The intro/outro timings saved beside an episode. They arrive with the
    stream, which a saved episode never resolves again -- without keeping
    them, a downloaded episode could never skip its intro."""
    return Path(media).with_suffix(".skip.json")


def save_skip_times(media: str | Path, times: dict) -> None:
    if times:
        skip_times_path(media).write_text(json.dumps(times))


def load_skip_times(media: str | Path) -> dict:
    try:
        saved = json.loads(skip_times_path(media).read_text())
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def delete_files(*paths: str | Path | None) -> None:
    """Removes an episode's files, and the anime's folder once it is empty, so
    finishing a series doesn't leave a tree of empty directories behind."""
    folders = set()
    for path in paths:
        if not path:
            continue
        target = Path(path)
        target.unlink(missing_ok=True)
        folders.add(target.parent)
    for folder in folders:
        try:
            if folder.is_dir() and folder != DOWNLOAD_DIR and not any(folder.iterdir()):
                folder.rmdir()
        except OSError:
            pass


def disk_usage(paths: list[str] | None = None) -> int:
    """Total bytes held by downloads, for the Settings page: the files
    listed (every saved episode, wherever it was saved), or else whatever is
    in the download folder."""
    if paths is not None:
        total = 0
        for path in paths:
            try:
                total += Path(path).stat().st_size
            except OSError:
                pass
        return total
    if not DOWNLOAD_DIR.exists():
        return 0
    return sum(f.stat().st_size for f in DOWNLOAD_DIR.rglob("*") if f.is_file())


def move_episode(files: list[str | None], folder: Path) -> list[str | None]:
    """Moves one saved episode's files (video, subtitles, skip times) into
    `folder`/<its show's folder name>, returning the new paths in the same
    order. Copies then deletes, so it works across drives."""
    moved: list[str | None] = []
    for path in files:
        if not path or not Path(path).exists():
            moved.append(None if not path else str(folder / Path(path).parent.name / Path(path).name))
            continue
        source = Path(path)
        target = folder / source.parent.name / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target != source:
            shutil.move(str(source), str(target))
        moved.append(str(target))
    delete_files(*(f for f in files if f))  # only tidies the emptied old folder now
    return moved


def cut_audio(source: str, referer: str, start: float, seconds: float, out: Path) -> bool:
    """A few seconds of an episode's sound as an mp3 (for Anki cards):
    from a saved file or straight from the stream. Seeks before opening, so
    a stream is only read around the clip, not from the start."""
    command = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.0, start):.2f}"]
    if referer:
        command += ["-headers", _headers(referer)]
    command += ["-i", source, "-t", f"{seconds:.2f}", "-vn", "-ac", "1", "-b:a", "96k", str(out)]
    try:
        result = subprocess.run(command, capture_output=True, timeout=90, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and out.exists() and out.stat().st_size > 0

