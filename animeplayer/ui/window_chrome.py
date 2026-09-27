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

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, Slot
from PySide6.QtGui import QGuiApplication, QKeyEvent, QMouseEvent, QWindow
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
