"""Finding out a newer version exists, and fetching it.

Releases live on GitHub (see version.py). A release is a git tag v1.2.3 with
the Windows installer attached, and its notes are what the update prompt
shows as "What's new". The check is one unauthenticated request to GitHub's
API -- well inside its 60-an-hour limit at one check every few hours.

How an update is applied depends on how the app is running:

* The Windows build (frozen by PyInstaller): download the new installer and
  run it silently. It closes this copy, replaces the files and starts the new
  one (see packaging/windows/installer.iss).
* A git checkout (running from source, as on the developer's own machine):
  `git pull`, then restart.
* Anything else: the release page is opened and the rest is up to the user.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

from animeplayer.platform_setup import NO_WINDOW
from animeplayer.version import REPO, VERSION

API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
INSTALLER_SUFFIX = "-Setup.exe"


class UpdateError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Release:
    version: str
    notes: str
    page_url: str
    installer_url: str  # "" when the release has no Windows installer attached
    installer_size: int


def parse_version(text: str) -> tuple[int, ...]:
    """"v1.2.3" -> (1, 2, 3). Anything after the numbers (-beta) is ignored,
    and garbage reads as (0,) so it never looks newer than anything."""
    match = re.match(r"v?(\d+(?:\.\d+)*)", text.strip())
    return tuple(int(p) for p in match.group(1).split(".")) if match else (0,)


def is_newer(candidate: str, current: str = VERSION) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def latest_release(client: httpx.Client) -> Release | None:
    """The newest published release, or None if there isn't one yet."""
    try:
        resp = client.get(API_URL, headers={"Accept": "application/vnd.github+json"}, timeout=15)
    except httpx.HTTPError as exc:
        raise UpdateError("Couldn't reach GitHub to check for updates.") from exc
    if resp.status_code == 404:
        return None
    if resp.status_code in (403, 429):
        raise UpdateError("GitHub is rate-limiting update checks -- try again later.")
    resp.raise_for_status()
    data = resp.json()
    installer = next((a for a in data.get("assets") or []
                      if a.get("name", "").endswith(INSTALLER_SUFFIX)), None)
    return Release(
        version=".".join(str(p) for p in parse_version(data.get("tag_name", ""))),
        notes=(data.get("body") or "").strip(),
        page_url=data.get("html_url") or f"https://github.com/{REPO}/releases",
        installer_url=installer["browser_download_url"] if installer else "",
        installer_size=int(installer.get("size") or 0) if installer else 0,
    )


def release_notes(client: httpx.Client, version: str) -> str:
    """The notes published with one version, for "What's new" after an
    update. "" if there are none or GitHub can't be reached."""
    try:
        resp = client.get(f"https://api.github.com/repos/{REPO}/releases/tags/v{version}",
                          headers={"Accept": "application/vnd.github+json"}, timeout=15)
    except httpx.HTTPError:
        return ""
    if resp.status_code != 200:
        return ""
    return (resp.json().get("body") or "").strip()


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def source_checkout() -> Path | None:
    """The git working tree this copy runs from, if it runs from one."""
    root = Path(__file__).resolve().parent.parent
    return root if (root / ".git").exists() else None


def how_to_install() -> str:
    """"installer", "git" or "page" -- see the module docstring."""
    if is_frozen() and sys.platform == "win32":
        return "installer"
    if not is_frozen() and source_checkout() is not None:
        return "git"
    return "page"


def download_installer(client: httpx.Client, release: Release, folder: Path,
                       on_progress: Callable[[float], None]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"AnimePlayer-{release.version}{INSTALLER_SUFFIX}"
    partial = target.with_suffix(".part")
    with client.stream("GET", release.installer_url, follow_redirects=True, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length") or release.installer_size or 0)
        done = 0
        with open(partial, "wb") as out:
            for chunk in resp.iter_bytes(1 << 16):
                out.write(chunk)
                done += len(chunk)
                if total:
                    on_progress(min(1.0, done / total))
    if release.installer_size and partial.stat().st_size != release.installer_size:
        partial.unlink(missing_ok=True)
        raise UpdateError("The download was cut short -- try again.")
    partial.replace(target)
    return target


def run_installer(path: Path) -> None:
    """Starts the installer detached, so it outlives this process -- which
    the caller then quits, freeing the files the installer is replacing."""
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                     creationflags=flags, close_fds=True)


def git_pull(root: Path) -> str:
    """Brings a source checkout up to date. Returns git's own message on
    failure (local changes in the way, no network), "" on success."""
    try:
        result = subprocess.run(["git", "-C", str(root), "pull", "--ff-only"],
                                capture_output=True, text=True, timeout=120,
                                creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)
    if result.returncode != 0:
        output = (result.stderr or result.stdout).strip()
        return output.splitlines()[-1] if output else "git pull failed"
    return ""
