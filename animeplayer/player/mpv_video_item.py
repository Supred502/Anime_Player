"""Embeds mpv playback inside the QML scene graph via mpv's OpenGL render API.

mpv/ani-cli's usual trick of embedding via a native window id (``--wid``) only
works on X11 -- it silently doesn't apply under native Wayland, which is what
Fedora KDE Plasma sessions run by default. Using mpv's render API (an OpenGL
FBO callback interface) instead of window embedding is the approach mpv's own
Qt-embedding docs and KDE's own mpv-based player (Haruna) use, and it works
identically under X11 and Wayland.
"""

from __future__ import annotations

import mpv
from PySide6.QtCore import Property, Signal, Slot
from PySide6.QtGui import QOpenGLContext
from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
from PySide6.QtQuick import QQuickFramebufferObject


def _get_proc_address(_ctx: int, name: bytes) -> int:
    ctx = QOpenGLContext.currentContext()
    if ctx is None:
        return 0
    addr = ctx.getProcAddress(name.decode("utf-8"))
    return int(addr) if addr else 0


# Kept as a module-level CFUNCTYPE instance per-item (see MpvVideoItem.__init__):
# ctypes does not keep a Python callable alive once wrapped, so the wrapped
# function object itself must be held onto for the lifetime of the render context.
_GetProcAddressFn = mpv.MpvGlGetProcAddressFn


class _MpvRenderer(QQuickFramebufferObject.Renderer):
    def __init__(self, item: "MpvVideoItem") -> None:
        super().__init__()
        self._item = item
        self._render_ctx: mpv.MpvRenderContext | None = None
        # QOpenGLFramebufferObject isn't a QObject, so PySide6 doesn't transfer
        # its ownership to the C++ side on return -- without this reference the
        # Python GC frees it right after createFramebufferObject() returns,
        # leaving Qt's QSGRenderThread holding a dangling pointer (segfaults in
        # QOpenGLFramebufferObject::texture() on the next paint).
        self._fbo: QOpenGLFramebufferObject | None = None

    def createFramebufferObject(self, size):
        fmt = QOpenGLFramebufferObjectFormat()
        fmt.setSamples(0)
        self._fbo = QOpenGLFramebufferObject(size, fmt)
        return self._fbo

    def render(self) -> None:
        if self._render_ctx is None:
            self._render_ctx = mpv.MpvRenderContext(
                self._item.mpv,
                "opengl",
                opengl_init_params={"get_proc_address": self._item.proc_address_fn},
            )
            self._render_ctx.update_cb = self._on_render_update

        if self._item.closed:
            return

        fbo = self.framebufferObject()
        self._render_ctx.render(
            flip_y=False,
            opengl_fbo={"w": fbo.width(), "h": fbo.height(), "fbo": fbo.handle()},
        )

    def synchronize(self, item) -> None:  # noqa: D401 -- Qt override, nothing to sync yet
        pass

    def _on_render_update(self) -> None:
        # Called from mpv's internal thread. self._item.closed is a plain Python
        # bool, safe to read from any thread; skip emitting once the QML item is
        # gone, since emit() on a signal whose C++ QObject is deleted raises.
        if not self._item.closed:
            self._item.frameReady.emit()


