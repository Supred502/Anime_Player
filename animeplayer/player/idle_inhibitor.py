"""Keeps the screen awake while an episode is actually playing.

mpv's own ``--stop-screensaver`` cannot do this job here. That option works
through the video output's own window, and this app renders through mpv's
render API with ``vo=libmpv`` (see mpv_video_item.py), so mpv has no window
of its own to hang an inhibition on. Nothing else in the app was telling the
desktop that anything was happening either -- playback produces no input
events -- so the session went idle mid-episode and the screen blanked.

**Why two interfaces rather than one.** Which inhibition interface a desktop
actually honours is not discoverable at runtime. Checked live on Plasma 6:
``org.freedesktop.ScreenSaver``, ``org.freedesktop.PowerManagement.Inhibit``
and KDE's own ``PolicyAgent.AddInhibition`` all return a valid cookie, while
PowerDevil's own ``ListInhibitions`` and ``HasInhibit`` readouts report none
of them (they only show inhibitions made through the Wayland idle-inhibit
protocol). So there is no way to ask the session which one is real. Both
freedesktop interfaces are asked; they are the two every portable media
player uses, and on a desktop that implements neither, both calls simply
fail and are ignored. KDE's PolicyAgent is deliberately left out: its
``AddInhibition`` takes a uint32, which PySide6 cannot marshal (see below).

**Why release by dropping the connection.** Each inhibition is held on a
dedicated D-Bus connection and released by disconnecting it, not by calling
``UnInhibit``. Two reasons, both established live:

* A session-bus service drops a client's inhibitions when that client's
  connection goes away. Tying the inhibition to a connection we own means a
  crash cannot strand the machine in a permanent "never sleep" state -- the
  worst failure mode this file could have.
* ``UnInhibit`` takes a uint32 cookie and PySide6 marshals Python ints as
  int32, so the call fails outright with
  ``No such method 'UnInhibit' ... (signature 'i')``. Releasing that way
  would have silently never released at all.
"""

from __future__ import annotations

import sys

if sys.platform != "win32":
    from PySide6.QtDBus import QDBusConnection, QDBusInterface

_APP_NAME = "Anime Player"

# (service, object path, interface) -- both take Inhibit(app_name, reason).
_TARGETS = (
    (
        "org.freedesktop.ScreenSaver",
        "/org/freedesktop/ScreenSaver",
        "org.freedesktop.ScreenSaver",
    ),
    (
        "org.freedesktop.PowerManagement.Inhibit",
        "/org/freedesktop/PowerManagement/Inhibit",
        "org.freedesktop.PowerManagement.Inhibit",
    ),
)

_CONNECTION_NAME = "animeplayer-idle-inhibit"

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002


def _set_execution_state(flags: int) -> int:
    import ctypes
    return ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags))


class IdleInhibitor:
    """Holds a "don't blank the screen" request for as long as it's wanted.

    inhibit()/release() are both idempotent, so callers can drive this
    straight from a boolean ("is an episode playing right now") without
    tracking state themselves.
    """

    def __init__(self) -> None:
        self._connection_name: str | None = None
        self._windows_held = False

    @property
    def active(self) -> bool:
        return self._connection_name is not None or self._windows_held

    def inhibit(self, reason: str = "Playing video") -> None:
        if self.active:
            return
        if sys.platform == "win32":
            # Windows has no D-Bus: SetThreadExecutionState is its "a video
            # is playing" switch. Held by the calling thread (the GUI
            # thread, which lives as long as the app) and dropped by Windows
            # if the process dies, so a crash can't leave the PC awake.
            self._windows_held = bool(_set_execution_state(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED
                                                           | _ES_DISPLAY_REQUIRED))
            return
        name = f"{_CONNECTION_NAME}-{id(self)}"
        bus = QDBusConnection.connectToBus(QDBusConnection.BusType.SessionBus, name)
        if not bus.isConnected():
            QDBusConnection.disconnectFromBus(name)
            return
        granted = False
        for service, path, interface in _TARGETS:
            reply = QDBusInterface(service, path, interface, bus).call(
                "Inhibit", _APP_NAME, reason
            )
            # A desktop that doesn't implement one of these answers with an
            # error; that's expected, not a problem, as long as one lands.
            if not reply.errorMessage():
                granted = True
        if not granted:
            QDBusConnection.disconnectFromBus(name)
            return
        self._connection_name = name

    def release(self) -> None:
        if self._windows_held:
            _set_execution_state(_ES_CONTINUOUS)
            self._windows_held = False
            return
        if self._connection_name is None:
            return
        # Dropping the connection is the release -- see the module docstring.
        QDBusConnection.disconnectFromBus(self._connection_name)
        self._connection_name = None
