#!/usr/bin/env python3
"""Copies the Breeze icons the app uses into a small icon theme it ships.

Windows has no freedesktop icon theme, so every `icon.name:` in the QML
would draw nothing there. This scans the QML for quoted names, looks each
one up in the installed Breeze Dark theme -- falling back the way
freedesktop lookup does (a-b-symbolic -> a-b -> a) -- and writes the files
to animeplayer/ui/assets/icons/breeze-compat. Run it on a machine with
Breeze installed after adding a new icon to the QML, and commit the result.

Breeze icons are LGPL-3.0 (KDE); the licence text goes alongside them.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QML = ROOT / "animeplayer" / "ui" / "qml"
OUT = ROOT / "animeplayer" / "ui" / "assets" / "icons" / "breeze-compat"
BREEZE = Path("/usr/share/icons/breeze-dark")
SIZES = ("16", "22", "32")
# Built from strings at runtime, so not found by the scan.
EXTRA = ["media-playback-pause-symbolic", "media-playback-start-symbolic",
         "audio-volume-high-symbolic", "audio-volume-muted-symbolic",
         "go-previous-symbolic", "go-next-symbolic", "go-up-symbolic", "go-down-symbolic",
         "window-close-symbolic", "dialog-close-symbolic", "edit-clear-symbolic",
         "view-fullscreen-symbolic", "view-restore-symbolic", "update-none-symbolic"]


# Words the scan finds that happen to be icon names too, but aren't used as icons.
SKIP = {"none", "label"}


def find(name: str, size: str) -> Path | None:
    """Only -symbolic names fall back: a plain word found in the QML ("none",
    "home") is as likely to be a setting value as an icon."""
    candidate = name
    while candidate:
        # This size first, then any size: an exact name drawn at another
        # size beats a vaguer name at this one.
        for want in (size, *(s for s in ("16", "22", "24", "32", "48") if s != size)):
            for context in sorted(BREEZE.iterdir()):
                path = context / want / f"{candidate}.svg"
                if path.exists():
                    return path.resolve()
        if "-" not in candidate or not name.endswith("-symbolic"):
            return None
        candidate = candidate.rsplit("-", 1)[0]
    return None


def main() -> None:
    names = set(EXTRA)
    for qml in QML.glob("*.qml"):
        names.update(re.findall(r'"([a-z][a-z0-9-]+)"', qml.read_text()))
    names -= SKIP
    if OUT.exists():
        shutil.rmtree(OUT)
    written = set()
    for size in SIZES:
        (OUT / size).mkdir(parents=True)
        for name in sorted(names):
            source = find(name, size)
            if source is not None:
                shutil.copyfile(source, OUT / size / f"{name}.svg")
                written.add(name)
    dirs = ",".join(SIZES)
    sections = "\n".join(
        f"[{s}]\nSize={s}\nType=Scalable\nMinSize=8\nMaxSize=512\n" for s in SIZES)
    (OUT / "index.theme").write_text(
        "[Icon Theme]\nName=breeze-compat\nComment=Breeze icons used by Anime Player\n"
        f"Directories={dirs}\n\n{sections}")
    licence = Path("/usr/share/licenses/breeze-icon-theme")
    for f in licence.glob("*") if licence.exists() else []:
        shutil.copyfile(f, OUT / f.name)
    (OUT / "README").write_text(
        "Icons from KDE's Breeze icon theme (breeze-dark), https://invent.kde.org/frameworks/breeze-icons\n"
        "Licensed LGPL-3.0-or-later. Collected by packaging/windows/collect_icons.py.\n")
    print(f"{len(written)} icons -> {OUT}")


if __name__ == "__main__":
    main()
