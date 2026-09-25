#!/usr/bin/env python3
"""Publishes a new version: every copy of the app then offers it as an update.

    python scripts/release.py patch "Fixed the thing"     0.2.0 -> 0.2.1
    python scripts/release.py minor "Big new feature"     0.2.1 -> 0.3.0
    python scripts/release.py 1.0.0 "First proper release"

The notes are what people see under "What's new" in the update prompt; use
"- " lines for a list. This bumps animeplayer/version.py, commits, tags the
commit v<version> and pushes both. GitHub then builds the Windows installer
and publishes the release (.github/workflows/release.yml, ~10 minutes);
apps pick it up at their next check, within a few hours, or straight away
from Settings > Check now.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "animeplayer" / "version.py"


def git(*args: str, capture: bool = False) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *args], check=True,
                            capture_output=capture, text=True)
    return result.stdout.strip() if capture else ""


def bump(current: str, how: str) -> str:
    if re.fullmatch(r"\d+\.\d+\.\d+", how):
        return how
    major, minor, patch = (int(p) for p in current.split("."))
    if how == "major":
        return f"{major + 1}.0.0"
    if how == "minor":
        return f"{major}.{minor + 1}.0"
    if how == "patch":
        return f"{major}.{minor}.{patch + 1}"
    sys.exit(f"Don't know how to bump by {how!r}: use patch, minor, major or x.y.z")


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    how, notes = sys.argv[1], sys.argv[2].strip()
    if not notes:
        sys.exit("Say what changed -- it's what people see before they update.")

    if git("status", "--porcelain", capture=True):
        sys.exit("Commit (or stash) your changes first -- the release is built from what's committed.")

    text = VERSION_FILE.read_text()
    current = re.search(r'^VERSION = "([^"]+)"', text, re.M).group(1)
    new = bump(current, how)
    if tuple(map(int, new.split("."))) <= tuple(map(int, current.split("."))):
        sys.exit(f"{new} isn't newer than {current}.")

    VERSION_FILE.write_text(re.sub(r'^VERSION = "[^"]+"', f'VERSION = "{new}"', text, flags=re.M))
    git("add", str(VERSION_FILE))
    git("commit", "-m", f"Release {new}\n\n{notes}")
    git("tag", "-a", f"v{new}", "-m", notes)
    branch = git("rev-parse", "--abbrev-ref", "HEAD", capture=True)
    git("push", "origin", branch)
    git("push", "origin", f"v{new}")
    print(f"\nReleased {current} -> {new}. GitHub is building it now:")
    print(f"  https://github.com/Supred502/Anime_Player/actions")


if __name__ == "__main__":
    main()
