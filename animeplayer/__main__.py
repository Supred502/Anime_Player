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

from animeplayer import platform_setup

platform_setup.before_imports()

from animeplayer.player.mpv_video_item import MpvVideoItem  # noqa: E402 -- needs the DLL path set up first
from animeplayer.gamepad import Gamepad  # noqa: E402
from animeplayer.ui import kirigami_compat  # noqa: E402
from animeplayer.ui.backend import Backend  # noqa: E402
from animeplayer.ui.window_chrome import WindowChrome  # noqa: E402

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


def _use_themable_style(compat: bool) -> None:
    # QLibraryInfo, not an engine's importPathList: the style has to be chosen
    # before QGuiApplication exists, and constructing a QQmlApplicationEngine
    # that early aborts with "Must construct a QCoreApplication before a
    # QJSEngine".
    qml_root = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.QmlImportsPath))
    if not compat and (qml_root / "org" / "kde" / "breeze" / "qmldir").exists():
        QQuickStyle.setStyle(_QML_STYLE)
    else:
        # No KDE here (Windows): Fusion, coloured Breeze Dark by
        # ui/kirigami_compat.py, is the closest stock style.
        QQuickStyle.setStyle("Fusion")


def _selftest(out_path: str) -> int:
    """`--selftest <file>`: checks the pieces a packaged build bundles --
    libmpv, ffmpeg, the Japanese tokenizer, the keyring -- and writes what
    it found to <file> as JSON. Run by the Windows build in CI, where the
    app has no console to print to."""
    import json
    import subprocess

    results: dict[str, str] = {}

    def check(name, fn) -> None:
        try:
            results[name] = str(fn())
        except Exception as exc:  # noqa: BLE001 -- the point is to report it
            results[name] = f"FAIL: {exc!r}"

    def mpv_version() -> str:
        import mpv
        player = mpv.MPV(vo="null", ao="null")
        try:
            return player.mpv_version
        finally:
            player.terminate()

    def ffmpeg_version() -> str:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=30,
                                creationflags=platform_setup.NO_WINDOW)
        return result.stdout.splitlines()[0]

    def tokenize() -> str:
        from animeplayer.learn import japanese
        return japanese.analyse("日本語を勉強します")["romaji"]

    def keyring_backend() -> str:
        import keyring
        return type(keyring.get_keyring()).__name__

    from animeplayer import updates
    from animeplayer.storage.db import DEFAULT_DB_PATH

    check("version", lambda: updates.VERSION)
    check("mpv", mpv_version)
    check("ffmpeg", ffmpeg_version)
    check("japanese", tokenize)
    check("keyring", keyring_backend)
    check("data_dir", lambda: DEFAULT_DB_PATH.parent)
    check("kirigami_compat", kirigami_compat.needed)

    def controller_support() -> str:
        from animeplayer import gamepad
        if gamepad.sdl2 is None:
            raise RuntimeError("SDL isn't bundled")
        pad = gamepad.Gamepad()
        if not pad.available:
            raise RuntimeError("SDL couldn't start")
        pad.shutdown()
        return "SDL %d.%d.%d" % gamepad.sdl2.dll.version_tuple

    check("controllers", controller_support)
    Path(out_path).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return 1 if any(v.startswith("FAIL") for v in results.values()) else 0


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--selftest":
        return _selftest(sys.argv[2])
    qInstallMessageHandler(_print_qt_message)
    platform_setup.before_app()
    compat = kirigami_compat.needed()
    if compat:
        kirigami_compat.register()
    _use_themable_style(compat)
    app = QGuiApplication(sys.argv)
    if compat:
        # Again: Plasma's platform theme swaps its own style in while the
        # application is constructed, which matters only when previewing
        # the Windows look on KDE.
        _use_themable_style(compat)
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
    if compat:
        kirigami_compat.install(engine)
    backend = Backend()
    engine.rootContext().setContextProperty("backend", backend)
    # Kept alive by this reference: a context property is not owned by the
    # engine, and a WindowChrome that went out of scope here would be
    # collected while QML still held a pointer to it.
    window_chrome = WindowChrome()
    engine.rootContext().setContextProperty("windowChrome", window_chrome)
    # Controllers (see gamepad.py). Held here for the same reason.
    game_controller = Gamepad()
    engine.rootContext().setContextProperty("gamepad", game_controller)
    app.aboutToQuit.connect(game_controller.shutdown)
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
    engine.rootContext().setContextProperty("testShots", os.environ.get("ANIMEPLAYER_TEST_SHOTS", ""))
    root_qml = os.environ.get("ANIMEPLAYER_TEST_QML", "Main.qml")
    engine.load(str(QML_DIR / root_qml))
    if not engine.rootObjects():
        return 1
    game_controller.filter_window(engine.rootObjects()[0])

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

    code = app.exec()
    # Past this point nothing of the app's own is left to run: aboutToQuit
    # has saved everything (Backend.shutdown). The players are stopped, and
    # then the process ends here rather than through Python's own shutdown,
    # during which mpv's and Qt's native threads can still call into an
    # interpreter that is being torn down -- a crash on every quit made
    # mid-episode, and seconds of waiting before it.
    MpvVideoItem.close_all()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    raise SystemExit(main())
