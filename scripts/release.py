#!/usr/bin/env python3
"""Publishes a new version: every copy of the app then offers it as an update.

    python scripts/release.py minor                        0.3.0 -> 0.4.0
    python scripts/release.py patch "Fixed the thing"     0.4.0 -> 0.4.1
    python scripts/release.py 1.0.0 "First proper release"

The notes are what people see under "What's new", in the update prompt and
again after updating. Leave them out and they're made from the commits
since the last release, one line each -- printed first, so you can see
them. This bumps animeplayer/version.py, commits, tags the
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


def changes_since_last_release() -> str:
    """One "- " line per commit since the last v* tag: its subject line."""
    try:
        last = git("describe", "--tags", "--abbrev=0", "--match", "v*", capture=True)
        span = f"{last}..HEAD"
    except subprocess.CalledProcessError:
        span = "HEAD"
    subjects = git("log", "--reverse", "--format=%s", span, capture=True).splitlines()
    return "\n".join(f"- {s}" for s in subjects if s and not s.startswith("Release "))


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
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    how = sys.argv[1]
    notes = sys.argv[2].strip() if len(sys.argv) == 3 else changes_since_last_release()
    if not notes:
        sys.exit("Nothing has changed since the last release.")
    print("What's new:\n" + notes + "\n")

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
