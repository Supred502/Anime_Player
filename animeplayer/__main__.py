from __future__ import annotations

import locale
import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType

from animeplayer.player.mpv_video_item import MpvVideoItem
from animeplayer.ui.backend import Backend

QML_DIR = Path(__file__).parent / "ui" / "qml"


def main() -> int:
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Anime Player")
    app.setOrganizationName("animeplayer")

    # Qt's QGuiApplication resets the process locale from the environment on
    # construction. libmpv requires LC_NUMERIC to stay "C" (it parses/formats
    # numbers with plain C functions internally) -- anything else reliably
    # segfaults it. Must be reset after the QGuiApplication call, not before.
    locale.setlocale(locale.LC_NUMERIC, "C")

    qmlRegisterType(MpvVideoItem, "AnimePlayer", 1, 0, "MpvVideoItem")

    engine = QQmlApplicationEngine()
    backend = Backend()
    engine.rootContext().setContextProperty("backend", backend)
    app.aboutToQuit.connect(backend.shutdown)

    engine.load(str(QML_DIR / "Main.qml"))
    if not engine.rootObjects():
        return 1

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
