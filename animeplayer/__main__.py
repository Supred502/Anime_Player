from __future__ import annotations

import locale
import os
import sys
from pathlib import Path

from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType

from animeplayer.player.mpv_video_item import MpvVideoItem
from animeplayer.ui.backend import Backend

QML_DIR = Path(__file__).parent / "ui" / "qml"


def _print_qt_message(_mode, context, message: str) -> None:
    """Qt swallows QML console.log/warn output entirely in this PySide6 build
    (confirmed: nothing reaches stdout or stderr, with or without
    QT_LOGGING_RULES), which makes QML-side warnings -- binding loops,
    undefined property reads, and anything a page logs about itself --
    invisible while debugging. Routing Qt's message stream through Python
    restores them.
    """
    where = f"{Path(context.file).name}:{context.line}" if context.file else "qml"
    print(f"[qml] {where}: {message}", file=sys.stderr, flush=True)


def main() -> int:
    qInstallMessageHandler(_print_qt_message)
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

    # ANIMEPLAYER_TEST_QML swaps in a scripted driver that walks the real
    # pages through a real navigation path, and ANIMEPLAYER_TEST_PAUSE slows
    # it down so a screenshot can land mid-flow -- see
    # ui/qml/_TestPlaybackReal.qml. Both no-op for a normal launch.
    engine.rootContext().setContextProperty("testPause", os.environ.get("ANIMEPLAYER_TEST_PAUSE", ""))
    engine.rootContext().setContextProperty(
        "testHideControls", os.environ.get("ANIMEPLAYER_TEST_HIDECONTROLS", "")
    )
    root_qml = os.environ.get("ANIMEPLAYER_TEST_QML", "Main.qml")
    engine.load(str(QML_DIR / root_qml))
    if not engine.rootObjects():
        return 1

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
