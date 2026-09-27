"""Game controllers: Xbox, PlayStation, Switch Pro, the Steam Deck (which
Steam presents to other apps as an Xbox pad), and anything else SDL knows.

SDL, the library most games read controllers through, maps every one of
them to the same Xbox-style layout, so the rest of the app deals in a
handful of named actions and never sees a device:

    up down left right   D-pad, or the left stick
    accept back          A, B  (Cross, Circle on PlayStation)
    x y                  X, Y  (Square, Triangle)
    lb rb lt rt          bumpers and triggers
    menu view            Start, Back/Select (Options, Share)

Directions and triggers repeat while held, as a keyboard key does. What
each action does is up to the QML (see GamepadNav.qml).

SDL is polled from a timer on the GUI thread. If it isn't installed, or no
controller is ever plugged in, none of this does anything.

Steam's desktop layout -- the Deck in Desktop Mode, or any controller while
Steam runs, for an app Steam didn't start -- also turns the D-pad into arrow
keys, A into Enter, B into Escape and the stick into a scroll wheel. The app
would get every press twice: the highlight moves and the page scrolls on
its own, B goes back twice. `filter_window` drops those keys and wheel
turns while the controller is in use.
"""

from __future__ import annotations

import os
import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication

try:  # pragma: no cover - depends on the platform's SDL
    import warnings
    with warnings.catch_warnings():
        # "Using SDL2 binaries from pysdl2-dll": expected, and on every start.
        warnings.simplefilter("ignore", UserWarning)
        import sdl2
except Exception:  # noqa: BLE001 -- no SDL means no controller support, not a crash
    sdl2 = None

STICK_THRESHOLD = 0.55       # of full tilt, before a stick counts as a direction
TRIGGER_THRESHOLD = 0.5
REPEAT_DELAY = 0.38          # seconds held before a direction repeats
REPEAT_INTERVAL = 0.11

_BUTTONS = {}
if sdl2 is not None:
    _BUTTONS = {
        sdl2.SDL_CONTROLLER_BUTTON_DPAD_UP: "up",
        sdl2.SDL_CONTROLLER_BUTTON_DPAD_DOWN: "down",
        sdl2.SDL_CONTROLLER_BUTTON_DPAD_LEFT: "left",
        sdl2.SDL_CONTROLLER_BUTTON_DPAD_RIGHT: "right",
        sdl2.SDL_CONTROLLER_BUTTON_A: "accept",
        sdl2.SDL_CONTROLLER_BUTTON_B: "back",
        sdl2.SDL_CONTROLLER_BUTTON_X: "x",
        sdl2.SDL_CONTROLLER_BUTTON_Y: "y",
        sdl2.SDL_CONTROLLER_BUTTON_LEFTSHOULDER: "lb",
        sdl2.SDL_CONTROLLER_BUTTON_RIGHTSHOULDER: "rb",
        sdl2.SDL_CONTROLLER_BUTTON_START: "menu",
        sdl2.SDL_CONTROLLER_BUTTON_BACK: "view",
    }
_REPEATING = {"up", "down", "left", "right", "lt", "rt"}

# What Steam types for the controller, and how long after the controller's
# last use a key or wheel turn is still taken to be Steam's. Holding a
# direction repeats well within it.
_STEAM_KEYS = {Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right,
               Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape, Qt.Key.Key_Space,
               Qt.Key.Key_Tab, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown}
IN_USE_WINDOW = 0.6