class MpvVideoItem(QQuickFramebufferObject):
    """QML-facing video surface. Register via qmlRegisterType before use."""

    frameReady = Signal()
    positionChanged = Signal(float)
    durationChanged = Signal(float)
    pausedChanged = Signal(bool)
    volumeChanged = Signal(float)
    endOfFile = Signal()
    playbackError = Signal(str)  # a real mpv-reported error, e.g. a dead/stalled stream

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.frameReady.connect(self.update)
        self.proc_address_fn = _GetProcAddressFn(_get_proc_address)

        self._position = 0.0
        self._duration = 0.0
        self._paused = True
        self._volume = 100.0
        # Set once close() runs (page popped / item destroyed) so any callback
        # still in flight on mpv's own threads bails out before touching a
        # signal whose underlying QObject Qt may have already deleted -- see
        # close() below.
        self.closed = False

        # mpv previously failed completely silently on a bad/stalled stream --
        # the UI just sat at "Loading video..." forever with nothing in the
        # logs to explain why. log_handler surfaces mpv's own error/warning
        # messages (e.g. HLS fetch failures) up to the QML layer instead.
        self.mpv = mpv.MPV(
            vo="libmpv", ytdl=False, hwdec="auto", keep_open="yes",
            # mpv's default (keep-open-pause=yes) carries the paused state from
            # one episode's end-of-file straight into the *next* loaded file --
            # confirmed in mpv's own docs. Without this, auto-play-next loaded
            # the next episode correctly but silently sat there paused instead
            # of actually playing.
            keep_open_pause="no",
            log_handler=self._on_mpv_log, msg_level="all=warn",
        )
        self.mpv.observe_property("time-pos", self._on_time_pos)
        self.mpv.observe_property("duration", self._on_duration)
        self.mpv.observe_property("pause", self._on_pause)
        self.mpv.observe_property("eof-reached", self._on_eof)
        self.mpv.observe_property("volume", self._on_volume)

        @self.mpv.event_callback("end-file")
        def _on_end_file(event) -> None:
            if self.closed:
                return
            data = event.get("event", {}) if isinstance(event, dict) else {}
            reason = data.get("reason")
            if reason == "error":
                error = data.get("error", "unknown error")
                self.playbackError.emit(f"mpv stopped playback: {error}")

    # Property callbacks fire on mpv's internal event thread. Mutating these
    # plain attributes from there is safe under CPython's GIL (assignment is
    # atomic); QML picks up the change via the *Changed signal, which is
    # itself safe to emit cross-thread.
    def _on_time_pos(self, _name: str, value) -> None:
        if not self.closed and value is not None:
            self._position = float(value)
            self.positionChanged.emit(self._position)

    def _on_duration(self, _name: str, value) -> None:
        if not self.closed and value is not None:
            self._duration = float(value)
            self.durationChanged.emit(self._duration)

    def _on_pause(self, _name: str, value) -> None:
        if not self.closed:
            self._paused = bool(value)
            self.pausedChanged.emit(self._paused)

    def _on_eof(self, _name: str, value) -> None:
        if not self.closed and value:
            self.endOfFile.emit()

    def _on_volume(self, _name: str, value) -> None:
        if not self.closed and value is not None:
            self._volume = float(value)
            self.volumeChanged.emit(self._volume)

    def _on_mpv_log(self, level: str, prefix: str, text: str) -> None:
        # Fires on mpv's own log thread. Only surface real problems (error/fatal)
        # to the UI -- "warn" is noisy and mostly benign (codec probing, etc).
        if not self.closed and level in ("error", "fatal"):
            self.playbackError.emit(text.strip())

    def createRenderer(self):
        return _MpvRenderer(self)

    @Slot()
    def close(self) -> None:
        """Must be called (e.g. from QML's Component.onDestruction) before this
        item is destroyed. Without it, mpv's internal threads keep running and
        their callbacks keep firing into a Python wrapper whose underlying
        QObject Qt has deleted -- which reliably corrupts state and can crash
        the process, not just raise a caught exception.

        This stops playback (self.mpv.stop()) rather than fully tearing down
        the mpv core (self.mpv.terminate()). libmpv aborts inside mp_destroy()
        if its render context hasn't been freed first, and freeing that render
        context correctly requires the exact OpenGL context that's only ever
        current on Qt's render thread during a render() call -- not safely
        reachable from here (this runs on the GUI thread, from QML's
        Component.onDestruction). stop() halts audio/decoding without hitting
        that path; the mpv core and render context are leaked (idle) until the
        process exits rather than being cleanly freed per-item."""
        if self.closed:
            return
        self.closed = True
        self.mpv.stop()

    def getPosition(self) -> float:
        return self._position

    def getDuration(self) -> float:
        return self._duration

    def getPaused(self) -> bool:
        return self._paused

    def getVolume(self) -> float:
        return self._volume

    position = Property(float, getPosition, notify=positionChanged)
    duration = Property(float, getDuration, notify=durationChanged)
    paused = Property(bool, getPaused, notify=pausedChanged)
    volume = Property(float, getVolume, notify=volumeChanged)

    @Slot(float)
    def setVolume(self, value: float) -> None:
        if not self.closed:
            self.mpv.volume = max(0.0, min(100.0, value))

    @Slot(str)
    def loadUrl(self, url: str) -> None:
        if not self.closed:
            self.mpv.play(url)

    @Slot()
    def togglePause(self) -> None:
        if not self.closed:
            self.mpv.pause = not self.mpv.pause

    @Slot(bool)
    def setPaused(self, paused: bool) -> None:
        if not self.closed:
            self.mpv.pause = paused

    @Slot(float)
    def seekAbsolute(self, seconds: float) -> None:
        if not self.closed:
            # Plain "absolute" seeking snaps to the nearest keyframe rather
            # than decoding to the exact target -- on these HLS streams that
            # reliably desyncs audio from video, worse when seeking backward
            # (matches what the user reported, and the same known behavior
            # ani-cli/mpv have on this kind of segmented stream). "exact"
            # forces mpv to actually decode forward to the precise target
            # instead of snapping, which keeps audio and video aligned.
            self.mpv.command("seek", str(seconds), "absolute+exact")

    @Slot()
    def stop(self) -> None:
        if not self.closed:
            self.mpv.stop()
