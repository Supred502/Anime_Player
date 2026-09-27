"""Embeds mpv playback inside the QML scene graph via mpv's OpenGL render API.

mpv/ani-cli's usual trick of embedding via a native window id (``--wid``) only
works on X11 -- it silently doesn't apply under native Wayland, which is what
Fedora KDE Plasma sessions run by default. Using mpv's render API (an OpenGL
FBO callback interface) instead of window embedding is the approach mpv's own
Qt-embedding docs and KDE's own mpv-based player (Haruna) use, and it works
identically under X11 and Wayland.
"""

from __future__ import annotations

import weakref

import mpv
from PySide6.QtCore import Property, QTimer, Signal, Slot
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
            # Tells the item it is now safe to start playing. Until this
            # exists, mpv has nowhere to put video and fails the file outright
            # with "Error opening/initializing the selected video_out (--vo)
            # device" -- see MpvVideoItem.loadUrl.
            self._item.render_ready = True

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
    mutedChanged = Signal(bool)
    endOfFile = Signal()
    playbackError = Signal(str)  # a real mpv-reported error, e.g. a dead/stalled stream
    # Internal: emitted from mpv's event thread, handled on the GUI thread.
    fileLoaded = Signal()

    # Every player alive, so quitting can stop them all -- see close_all().
    _live: "weakref.WeakSet[MpvVideoItem]" = weakref.WeakSet()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        MpvVideoItem._live.add(self)
        self.frameReady.connect(self.update)
        self.fileLoaded.connect(self._attach_pending_subtitle)
        self.proc_address_fn = _GetProcAddressFn(_get_proc_address)

        # Set from the render thread once mpv's render context exists. A plain
        # bool, so reading it from the GUI thread is safe under the GIL.
        self.render_ready = False
        self._pending_url = ""
        self._render_waited_ms = 0

        self._position = 0.0
        self._duration = 0.0
        self._paused = True
        self._volume = 100.0
        self._muted = False
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
            # ffmpeg probes the start of a stream to work out what is in it,
            # and its defaults are tuned for arbitrary local files rather than
            # for an HLS playlist whose codecs are already declared. Measured
            # live against a real episode, three runs each: 847ms to first
            # frame on the defaults, 783ms with these -- and the track list
            # comes out identical (h264 + aac on every variant), which is the
            # thing a too-small probe would break.
            demuxer_lavf_probesize=32768,
            demuxer_lavf_analyzeduration=0.3,
            log_handler=self._on_mpv_log, msg_level="all=warn",
        )
        self.mpv.observe_property("time-pos", self._on_time_pos)
        self.mpv.observe_property("duration", self._on_duration)
        self.mpv.observe_property("pause", self._on_pause)
        self.mpv.observe_property("eof-reached", self._on_eof)
        self.mpv.observe_property("volume", self._on_volume)
        self.mpv.observe_property("mute", self._on_mute)

        # Set by loadUrl, consumed on the next file-loaded. Attaching the
        # track any earlier doesn't work -- see loadUrl's docstring.
        self._pending_subtitle = ""
        # Whether the current file has finished opening. A subtitle added
        # before then is listed but never selected -- measured: the dub's
        # English, added 0.15 s after the stream arrived, came up
        # "selected: False" and never showed.
        self._file_ready = False

        @self.mpv.event_callback("file-loaded")
        def _on_file_loaded(_event) -> None:
            self._file_ready = True
            if self.closed or not self._pending_subtitle:
                return
            # Deliberately only *signals* from here. Issuing the sub-add
            # command directly on mpv's event thread fails with a bare
            # MPV_ERROR_COMMAND (-12) in the real app -- confirmed live, and
            # confirmed to be about the calling thread rather than the
            # subtitle itself, since the identical command on the identical
            # URL succeeds when it isn't run from inside an event callback.
            # mpv's own API docs warn against calling back into it from an
            # event callback for exactly this reason. The signal hop hands
            # the command to the GUI thread, the same trick the property
            # callbacks below already rely on.
            self.fileLoaded.emit()

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

    def _on_mute(self, _name: str, value) -> None:
        if not self.closed and value is not None:
            self._muted = bool(value)
            self.mutedChanged.emit(self._muted)

    def _on_mpv_log(self, level: str, prefix: str, text: str) -> None:
        # Fires on mpv's own log thread. Only surface real problems (error/fatal)
        # to the UI -- "warn" is noisy and mostly benign (codec probing, etc).
        if self.closed or level not in ("error", "fatal"):
            return
        # Some FFmpeg decoder messages are logged at "error" level even though
        # they're recoverable hiccups that don't actually stop playback --
        # confirmed live: "aac: illegal icc" fires from a stray AAC stream
        # quirk on these episodes and decoding just continues fine right
        # through it, but it was popping up as an alarming "Playback
        # error" toast on otherwise-working playback. Filtered by substring
        # rather than dropping error-level entirely, since other error-level
        # messages (dead streams, unsupported codecs) are genuinely useful --
        # confirmed in an earlier round of debugging the stuck-at-0:00 bug.
        if "illegal icc" in text:
            return
        self.playbackError.emit(text.strip())

    @Slot()
    def _attach_pending_subtitle(self) -> None:
        """Runs on the GUI thread -- see the file-loaded callback above."""
        if self.closed or not self._pending_subtitle:
            return
        subtitle, self._pending_subtitle = self._pending_subtitle, ""
        try:
            self.mpv.command("sub-add", subtitle, "select")
        except Exception as exc:  # noqa: BLE001 -- a missing subtitle must not stop playback
            self.playbackError.emit(f"Couldn't load subtitles: {exc}")

    def createRenderer(self):
        return _MpvRenderer(self)

    @classmethod
    def close_all(cls) -> None:
        """Stops every player, for quitting. Qt doesn't destroy the pages on
        the way out, so their Component.onDestruction -> close() never runs,
        and mpv kept decoding: its video thread then called back into Python
        while the interpreter was shutting down, which crashed every quit
        made during playback (seen in core dumps: PyGILState_Ensure from
        mpv's vo_thread)."""
        for item in list(cls._live):
            item.close()

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

    def getMuted(self) -> bool:
        return self._muted

    muted = Property(bool, getMuted, notify=mutedChanged)

    @Slot(float)
    def setVolume(self, value: float) -> None:
        if not self.closed:
            self.mpv.volume = max(0.0, min(100.0, value))

    @Slot(bool)
    def setMuted(self, value: bool) -> None:
        if not self.closed:
            self.mpv.mute = value

    @Slot(float)
    def setSpeed(self, speed: float) -> None:
        """Playback speed. mpv keeps the pitch natural when slowed down
        (its default audio filter stretches time, not frequency), so voices
        at 0.75x sound slower rather than deeper."""
        if not self.closed:
            self.mpv.speed = max(0.25, min(2.0, speed))

    @Slot(str)
    def addSubtitle(self, url: str) -> None:
        """Adds and selects another subtitle track mid-playback -- the
        English from the subbed version, on a dub. The referer the stream
        was loaded with still applies."""
        if self.closed or not url:
            return
        if not self._file_ready:
            # Attached on file-loaded, like a stream's own subtitle.
            self._pending_subtitle = url
            return
        try:
            self.mpv.command("sub-add", url, "select", "English")
        except Exception:  # noqa: BLE001 -- a bad track must never stop playback
            pass

    @Slot(bool)
    def setSubtitlesVisible(self, visible: bool) -> None:
        if not self.closed:
            self.mpv.sub_visibility = visible

    @Slot(result=str)
    def currentSubtitleText(self) -> str:
        """The English line on screen right now, for a saved word's
        translation. "" between lines."""
        if self.closed:
            return ""
        try:
            return self.mpv.sub_text or ""
        except Exception:  # noqa: BLE001 -- property unavailable with no sub track
            return ""

    @Slot(float, int)
    def setSubtitleStyle(self, scale: float, position: int) -> None:
        """Subtitle size (1.0 = mpv's default) and vertical position (100 =
        the bottom edge, lower numbers move them up the screen). Applied live
        -- no reload -- and to every subtitle track, external ones included."""
        if not self.closed:
            self.mpv.sub_scale = max(0.3, min(3.0, scale))
            self.mpv.sub_pos = max(0, min(150, position))

    @Slot(str, str, str)
    def loadUrl(self, url: str, referer: str = "", subtitle_url: str = "") -> None:
        """Loads a stream, optionally with the referer and external subtitle
        track the source requires.

        Both matter on the current backend and were confirmed live (see
        sources/hianime.py): the stream host 403s every playlist and subtitle
        request that arrives without a Referer, so without it mpv never
        produces a single frame; and subtitles are not in the HLS manifest at
        all, so a "sub" episode plays with no subtitles unless the separate
        WebVTT track is attached.

        The subtitle is attached via sub-add on file-loaded rather than by
        setting mpv's sub-files option before play(). Also confirmed live:
        sub-files set as a property simply never produces a sub track (the
        track list comes back with video and audio only), while sub-add lands
        the track and selects it.
        """
        if self.closed:
            return
        self._pending_subtitle = subtitle_url
        self._file_ready = False
        # A global option rather than a per-file one so it also covers the
        # variant-playlist and segment fetches mpv makes on its own later.
        self.mpv["referrer"] = referer
        self._pending_url = url
        self._start_when_rendered()

    # How long to wait for the scene graph's first paint before giving up and
    # playing anyway. Generous: the alternative to waiting is the error this
    # exists to avoid, and in practice the context arrives within a frame.
    _RENDER_WAIT_MS = 5000

    def _start_when_rendered(self) -> None:
        """Holds the file back until mpv has somewhere to draw it.

        The render context is built on the first paint (see _MpvRenderer), and
        calling play() before that fails the file with "Error
        opening/initializing the selected video_out (--vo) device".

        This never showed up on a streamed episode because resolving a stream
        takes a few hundred milliseconds, by which time the first paint has
        long happened -- it only appeared once episodes could be played from a
        local file, which opens instantly and loses the race.
        """
        if self.closed or not self._pending_url:
            return
        # update() rather than merely waiting: if nothing else invalidates the
        # item, the paint that builds the context might not be scheduled at
        # all.
        self.update()
        if self.render_ready:
            url, self._pending_url = self._pending_url, ""
            self.mpv.play(url)
            return
        self._render_waited_ms += 16
        if self._render_waited_ms >= self._RENDER_WAIT_MS:
            url, self._pending_url = self._pending_url, ""
            self.mpv.play(url)
            return
        QTimer.singleShot(16, self._start_when_rendered)

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
            self._do_seek(seconds)

    def _do_seek(self, seconds: float) -> None:
        if self.closed:
            return
        # Confirmed live against the real HLS streams (muxed MPEG-TS
        # segments, not separate audio/video renditions) with mpv's
        # own audio-pts/time-pos properties: a *single* backward seek --
        # "exact" or not -- reliably leaves the video stream repositioned
        # correctly while the audio demuxer just keeps decoding forward from
        # wherever it already was, so audio ends up way ahead of video and
        # never catches back up (exactly the "video jumps back, audio
        # doesn't" symptom reported). Forward seeks never showed this.
        # Issuing the identical seek command again ~150ms later reliably
        # fixes it (tested repeatedly: sub-100ms audio/video drift
        # afterward) -- the first call alone doesn't reach the audio
        # demuxer, but by the time the second one lands, whatever state
        # made the first one partial has settled and it takes fully. Firing
        # both back-to-back with no gap does NOT work (tested: tens of
        # seconds of drift) -- the gap via QTimer.singleShot (non-blocking,
        # doesn't stall the GUI thread) is load-bearing, not incidental.
        self.mpv.command("seek", str(seconds), "absolute+exact")
        QTimer.singleShot(150, lambda: self._confirm_seek(seconds))

    def _confirm_seek(self, seconds: float) -> None:
        if not self.closed:
            self.mpv.command("seek", str(seconds), "absolute+exact")

    @Slot()
    def stop(self) -> None:
        if not self.closed:
            self.mpv.stop()
