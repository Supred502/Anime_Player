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
"""

from __future__ import annotations

import os
import time

from PySide6.QtCore import QObject, QTimer, Signal, Slot
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
        app = QGuiApplication.instance()
        if app is not None and app.applicationState() != 4 and not os.environ.get("ANIMEPLAYER_DB_PATH"):
            return  # Qt.ApplicationActive is 4: not while another app is in front
        self.action.emit(name)

    def _press(self, name: str) -> None:
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
                self._emit(name)
                self._held[name] = now + REPEAT_INTERVAL

    def shutdown(self) -> None:
        if sdl2 is not None and self.available:
            for pad in self._controllers.values():
                sdl2.SDL_GameControllerClose(pad)
            self._controllers.clear()
            sdl2.SDL_Quit()
