"""Lets QML drive the window manager for a frameless window.

The app draws its own titlebar (see AppWindow.qml), which means the window
has no system frame to drag or resize by. Qt can still ask the compositor to
do both -- QWindow::startSystemMove() and startSystemResize() -- but neither
is callable from QML: they are plain C++ functions, not slots or properties,
so QML sees nothing. This wraps them in slots.

Asking the compositor rather than moving the window by hand matters on
Wayland, where a client cannot position itself at all: setting window.x/y
from a MouseArea silently does nothing there, and snapping, tiling and
multi-monitor edges are the compositor's business regardless.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, Slot
from PySide6.QtGui import QGuiApplication, QKeyEvent, QMouseEvent, QWheelEvent, QWindow
from PySide6.QtQuick import QQuickWindow


class WindowChrome(QObject):
    """Exposed to QML as `windowChrome`."""

    # Which edge a resize grip pulls, as QML-friendly integers. Qt.Edges is a
    # flags type, and flags round-trip through QML as ints.
    _EDGES = {
        "left": Qt.Edge.LeftEdge,
        "right": Qt.Edge.RightEdge,
        "top": Qt.Edge.TopEdge,
        "bottom": Qt.Edge.BottomEdge,
        "topleft": Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
        "topright": Qt.Edge.TopEdge | Qt.Edge.RightEdge,
        "bottomleft": Qt.Edge.BottomEdge | Qt.Edge.LeftEdge,
        "bottomright": Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
    }

    @Slot(QObject, result=bool)
    def startMove(self, window: QObject) -> bool:
        if not isinstance(window, QWindow):
            return False
        return window.startSystemMove()

    @Slot(QObject, str, result=bool)
    def startResize(self, window: QObject, edge: str) -> bool:
        if not isinstance(window, QWindow):
            return False
        edges = self._EDGES.get(edge)
        if edges is None:
            return False
        return window.startSystemResize(edges)

    @Slot(result=bool)
    def separateWindowsWork(self) -> bool:
        """False in the Steam Deck's Gaming Mode: gamescope shows one window
        at a time, so a second one (the floating mini player) would take the
        whole screen from the app rather than float over it."""
        return not (os.environ.get("GAMESCOPE_WAYLAND_DISPLAY")
                    or "gamescope" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower())

    @Slot(QObject, int, int, result=bool)
    def keepAbove(self, window: QObject, width: int = 0, height: int = 0) -> bool:
        """Keeps `window` above other apps' windows: the floating mini player.

        Qt's WindowStaysOnTopHint does it on Windows, macOS and X11. Wayland
        has no way for an app to ask, and KDE's KWin ignores the hint there
        (checked: keepAbove stayed false). KWin will do it for a script,
        though, so on KDE one is sent over D-Bus that finds this window by
        its title and process and keeps it above -- and, since a Wayland app
        can't place its own windows either, puts it in the bottom-right
        corner at `width` x `height`, and pulls it back onto the screen
        whenever a move or resize leaves part of it off. Returns whether
        that was needed and worked."""
        if not isinstance(window, QWindow):
            return False
        if QGuiApplication.platformName() != "wayland" \
                or "KDE" not in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
            return False
        return _kwin_keep_above(window.title(), os.getpid(), width, height)

    @Slot()
    def releaseKeepAbove(self) -> None:
        """Unloads keepAbove's KWin script once its window has closed."""
        if QGuiApplication.platformName() != "wayland" \
                or "KDE" not in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
            return
        try:
            from PySide6.QtDBus import QDBusConnection, QDBusMessage
        except ImportError:
            return
        message = QDBusMessage.createMethodCall("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting",
                                                "unloadScript")
        message.setArguments([f"animeplayer_keepabove_{os.getpid()}"])
        QDBusConnection.sessionBus().call(message)

    @Slot(QObject, str, result=bool)
    def saveScreenshot(self, window: QObject, path: str) -> bool:
        """The whole window, popups included, as the user would see it. For
        the test drivers (see _TestTour.qml); works headless as well."""
        if not isinstance(window, QQuickWindow):
            return False
        return window.grabWindow().save(path)

    @Slot(QObject, float, float, bool)
    def click(self, window: QObject, x: float, y: float, right: bool = False) -> None:
        """A mouse click at (x, y) in the window, exactly as the mouse would
        make it. How a controller's A (and X, for a right-click) presses
        whatever it has highlighted: every button, card and cell in the app
        already answers to a click, so none of them needs to know about
        controllers."""
        if not isinstance(window, QQuickWindow):
            return
        pos = QPointF(x, y)
        glob = window.mapToGlobal(pos)
        button = Qt.MouseButton.RightButton if right else Qt.MouseButton.LeftButton
        for kind, pressed in ((QEvent.Type.MouseMove, Qt.MouseButton.NoButton),
                              (QEvent.Type.MouseButtonPress, button),
                              (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
            which = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else button
            QGuiApplication.sendEvent(window, QMouseEvent(kind, pos, glob, which, pressed,
                                                          Qt.KeyboardModifier.NoModifier))

    @Slot(QObject, float, float)
    def hover(self, window: QObject, x: float, y: float) -> None:
        """Moves the (invisible) pointer to (x, y), so what a controller has
        highlighted also looks hovered -- and shows its hover preview."""
        if not isinstance(window, QQuickWindow):
            return
        pos = QPointF(x, y)
        QGuiApplication.sendEvent(window, QMouseEvent(
            QEvent.Type.MouseMove, pos, window.mapToGlobal(pos), Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))

    @Slot(QObject, int)
    def key(self, window: QObject, key: int) -> None:
        """A key press and release, to the window. B on a controller sends
        Escape, which is what closes a menu or a dialog in Qt."""
        if not isinstance(window, QQuickWindow):
            return
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QGuiApplication.sendEvent(window, QKeyEvent(kind, key, Qt.KeyboardModifier.NoModifier))

    @Slot(QObject, float, float, float, float)
    def testDrag(self, window: QObject, x1: float, y1: float, x2: float, y2: float) -> None:
        """A left-button drag from (x1, y1) to (x2, y2), in steps, as a mouse
        makes it. For the test drivers only."""
        if not isinstance(window, QQuickWindow):
            return
        left, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton

        def send(kind, x, y, button, buttons):
            pos = QPointF(x, y)
            QGuiApplication.sendEvent(window, QMouseEvent(kind, pos, window.mapToGlobal(pos), button,
                                                          buttons, Qt.KeyboardModifier.NoModifier))

        send(QEvent.Type.MouseMove, x1, y1, none, none)
        send(QEvent.Type.MouseButtonPress, x1, y1, left, left)
        for i in range(1, 21):
            send(QEvent.Type.MouseMove, x1 + (x2 - x1) * i / 20, y1 + (y2 - y1) * i / 20, none, left)
            QGuiApplication.processEvents()
        send(QEvent.Type.MouseButtonRelease, x2, y2, left, none)

    @Slot(QObject, float, float, int)
    def testWheel(self, window: QObject, x: float, y: float, delta: int) -> None:
        """One notch of a mouse wheel (delta 120 up, -120 down) at (x, y).
        For the test drivers only."""
        if not isinstance(window, QQuickWindow):
            return
        from PySide6.QtCore import QPoint
        pos = QPointF(x, y)
        QGuiApplication.sendEvent(window, QWheelEvent(
            pos, window.mapToGlobal(pos), QPoint(0, 0), QPoint(0, delta), Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))

    @Slot(QObject, int, int)
    def testKey(self, window: QObject, key: int, modifiers: int) -> None:
        """A key press through the same path a real keyboard takes,
        shortcuts included. For the test drivers only."""
        from PySide6.QtTest import QTest
        if isinstance(window, QQuickWindow):
            QTest.keyClick(window, Qt.Key(key), Qt.KeyboardModifier(modifiers))


_KWIN_SCRIPT = """
const title = %(title)s, pid = %(pid)d, width = %(width)d, height = %(height)d;
// Back fully on screen, against the edge it went past.
function onScreen(w) {
    const area = workspace.clientArea(KWin.MaximizeArea, w);
    const g = w.frameGeometry;
    const x = Math.min(Math.max(g.x, area.x), area.x + area.width - g.width);
    const y = Math.min(Math.max(g.y, area.y), area.y + area.height - g.height);
    if (x !== g.x || y !== g.y) w.frameGeometry = { x: x, y: y, width: g.width, height: g.height };
}
for (const w of workspace.windowList()) {
    if (w.caption !== title || w.pid !== pid) continue;
    w.keepAbove = true;
    if (width > 0 && height > 0) {
        const area = workspace.clientArea(KWin.PlacementArea, w);
        w.frameGeometry = { x: area.x + area.width - width - 24, y: area.y + area.height - height - 24,
                            width: width, height: height };
    }
    // Every time it's let go after a move or a resize. The script stays
    // loaded while the window is open for this (see releaseKeepAbove).
    w.interactiveMoveResizeFinished.connect(function() { onScreen(w); });
    // And after any other change -- the app putting a resized window back
    // to 16:9 can push its edge off -- but never mid-drag.
    w.frameGeometryChanged.connect(function() { if (!w.move && !w.resize) onScreen(w); });
}
"""


def _kwin_keep_above(title: str, pid: int, width: int, height: int) -> bool:
    """Loads, runs and unloads a one-off KWin script (see keepAbove). KWin
    reads the script from disk, so it goes in a file first; in the Flatpak
    that is under ~/.var/app, which is the same path on the host."""
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusMessage
    except ImportError:
        return False
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return False
    folder = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "animeplayer"
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".js", dir=folder, delete=False) as f:
        f.write(_KWIN_SCRIPT % {"title": json.dumps(title), "pid": pid,
                                "width": int(width), "height": int(height)})
        script = f.name
    name = f"animeplayer_keepabove_{pid}"

    def call(path: str, interface: str, method: str, *args):
        message = QDBusMessage.createMethodCall("org.kde.KWin", path, interface, method)
        if args:
            message.setArguments(list(args))
        return bus.call(message)

    try:
        call("/Scripting", "org.kde.kwin.Scripting", "unloadScript", name)   # a leftover
        reply = call("/Scripting", "org.kde.kwin.Scripting", "loadScript", script, name)
        if reply.type() != QDBusMessage.MessageType.ReplyMessage or not reply.arguments():
            return False
        script_id = int(reply.arguments()[0])
        if script_id < 0:
            return False
        run = call(f"/Scripting/Script{script_id}", "org.kde.kwin.Script", "run")
        # Left loaded: it keeps the window on screen after each move (see the
        # script). Unloaded when the window goes (releaseKeepAbove), or by the
        # next load, which clears a leftover of the same name first.
        return run.type() == QDBusMessage.MessageType.ReplyMessage
    finally:
        try:
            os.unlink(script)
        except OSError:
            pass