class Gamepad(QObject):
    """Exposed to QML as `gamepad`."""

    action = Signal(str)
    connected = Signal(str)     # the controller's name
    disconnected = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._controllers: dict[int, object] = {}
        self._held: dict[str, float] = {}      # action -> when it next repeats
        self._stick: dict[str, bool] = {}      # which stick/trigger directions are past threshold
        self._last_used = 0.0                   # time.monotonic() of the last action
        self._simulated = False
        self.available = False
        if sdl2 is None or os.environ.get("ANIMEPLAYER_NO_GAMEPAD"):
            return
        # Controllers are read whether or not a window has focus; the app
        # ignores them itself while it's in the background (see _emit).
        sdl2.SDL_SetHint(sdl2.SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, b"1")
        if sdl2.SDL_Init(sdl2.SDL_INIT_GAMECONTROLLER) != 0:
            return
        self.available = True
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self.poll)
        self._timer.start()

    @Slot(result=bool)
    def isConnected(self) -> bool:
        return bool(self._controllers)

    def _emit(self, name: str) -> None:
        # Not while another app is in front. Compared with the enum itself:
        # against the number 4 it never matched in PySide6 6.11 (its enums
        # aren't ints), so every action was dropped as "in the background"
        # -- the controller did nothing in the app, while the test drivers,
        # which skip this check, worked.
        app = QGuiApplication.instance()
        if (app is not None and app.applicationState() != Qt.ApplicationState.ApplicationActive
                and not os.environ.get("ANIMEPLAYER_DB_PATH")):
            return
        self.action.emit(name)

    def _press(self, name: str) -> None:
        self._last_used = time.monotonic()
        self._emit(name)
        if name in _REPEATING:
            self._held[name] = time.monotonic() + REPEAT_DELAY

    def _release(self, name: str) -> None:
        self._held.pop(name, None)

    def _axis(self, name: str, pushed: bool) -> None:
        if pushed and not self._stick.get(name):
            self._stick[name] = True
            self._press(name)
        elif not pushed and self._stick.get(name):
            self._stick[name] = False
            self._release(name)

    @Slot()
    def poll(self) -> None:
        if sdl2 is None:
            return
        event = sdl2.SDL_Event()
        while sdl2.SDL_PollEvent(event):
            kind = event.type
            if kind == sdl2.SDL_CONTROLLERDEVICEADDED:
                index = event.cdevice.which
                if sdl2.SDL_IsGameController(index):
                    pad = sdl2.SDL_GameControllerOpen(index)
                    if pad:
                        joystick = sdl2.SDL_GameControllerGetJoystick(pad)
                        self._controllers[sdl2.SDL_JoystickInstanceID(joystick)] = pad
                        name = sdl2.SDL_GameControllerName(pad)
                        self.connected.emit(name.decode("utf-8", "replace") if name else "Controller")
            elif kind == sdl2.SDL_CONTROLLERDEVICEREMOVED:
                pad = self._controllers.pop(event.cdevice.which, None)
                if pad is not None:
                    sdl2.SDL_GameControllerClose(pad)
                    self._held.clear()
                    self._stick.clear()
                    self.disconnected.emit()
            elif kind == sdl2.SDL_CONTROLLERBUTTONDOWN:
                name = _BUTTONS.get(event.cbutton.button)
                if name:
                    self._press(name)
            elif kind == sdl2.SDL_CONTROLLERBUTTONUP:
                name = _BUTTONS.get(event.cbutton.button)
                if name:
                    self._release(name)
            elif kind == sdl2.SDL_CONTROLLERAXISMOTION:
                value = event.caxis.value / 32767.0
                axis = event.caxis.axis
                if axis == sdl2.SDL_CONTROLLER_AXIS_LEFTX:
                    self._axis("left", value < -STICK_THRESHOLD)
                    self._axis("right", value > STICK_THRESHOLD)
                elif axis == sdl2.SDL_CONTROLLER_AXIS_LEFTY:
                    self._axis("up", value < -STICK_THRESHOLD)
                    self._axis("down", value > STICK_THRESHOLD)
                elif axis == sdl2.SDL_CONTROLLER_AXIS_TRIGGERLEFT:
                    self._axis("lt", value > TRIGGER_THRESHOLD)
                elif axis == sdl2.SDL_CONTROLLER_AXIS_TRIGGERRIGHT:
                    self._axis("rt", value > TRIGGER_THRESHOLD)
        now = time.monotonic()
        for name, due in list(self._held.items()):
            if now >= due:
                self._last_used = now
                self._emit(name)
                self._held[name] = now + REPEAT_INTERVAL

    @Slot(str)
    def simulate(self, name: str) -> None:
        """A press and release of `name`, as if from a controller. For the
        test drivers."""
        self._simulated = True
        self._press(name)
        self._release(name)

    def in_use(self) -> bool:
        """Being pressed now, or a moment ago. Asks SDL for the buttons' state
        as it is right now: Steam's key can arrive before this app's next
        poll has seen the press it came from."""
        if not self._controllers and not self._simulated:
            return False
        if self._held or any(self._stick.values()):
            return True
        if time.monotonic() - self._last_used < IN_USE_WINDOW:
            return True
        sdl2.SDL_GameControllerUpdate()
        for pad in self._controllers.values():
            for button in _BUTTONS:
                if sdl2.SDL_GameControllerGetButton(pad, button):
                    return True
            for axis in (sdl2.SDL_CONTROLLER_AXIS_LEFTX, sdl2.SDL_CONTROLLER_AXIS_LEFTY):
                if abs(sdl2.SDL_GameControllerGetAxis(pad, axis)) / 32767.0 > STICK_THRESHOLD:
                    return True
        return False

    def filter_window(self, window: QObject) -> None:
        """Drops Steam's doubles of controller presses (see the top)."""
        if self.available:
            window.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 -- Qt's name
        kind = event.type()
        if kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease, QEvent.Type.ShortcutOverride):
            # spontaneous(): from a device. The app's own keys (B closing a
            # menu with Escape) are sent directly, and pass.
            if event.spontaneous() and event.key() in _STEAM_KEYS and self.in_use():
                return True
        elif kind == QEvent.Type.Wheel:
            if event.spontaneous() and self.in_use():
                return True
        return False

    def shutdown(self) -> None:
        if sdl2 is not None and self.available:
            for pad in self._controllers.values():
                sdl2.SDL_GameControllerClose(pad)
            self._controllers.clear()
            sdl2.SDL_Quit()
