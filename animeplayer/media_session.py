"""The desktop's media controls: a keyboard's play/pause, next and previous
keys, a headset's button, KDE's media widget -- working while another app is
in front, which is the point of the floating mini player.

Linux (and the Steam Deck): the app is an MPRIS player on the session bus,
which is what every Linux desktop's media keys and media widgets talk to.
Windows: the three media keys are claimed with RegisterHotKey while a
player is open, and let go when it closes, so other apps have them back.

Exposed to QML as `mediaSession`. A player calls update() as it plays and
clear() when it goes; presses arrive as action("playpause" | "play" |
"pause" | "next" | "previous" | "stop").
"""

from __future__ import annotations

import os
import sys
from typing import Any

from PySide6.QtCore import ClassInfo, Property, QObject, Signal, Slot

BUS_NAME = "org.mpris.MediaPlayer2.animeplayer"
OBJECT_PATH = "/org/mpris/MediaPlayer2"


class MediaSession(QObject):
    action = Signal(str)
    raiseRequested = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.title = ""
        self.subtitle = ""
        self.art_url = ""
        self.length_us = 0
        self.status = "Stopped"          # MPRIS's words: Playing, Paused, Stopped
        self.can_next = False
        self.can_previous = False
        self._mpris: _Mpris | None = None
        self._win: _WindowsKeys | None = None
        if os.environ.get("ANIMEPLAYER_NO_MEDIA_SESSION"):
            return
        if sys.platform.startswith("linux"):
            self._mpris = _Mpris.start(self)
        elif sys.platform == "win32":
            self._win = _WindowsKeys.start(self)

    @property
    def active(self) -> bool:
        return self.status != "Stopped"

    @Slot(str, str, str, float, bool, bool, bool)
    def update(self, title: str, subtitle: str, art_url: str, length_seconds: float,
               playing: bool, can_next: bool, can_previous: bool) -> None:
        self.title, self.subtitle, self.art_url = title, subtitle, art_url
        self.length_us = int(max(0.0, length_seconds) * 1_000_000)
        self.status = "Playing" if playing else "Paused"
        self.can_next, self.can_previous = can_next, can_previous
        if self._mpris is not None:
            self._mpris.changed()
        if self._win is not None:
            self._win.claim()

    @Slot()
    def clear(self) -> None:
        self.status = "Stopped"
        self.title = self.subtitle = self.art_url = ""
        self.length_us = 0
        if self._mpris is not None:
            self._mpris.changed()
        if self._win is not None:
            self._win.release()

    def shutdown(self) -> None:
        if self._win is not None:
            self._win.release()


# -- Linux: MPRIS -------------------------------------------------------------

try:  # pragma: no cover - depends on the Qt build
    from PySide6.QtDBus import (QDBusAbstractAdaptor, QDBusConnection, QDBusMessage,
                                QDBusObjectPath)
except ImportError:  # noqa: BLE001 -- no QtDBus, no media keys; nothing else changes
    QDBusAbstractAdaptor = None


if QDBusAbstractAdaptor is not None:

    @ClassInfo({"D-Bus Interface": "org.mpris.MediaPlayer2"})
    class _RootAdaptor(QDBusAbstractAdaptor):
        def __init__(self, owner: "_Mpris") -> None:
            super().__init__(owner)
            self._session = owner.session

        @Property(str)
        def Identity(self) -> str:  # noqa: N802 -- MPRIS's names
            return "Anime Player"

        @Property(str)
        def DesktopEntry(self) -> str:  # noqa: N802
            return "io.github.supred.animeplayer"

        @Property(bool)
        def CanQuit(self) -> bool:  # noqa: N802
            return False

        @Property(bool)
        def CanRaise(self) -> bool:  # noqa: N802
            return True

        @Property(bool)
        def HasTrackList(self) -> bool:  # noqa: N802
            return False

        @Property("QStringList")
        def SupportedUriSchemes(self) -> list[str]:  # noqa: N802
            return []

        @Property("QStringList")
        def SupportedMimeTypes(self) -> list[str]:  # noqa: N802
            return []

        @Slot()
        def Raise(self) -> None:  # noqa: N802
            self._session.raiseRequested.emit()

        @Slot()
        def Quit(self) -> None:  # noqa: N802
            pass

    @ClassInfo({"D-Bus Interface": "org.mpris.MediaPlayer2.Player"})
    class _PlayerAdaptor(QDBusAbstractAdaptor):
        def __init__(self, owner: "_Mpris") -> None:
            super().__init__(owner)
            self._session = owner.session

        @Property(str)
        def PlaybackStatus(self) -> str:  # noqa: N802
            return self._session.status

        @Property("QVariantMap")
        def Metadata(self) -> dict[str, Any]:  # noqa: N802
            return _metadata(self._session)

        @Property(bool)
        def CanControl(self) -> bool:  # noqa: N802
            return True

        @Property(bool)
        def CanPlay(self) -> bool:  # noqa: N802
            return self._session.active

        @Property(bool)
        def CanPause(self) -> bool:  # noqa: N802
            return self._session.active

        @Property(bool)
        def CanGoNext(self) -> bool:  # noqa: N802
            return self._session.can_next

        @Property(bool)
        def CanGoPrevious(self) -> bool:  # noqa: N802
            return self._session.can_previous

        @Property(bool)
        def CanSeek(self) -> bool:  # noqa: N802
            return False

        @Property(float)
        def Rate(self) -> float:  # noqa: N802
            return 1.0

        @Slot()
        def PlayPause(self) -> None:  # noqa: N802
            self._session.action.emit("playpause")

        @Slot()
        def Play(self) -> None:  # noqa: N802
            self._session.action.emit("play")

        @Slot()
        def Pause(self) -> None:  # noqa: N802
            self._session.action.emit("pause")

        @Slot()
        def Stop(self) -> None:  # noqa: N802
            self._session.action.emit("pause")

        @Slot()
        def Next(self) -> None:  # noqa: N802
            self._session.action.emit("next")

        @Slot()
        def Previous(self) -> None:  # noqa: N802
            self._session.action.emit("previous")


