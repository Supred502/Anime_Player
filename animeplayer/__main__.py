from __future__ import annotations

import locale
import os
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QTimer, qInstallMessageHandler
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
from PySide6.QtQuickControls2 import QQuickStyle

from animeplayer.player.mpv_video_item import MpvVideoItem
from animeplayer.ui.backend import Backend
from animeplayer.ui.window_chrome import WindowChrome

QML_DIR = Path(__file__).parent / "ui" / "qml"
ASSETS_DIR = Path(__file__).parent / "ui" / "assets"

# Shipped rather than asked of the system: the app should look the same on a
# machine that happens to have Roboto installed and one that doesn't, and
# Kirigami otherwise falls back to whatever the Plasma font setting is.
_FONT_FAMILY = "Roboto"


def _load_bundled_fonts() -> str | None:
    """Registers the bundled Roboto faces and returns the family name Qt filed
    them under, or None if none loaded (in which case the platform font is
    left alone rather than a missing family being requested by name)."""
    family: str | None = None
    for path in sorted((ASSETS_DIR / "fonts").glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id == -1:
            continue
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            family = families[0]
    return family


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


# The pure-QML Breeze style, not the default org.kde.desktop one. The latter
# draws its controls through the platform QStyle, which reads the system
# colour scheme and ignores both Kirigami.Theme and QPalette -- measured live,
# a page themed purple still drew Breeze-blue buttons and checkboxes. This
# style is Kirigami-themed all the way down, so the app's own colours apply to
# stock controls too. Set before QGuiApplication, and only if it is installed.
_QML_STYLE = "org.kde.breeze"


def _use_themable_style() -> None:
    # QLibraryInfo, not an engine's importPathList: the style has to be chosen
    # before QGuiApplication exists, and constructing a QQmlApplicationEngine
    # that early aborts with "Must construct a QCoreApplication before a
    # QJSEngine".
    qml_root = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.QmlImportsPath))
    if (qml_root / "org" / "kde" / "breeze" / "qmldir").exists():
        QQuickStyle.setStyle(_QML_STYLE)


def main() -> int:
    qInstallMessageHandler(_print_qt_message)
    _use_themable_style()
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Anime Player")
    app.setOrganizationName("animeplayer")
    app.setWindowIcon(QIcon(str(ASSETS_DIR / "images" / "AP.svg")))
    # setDesktopFileName as well as setWindowIcon: on Wayland the compositor
    # takes a window's task-manager icon from the .desktop file it can match
    # the app to, and ignores the icon the app sets on itself.
    app.setDesktopFileName("io.github.supred.animeplayer")

    bundled_family = _load_bundled_fonts()
    if bundled_family is not None:
        font = QFont(bundled_family)
        # Qt defaults an app font to 0pt when built from a family name alone,
        # which renders as an unreadably small default in some styles.
        font.setPointSizeF(app.font().pointSizeF())
        app.setFont(font)

    # Qt's QGuiApplication resets the process locale from the environment on
    # construction. libmpv requires LC_NUMERIC to stay "C" (it parses/formats
    # numbers with plain C functions internally) -- anything else reliably
    # segfaults it. Must be reset after the QGuiApplication call, not before.
    locale.setlocale(locale.LC_NUMERIC, "C")

    qmlRegisterType(MpvVideoItem, "AnimePlayer", 1, 0, "MpvVideoItem")

    engine = QQmlApplicationEngine()
    backend = Backend()
    engine.rootContext().setContextProperty("backend", backend)
    # Kept alive by this reference: a context property is not owned by the
    # engine, and a WindowChrome that went out of scope here would be
    # collected while QML still held a pointer to it.
    window_chrome = WindowChrome()
    engine.rootContext().setContextProperty("windowChrome", window_chrome)
    app.aboutToQuit.connect(backend.shutdown)

    # ANIMEPLAYER_TEST_QML swaps in a scripted driver that walks the real
    # pages through a real navigation path, and ANIMEPLAYER_TEST_PAUSE slows
    # it down so a screenshot can land mid-flow -- see
    # ui/qml/_TestPlaybackReal.qml. Both no-op for a normal launch.
    engine.rootContext().setContextProperty("testPause", os.environ.get("ANIMEPLAYER_TEST_PAUSE", ""))
    engine.rootContext().setContextProperty(
        "testHideControls", os.environ.get("ANIMEPLAYER_TEST_HIDECONTROLS", "")
    )
    engine.rootContext().setContextProperty("testMode", os.environ.get("ANIMEPLAYER_TEST_MODE", ""))
    root_qml = os.environ.get("ANIMEPLAYER_TEST_QML", "Main.qml")
    engine.load(str(QML_DIR / root_qml))
    if not engine.rootObjects():
        return 1

    # Qt runs no shutdown of its own for SIGTERM/SIGINT, so a plain `kill` (or
    # a Ctrl-C in the terminal) used to tear the process down mid-frame. That
    # matters here because the player hides the mouse pointer while its
    # controls are faded out, and a Wayland compositor keeps whatever cursor a
    # client last set: dying that way left the whole desktop with no visible
    # pointer until something else happened to set one. Quitting through Qt
    # runs aboutToQuit, which is where PlayerPage.qml puts the arrow back.
    #
    # The timer is not idle work: while app.exec() is blocked inside Qt's C++
    # event loop, Python never gets to run a queued signal handler, so without
    # something waking the interpreter periodically these handlers would only
    # fire on the next unrelated event.
    signal_wakeup = QTimer()
    signal_wakeup.start(200)
    signal_wakeup.timeout.connect(lambda: None)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: app.quit())

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
