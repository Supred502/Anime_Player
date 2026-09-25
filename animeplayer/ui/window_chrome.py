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

from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtGui import QWindow
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