def _metadata(session: MediaSession) -> dict[str, Any]:
    if not session.active:
        return {}
    data: dict[str, Any] = {
        "mpris:trackid": QDBusObjectPath("/io/github/supred/animeplayer/current"),
        "xesam:title": session.subtitle or session.title,
        "xesam:album": session.title,
        "xesam:artist": [session.title],
    }
    if session.length_us:
        data["mpris:length"] = session.length_us
    if session.art_url:
        data["mpris:artUrl"] = session.art_url
    return data


class _Mpris(QObject):
    """The object on the bus; the two adaptors above are its interfaces."""

    def __init__(self, session: MediaSession) -> None:
        super().__init__(session)
        self.session = session
        self.bus = QDBusConnection.sessionBus()

    @classmethod
    def start(cls, session: MediaSession) -> "_Mpris | None":
        if QDBusAbstractAdaptor is None:
            return None
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return None
        mpris = cls(session)
        _RootAdaptor(mpris)
        _PlayerAdaptor(mpris)
        if not bus.registerObject(OBJECT_PATH, mpris, QDBusConnection.RegisterOption.ExportAdaptors):
            return None
        # A second copy of the app (or a test run beside the real one) takes
        # a name of its own, as MPRIS allows, rather than none.
        if not bus.registerService(BUS_NAME) \
                and not bus.registerService(f"{BUS_NAME}.instance{os.getpid()}"):
            bus.unregisterObject(OBJECT_PATH)
            return None
        return mpris

    def changed(self) -> None:
        """Tells whoever is listening (the media widget) what changed."""
        session = self.session
        props = {
            "PlaybackStatus": session.status,
            "Metadata": _metadata(session),
            "CanPlay": session.active,
            "CanPause": session.active,
            "CanGoNext": session.can_next,
            "CanGoPrevious": session.can_previous,
        }
        message = QDBusMessage.createSignal(OBJECT_PATH, "org.freedesktop.DBus.Properties",
                                            "PropertiesChanged")
        message.setArguments(["org.mpris.MediaPlayer2.Player", props, []])
        self.bus.send(message)


# -- Windows: the media keys ---------------------------------------------------

_WM_HOTKEY = 0x0312
_MOD_NOREPEAT = 0x4000
_KEYS = {0xB3: "playpause", 0xB0: "next", 0xB1: "previous", 0xB2: "pause"}   # VK_MEDIA_*


class _WindowsKeys:  # pragma: no cover - Windows only
    """RegisterHotKey on the GUI thread: Windows then posts WM_HOTKEY to
    this thread wherever the focus is, and Qt's event loop hands every
    message it pulls to the native event filter below."""

    def __init__(self, session: MediaSession) -> None:
        import ctypes
        from ctypes import wintypes

        from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication

        self._user32 = ctypes.windll.user32
        self._msg_type = wintypes.MSG
        self._claimed = False
        keys = self

        class Filter(QAbstractNativeEventFilter):
            def nativeEventFilter(self, event_type, message):  # noqa: N802 -- Qt's name
                if bytes(event_type) != b"windows_generic_MSG":
                    return False, 0
                msg = keys._msg_type.from_address(int(message))
                if msg.message == _WM_HOTKEY and msg.wParam in _KEYS:
                    session.action.emit(_KEYS[msg.wParam])
                    return True, 0
                return False, 0

        self._filter = Filter()
        QCoreApplication.instance().installNativeEventFilter(self._filter)

    @classmethod
    def start(cls, session: MediaSession) -> "_WindowsKeys | None":
        try:
            return cls(session)
        except Exception:  # noqa: BLE001 -- no media keys rather than no app
            return None

    def claim(self) -> None:
        if self._claimed:
            return
        self._claimed = True
        for vk in _KEYS:
            # The id is the key itself; fails quietly if another app holds it.
            self._user32.RegisterHotKey(None, vk, _MOD_NOREPEAT, vk)

    def release(self) -> None:
        if not self._claimed:
            return
        self._claimed = False
        for vk in _KEYS:
            self._user32.UnregisterHotKey(None, vk)
