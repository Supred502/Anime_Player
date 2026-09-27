"""The controller layer, fed SDL events the way a real controller produces
them (SDL lets a program push events into its own queue)."""

import time

import pytest

from animeplayer import gamepad as gp

pytestmark = pytest.mark.skipif(gp.sdl2 is None, reason="SDL isn't installed")
sdl2 = gp.sdl2


@pytest.fixture
def pad(monkeypatch):
    monkeypatch.setenv("ANIMEPLAYER_DB_PATH", "x")   # skip the "app in front" check
    g = gp.Gamepad()
    if not g.available:
        pytest.skip("SDL couldn't start")
    got = []
    g.action.connect(got.append)
    g._timer.stop()
    yield g, got
    g.shutdown()


def push_button(button, down=True):
    e = sdl2.SDL_Event()
    e.type = sdl2.SDL_CONTROLLERBUTTONDOWN if down else sdl2.SDL_CONTROLLERBUTTONUP
    e.cbutton.button = button
    sdl2.SDL_PushEvent(e)


def push_axis(axis, value):
    e = sdl2.SDL_Event()
    e.type = sdl2.SDL_CONTROLLERAXISMOTION
    e.caxis.axis = axis
    e.caxis.value = value
    sdl2.SDL_PushEvent(e)


def test_buttons_become_actions(pad):
    g, got = pad
    for b in (sdl2.SDL_CONTROLLER_BUTTON_A, sdl2.SDL_CONTROLLER_BUTTON_B, sdl2.SDL_CONTROLLER_BUTTON_START,
              sdl2.SDL_CONTROLLER_BUTTON_LEFTSHOULDER):
        push_button(b)
        push_button(b, down=False)
    g.poll()
    assert got == ["accept", "back", "menu", "lb"]


def test_stick_is_a_direction_once_past_the_threshold(pad):
    g, got = pad
    push_axis(sdl2.SDL_CONTROLLER_AXIS_LEFTX, 8000)      # a small nudge: nothing
    push_axis(sdl2.SDL_CONTROLLER_AXIS_LEFTX, 30000)     # pushed right
    push_axis(sdl2.SDL_CONTROLLER_AXIS_LEFTX, 31000)     # still right: not again
    push_axis(sdl2.SDL_CONTROLLER_AXIS_LEFTX, 0)         # let go
    push_axis(sdl2.SDL_CONTROLLER_AXIS_LEFTY, -30000)    # up
    push_axis(sdl2.SDL_CONTROLLER_AXIS_TRIGGERRIGHT, 30000)
    g.poll()
    assert got == ["right", "up", "rt"]


def test_holding_a_direction_repeats(pad, monkeypatch):
    g, got = pad
    monkeypatch.setattr(gp, "REPEAT_DELAY", 0.05)
    monkeypatch.setattr(gp, "REPEAT_INTERVAL", 0.02)
    push_button(sdl2.SDL_CONTROLLER_BUTTON_DPAD_DOWN)
    g.poll()
    time.sleep(0.2)
    for _ in range(5):
        g.poll()
        time.sleep(0.03)
    push_button(sdl2.SDL_CONTROLLER_BUTTON_DPAD_DOWN, down=False)
    g.poll()
    count = len(got)
    g.poll()
    assert got[0] == "down" and count >= 3 and len(got) == count


def test_actions_reach_the_app_when_it_is_in_front(monkeypatch):
    """Without the test drivers' bypass. The check used to compare the
    app's state with the number 4, which never matched PySide6's enum, so
    the real app dropped every action."""
    from PySide6.QtCore import Qt
    monkeypatch.delenv("ANIMEPLAYER_DB_PATH", raising=False)

    class FakeApp:
        state = Qt.ApplicationState.ApplicationActive
        def applicationState(self):
            return self.state

    fake = FakeApp()
    monkeypatch.setattr(gp.QGuiApplication, "instance", staticmethod(lambda: fake))
    g = gp.Gamepad.__new__(gp.Gamepad)
    gp.QObject.__init__(g)
    got = []
    g.action.connect(got.append)
    g._emit("accept")
    fake.state = Qt.ApplicationState.ApplicationInactive
    g._emit("back")
    assert got == ["accept"]
