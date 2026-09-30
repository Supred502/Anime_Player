import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import AnimePlayer 1.0

Kirigami.Page {
    id: page

    // Paints this page in the app's colour scheme -- see AppTheming.qml
    // for why this is per-page rather than set once on the window.
    AppTheming {}
    property var anime: ({})
    property int episodeId: 0
    property real episodeNumber: 0
    property bool dub: false
    // Seconds to jump to once the video is ready, e.g. a saved word's line.
    // -1: start wherever playback normally starts.
    property real startAt: -1
    title: (anime.title || "") + " - Episode " + episodeNumber
    padding: 0
    focus: true // needed for Keys.onPressed below to actually receive events

    // Subtitle size and height, saved app-wide (see backend.subtitleStyle)
    // and pushed to mpv whenever either changes.
    property real subScale: 1.0
    property int subPosition: 100
    onSubScaleChanged: page.applySubtitleStyle()
    onSubPositionChanged: page.applySubtitleStyle()
    function applySubtitleStyle() {
        if (video) video.setSubtitleStyle(page.subScale, page.subPosition)
    }
    function saveSubtitleStyle() { backend.setSubtitleStyle(page.subScale, page.subPosition) }

    // -- Learn Japanese (see LearnOverlay.qml) ---------------------------------
    property bool learnMode: false
    property bool showEnglish: true
    property bool learnAutoSynced: false
    property bool dubEnglish: true
    onShowEnglishChanged: if (video) video.setSubtitlesVisible(page.showEnglish)
    onLearnModeChanged: {
        backend.setLearnMode(page.learnMode)
        if (page.learnMode) page.startLearning()
        else { learnOverlay.cues = []; learnOverlay.status = ""; video.setSubtitlesVisible(true) }
    }
    function startLearning() {
        learnOverlay.cues = []
        learnOverlay.status = "Loading Japanese subtitles\u2026"
        if (backend.dictionaryState() === "missing") {
            showPassiveNotification("Setting up the dictionary -- a one-time 10 MB download")
            backend.prepareDictionary()
        }
        video.setSubtitlesVisible(page.showEnglish)
        backend.loadJapaneseSubs(page.episodeNumber)
    }
    function learnFlag(name, fallback) {
        let value = backend.learnOption(name)
        return value === "" ? fallback : value === "true"
    }
    function setLearnFlag(name, value) { backend.setLearnOption(name, value ? "true" : "false") }

    property bool loadingStream: true
    property bool controlsVisible: true
    property bool isFullscreen: false
    property bool stalled: false // stream loaded but no frames arrived after a real wait -- offer a retry instead of spinning forever
    property bool autoRetried: false // one silent fresh-resolve retry before bothering the user with a Retry button

    // Intro/outro auto-skip (Aniskip) + auto-next-episode
    property var skipOp: null   // {start, end} in seconds, or null if unknown/none for this episode
    property var skipEd: null
    property bool opAutoSkipped: false // guards against re-seeking every position tick while inside the interval
    property bool edAutoSkipped: false
    property bool autoSkipEnabled: true
    property bool skipFinalEpisodeEnabled: false
    property bool autoNextEnabled: true
    property int episodeCount: 0
    property real firstEpisodeNumber: 1
    readonly property bool isLastEpisode: page.episodeCount > 0 && page.episodeNumber >= page.episodeCount
    // On the last episode, auto-skip is suppressed unless skipFinalEpisodeEnabled
    // is explicitly on -- nothing left to spoil by watching the real ending.
    readonly property bool autoSkipActive: page.autoSkipEnabled && (!page.isLastEpisode || page.skipFinalEpisodeEnabled)
    // Page.qml computes its own default globalToolBarStyle from PageRow context
    // (back button, breadcrumb, etc.) -- snapshotted once below so exiting
    // fullscreen restores exactly that instead of a hardcoded guess. Must be
    // read via Qt.callLater, not synchronously in onCompleted: verified live
    // that at onCompleted time this page isn't fully wired into the PageRow
    // yet, so globalToolBarStyle still reads as None (no back button) then --
    // it only settles to the real value (ToolBar, with the back button) a
    // tick later. Snapshotting the premature value is exactly what silently
    // ate the back button after the first fullscreen toggle.
    property int normalToolBarStyle: Kirigami.ApplicationHeaderStyle.Auto

    ListModel { id: qualityModel }

    Component.onCompleted: {
        Qt.callLater(function() { page.normalToolBarStyle = page.globalToolBarStyle })
        page.autoSkipEnabled = backend.getAutoSkipEnabled()
        page.skipFinalEpisodeEnabled = backend.getSkipFinalEpisodeEnabled()
        page.autoNextEnabled = backend.getAutoNextEnabled()
        page.episodeCount = backend.getCurrentEpisodeCount()
        page.firstEpisodeNumber = backend.getFirstEpisodeNumber()
        learnOverlay.showRomaji = page.learnFlag("romaji", true)
        learnOverlay.showFurigana = page.learnFlag("furigana", true)
        learnOverlay.pauseOnHover = page.learnFlag("pause_hover", true)
        learnOverlay.pauseEachLine = page.learnFlag("pause_line", false)
        learnOverlay.wordGaps = page.learnFlag("gaps", true)
        learnOverlay.readAlong = page.learnFlag("read_along", true)
        page.dubEnglish = backend.getDubEnglishEnabled()
        page.showEnglish = page.learnFlag("english", true)
        page.learnMode = backend.getLearnMode()
        let savedSpeed = parseFloat(backend.learnOption("speed"))
        if (savedSpeed > 0 && savedSpeed !== 1) page.speed = savedSpeed
        // Volume and mute carry over from the last episode: every one
        // started at full volume before.
        let savedVolume = parseFloat(backend.learnOption("volume"))
        if (savedVolume >= 0) video.setVolume(savedVolume)
        video.setMuted(backend.learnOption("muted") === "true")
        page.volumeRestored = true
        let style = backend.subtitleStyle()
        page.subScale = style.scale
        page.subPosition = style.position
        page.startLoad()
        // Straight into fullscreen on the way in, unless the user turned that
        // off. Picking an episode is an unambiguous "I am going to watch
        // this", and the alternative is everyone reaching for the same button
        // every time.
        if (backend.getAutoFullscreenEnabled() && !page.isFullscreen) {
            // Deferred: the page is not in the PageRow yet at this point (the
            // same reason normalToolBarStyle above is read via callLater), and
            // toggling visibility before it is wired in leaves the toolbar
            // state snapshot wrong on the way back out.
            Qt.callLater(function() { page.toggleFullscreen() })
        }
    }

    function startLoad(resetAutoRetry) {
        // resetAutoRetry defaults to true (a genuinely fresh attempt -- initial
        // load or the user's own manual Retry click); the one silent internal
        // auto-retry in onPlaybackError below passes false so it can't loop
        // forever retrying the same dead stream.
        page.loadingStream = true
        page.stalled = false
        if (resetAutoRetry !== false) page.autoRetried = false
        stallTimer.restart()
        backend.loadStream(episodeId, episodeNumber, dub)
    }

    // loadUrl() handing the URL to mpv is not the same as mpv actually
    // producing frames -- a dead/expired HLS link can sit at 0:00 forever
    // with no error at all. Give it a real window to start, then offer a
    // manual retry instead of leaving the user staring at a stuck spinner.
    Timer {
        id: stallTimer
        interval: 12000
        onTriggered: {
            if (!page.loadingStream && video.position <= 0 && video.duration <= 0) {
                page.stalled = true
            }
        }
    }
    // Playback generates no input events, so the session goes idle and the
    // screen blanks mid-episode unless the desktop is told otherwise -- see
    // player/idle_inhibitor.py. Tracks actual playback rather than merely
    // being on this page: a paused episode should let the screen sleep.
    readonly property bool keepScreenAwake: !page.loadingStream && !video.paused
    onKeepScreenAwakeChanged: backend.setKeepScreenAwake(page.keepScreenAwake)

    // Everything that must be true for the pointer to be hidden. Leaving this
    // page, losing focus, or the application shutting down all put the arrow
    // back before this item stops existing -- see the MouseArea below.
    property bool showingPointerAgain: false
    readonly property bool pointerHidden: !page.controlsVisible
                                          && page.Window.active
                                          && !page.showingPointerAgain

    Connections {
        target: Qt.application
        function onAboutToQuit() { page.showingPointerAgain = true }
    }

    // Watched enough of it to count. Deliberately not "reached the end":
    // most people stop during the credits, and an episode that never counts
    // as watched is one whose saved copy never gets cleaned up.
    // Past this much of an episode it counts as watched: on AniList, in
    // Stats, and for clearing old downloads. Checked as it plays (see the
    // video's onPositionChanged), not only on leaving.
    readonly property real watchedThreshold: 0.8
    property bool reportedWatched: false

    function reportWatched() {
        if (page.reportedWatched) return
        page.reportedWatched = true
        backend.episodeWatched(page.episodeId, page.dub)
    }

    // The desktop's media controls (see media_session.py): what's playing,
    // for the media widget, and the media keys from any app.
    function publishMedia() {
        if (video.duration <= 0) return
        mediaSession.update(page.anime.title || "", "Episode " + page.episodeNumber,
                            page.anime.poster_url || "", video.duration, !video.paused,
                            !page.isLastEpisode, page.episodeNumber > page.firstEpisodeNumber)
    }
    Connections {
        target: video
        function onPausedChanged() { page.publishMedia() }
        function onDurationChanged() { page.publishMedia() }
    }
    Connections {
        target: mediaSession
        function onAction(name) {
            if (name === "playpause") video.togglePause()
            else if (name === "play") video.setPaused(false)
            else if (name === "pause") video.setPaused(true)
            else if (name === "next" && !page.isLastEpisode) page.nextEpisode()
            else if (name === "previous" && page.episodeNumber > page.firstEpisodeNumber) page.previousEpisode()
        }
    }

    Component.onDestruction: {
        mediaSession.clear()
        // Leaving part-way through the credits still counts -- see above.
        if (video && video.duration > 0
                && video.position >= video.duration * page.watchedThreshold) {
            page.reportWatched()
        }
        page.showingPointerAgain = true
        backend.setKeepScreenAwake(false)
        backend.playerClosed()
        let win = applicationWindow()
        if (page.isFullscreen && !win.appFullscreen) win.visibility = Window.Windowed
        // Always, not only when leaving fullscreen: the player hides the
        // nav bar, so it must hand it back -- unless the whole app is in
        // F11 fullscreen, which hides it on purpose.
        win.chromeVisible = !win.appFullscreen
    }

    // Leaving while fullscreen (the Back button, the mouse's back button,
    // Alt+Left): out of fullscreen first, while the page is still whole.
    // Left to Component.onDestruction, it was measured not to happen -- the
    // window stayed fullscreen with no nav bar over the episode list.
    onBackRequested: (event) => { if (page.isFullscreen) page.toggleFullscreen() }

    function toggleFullscreen() {
        page.isFullscreen = !page.isFullscreen
        let win = applicationWindow()
        // Leaving the player's fullscreen while the whole app is in F11
        // fullscreen goes back to the app's fullscreen, not to a window.
        win.visibility = page.isFullscreen || win.appFullscreen ? Window.FullScreen : Window.Windowed
        page.globalToolBarStyle = page.isFullscreen ? Kirigami.ApplicationHeaderStyle.None : page.normalToolBarStyle
        // The app draws its own titlebar now, and that bar belongs to the
        // window rather than to any page -- so hiding this page's own toolbar
        // used to leave the nav bar sitting across the top of the video.
        applicationWindow().chromeVisible = !page.isFullscreen && !win.appFullscreen
    }

    // Shared actions -- used by both the keyboard shortcuts below and by
    // remote-control commands (see onRemoteCommand in the Connections block),
    // so there's exactly one implementation of each behavior.
    function seekTo(seconds) {
        video.seekAbsolute(Math.max(0, Math.min(video.duration, seconds)))
    }
    function seekRelative(deltaSeconds) {
        video.seekAbsolute(Math.max(0, Math.min(video.duration, video.position + deltaSeconds)))
    }
    function skipIntroNow() {
        if (page.skipOp) { page.opAutoSkipped = true; video.seekAbsolute(page.skipOp.end) }
    }
    function skipOutroNow() {
        if (page.skipEd) { page.edAutoSkipped = true; video.seekAbsolute(page.skipEd.end) }
    }
    // An automatic skip is announced for a few seconds, with a way back:
    // otherwise it is indistinguishable from the video jumping by itself,
    // and there is no way to watch an opening you actually wanted to see.
    property string justSkipped: ""   // "intro", "outro" or ""
    function announceSkip(which) {
        page.justSkipped = which
        skipNotice.restart()
    }
    function undoSkip() {
        let range = page.justSkipped === "intro" ? page.skipOp : page.skipEd
        page.justSkipped = ""
        // The *AutoSkipped guard is still set, so this won't skip again.
        if (range) video.seekAbsolute(range.start)
    }
    Timer {
        id: skipNotice
        interval: 6000
        onTriggered: page.justSkipped = ""
    }

    // What's loaded, for handing over to the mini player.
    property string streamUrl: ""
    property string streamReferer: ""
    property string streamSubtitle: ""
    function toMiniPlayer() {
        if (page.streamUrl === "" || video.duration <= 0) return
        let win = applicationWindow()
        win.startMiniPlayer({
            anime: page.anime, episodeId: page.episodeId, episodeNumber: page.episodeNumber,
            dub: page.dub, url: page.streamUrl, referer: page.streamReferer,
            subtitle: page.streamSubtitle, position: video.position
        })
        if (page.isFullscreen) page.toggleFullscreen()
        win.pageStack.goBack()
    }

    // A controller in the player (see GamepadNav): A pauses, left/right
    // seek 10s and the triggers 30s, up/down is volume, LB/RB change
    // episode, Y skips the intro or outro, X is Learn Japanese, Start is
    // fullscreen, B leaves. View/Select hands over to the on-screen controls.
    function gamepadAction(action) {
        page.controlsVisible = true
        hideTimer.restart()
        switch (action) {
        case "accept": video.togglePause(); break
        case "left": page.seekRelative(-10); break
        case "right": page.seekRelative(10); break
        case "lt": page.seekRelative(-30); break
        case "rt": page.seekRelative(30); break
        case "up": page.volumeUp(); page.flashVolume(); break
        case "down": page.volumeDown(); page.flashVolume(); break
        case "lb": page.previousEpisode(); break
        case "rb": page.nextEpisode(); break
        case "y":
            if (page.skipOp && video.position >= page.skipOp.start && video.position < page.skipOp.end) page.skipIntroNow()
            else if (page.skipEd && video.position >= page.skipEd.start && video.position < page.skipEd.end) page.skipOutroNow()
            break
        case "x": if (backend.learnFeatures) page.learnMode = !page.learnMode; break
        case "menu": page.toggleFullscreen(); break
        case "back": applicationWindow().pageStack.goBack(); break
        }
    }

    function nextEpisode() { backend.loadNextEpisode(page.episodeNumber, page.dub) }
    function previousEpisode() { backend.loadPreviousEpisode(page.episodeNumber, page.dub) }
    function volumeUp() { video.setMuted(false); video.setVolume(video.volume + 10) }
    function volumeDown() { video.setVolume(video.volume - 10) }
    // Saved a moment after it stops changing (a slider drag is dozens of
    // changes), and only once the saved one has been put back.
    property bool volumeRestored: false
    Connections {
        target: video
        function onVolumeChanged() { if (page.volumeRestored) volumeSave.restart() }
        function onMutedChanged() { if (page.volumeRestored) volumeSave.restart() }
    }
    Timer {
        id: volumeSave
        interval: 600
        onTriggered: {
            backend.setLearnOption("volume", String(Math.round(video.volume)))
            backend.setLearnOption("muted", video.muted ? "true" : "false")
        }
    }
    function escapeAction() {
        video.setPaused(true)
        if (page.isFullscreen) page.toggleFullscreen()
    }

    Keys.onPressed: (event) => {
        if (event.key === Qt.Key_Space) {
            video.togglePause()
            event.accepted = true
        } else if (event.key === Qt.Key_Left) {
            page.seekRelative(-5)
            event.accepted = true
        } else if (event.key === Qt.Key_Right) {
            page.seekRelative(5)
            event.accepted = true
        } else if (event.key === Qt.Key_Escape) {
            page.escapeAction()
            event.accepted = true
        } else if (event.key === Qt.Key_F) {
            page.toggleFullscreen()
            event.accepted = true
        } else if (event.key === Qt.Key_I) {
            page.toMiniPlayer()
            event.accepted = true
        } else if (event.key === Qt.Key_N) {
            page.nextEpisode()
            event.accepted = true
        } else if (event.key === Qt.Key_P) {
            page.previousEpisode()
            event.accepted = true
        } else if (event.key === Qt.Key_S) {
            // Whichever of the two the video is in; nothing otherwise.
            if (page.skipOp && video.position >= page.skipOp.start && video.position < page.skipOp.end) page.skipIntroNow()
            else if (page.skipEd && video.position >= page.skipEd.start && video.position < page.skipEd.end) page.skipOutroNow()
            event.accepted = true
        } else if (event.key === Qt.Key_Up) {
            page.volumeUp()
            page.flashVolume()
            event.accepted = true
        } else if (event.key === Qt.Key_Down) {
            page.volumeDown()
            page.flashVolume()
            event.accepted = true
        } else if (event.key === Qt.Key_MediaTogglePlayPause || event.key === Qt.Key_MediaPlay
                   || event.key === Qt.Key_MediaPause) {
            // A keyboard's media keys, and headset buttons, which send the same.
            if (event.key === Qt.Key_MediaPause) video.setPaused(true)
            else if (event.key === Qt.Key_MediaPlay) video.setPaused(false)
            else video.togglePause()
            event.accepted = true
        } else if (event.key === Qt.Key_MediaNext) {
            page.nextEpisode()
            event.accepted = true
        } else if (event.key === Qt.Key_MediaPrevious) {
            page.previousEpisode()
            event.accepted = true
        } else if (event.key === Qt.Key_M) {
            video.setMuted(!video.muted)
            page.flashVolume()
            event.accepted = true
        } else if (event.key === Qt.Key_BracketLeft) {
            page.stepSpeed(-1)
            event.accepted = true
        } else if (event.key === Qt.Key_BracketRight) {
            page.stepSpeed(1)
            event.accepted = true
        } else if (event.key === Qt.Key_L && backend.learnFeatures) {
            page.learnMode = !page.learnMode
            event.accepted = true
        } else if (event.key === Qt.Key_R && page.learnMode) {
            learnOverlay.replayLine()
            event.accepted = true
        } else if (event.key === Qt.Key_Question || event.key === Qt.Key_Slash) {
            shortcutHelp.visible = !shortcutHelp.visible
            event.accepted = true
        }
    }

    // Volume keys change something invisible, so they say what they did.
    property bool volumeShown: false
    // What the centre flash says; volume by default.
    property string flashText: ""
    function flashVolume() {
        page.flashText = ""
        page.volumeShown = true
        volumeFlash.restart()
    }
    function flash(text) {
        page.flashText = text
        page.volumeShown = true
        volumeFlash.restart()
    }

    // Playback speed. Remembered app-wide: someone who needs 0.75x to read
    // along needs it every episode, not just this one.
    readonly property var speeds: [0.5, 0.6, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0]
    property real speed: 1.0
    onSpeedChanged: {
        video.setSpeed(page.speed)
        backend.setLearnOption("speed", String(page.speed))
    }
    function speedLabel(value) { return (value === 1 ? "1" : String(value)) + "\u00d7" }
    function stepSpeed(direction) {
        let i = page.speeds.indexOf(page.speed)
        if (i < 0) i = page.speeds.indexOf(1.0)
        page.speed = page.speeds[Math.max(0, Math.min(page.speeds.length - 1, i + direction))]
        page.flash("Speed " + page.speedLabel(page.speed))
    }
    Timer { id: volumeFlash; interval: 1200; onTriggered: page.volumeShown = false }

    Connections {
        target: backend
        function onStreamReady(url, referer, subtitleUrl) {
            page.loadingStream = false
            page.stalled = false
            stallTimer.restart()
            // referer and subtitleUrl are both load-bearing, not optional
            // extras -- see MpvVideoItem.loadUrl.
            video.loadUrl(url, referer, subtitleUrl)
            page.streamUrl = url
            page.streamReferer = referer
            page.streamSubtitle = subtitleUrl
        }
        function onStreamFailed(message) {
            page.loadingStream = false
            showPassiveNotification("Playback failed: " + message)
        }
        function onDubEnglishReady(url) {
            if (page.dub) video.addSubtitle(url)
        }
        function onJapaneseSubsReady(payload) {
            if (payload.episode !== page.episodeNumber) return
            learnOverlay.cues = payload.cues
            learnOverlay.status = ""
            // Lined up with the English subtitles automatically when they
            // agree clearly on an offset (see learn/sync.py); the Timing
            // buttons adjust from there.
            learnOverlay.offset = payload.offset !== undefined && payload.offset !== null ? payload.offset : 0
            page.learnAutoSynced = payload.offset !== undefined && payload.offset !== null
        }
        function onJapaneseSubsFailed(message) {
            if (page.learnMode) learnOverlay.status = message
        }
        function onDictionaryReady() {
            if (page.learnMode) showPassiveNotification("Dictionary ready -- hover a word to look it up")
        }
        function onDictionaryFailed(message) { showPassiveNotification(message) }
        function onSkipTimesReady(times) {
            page.skipOp = times.op || null
            page.skipEd = times.ed || null
            page.opAutoSkipped = false
            page.edAutoSkipped = false
        }
        function onNextEpisodeLoading(newEpisodeId, newEpisodeNumber) {
            page.episodeId = newEpisodeId
            page.episodeNumber = newEpisodeNumber
            page.loadingStream = true
            page.stalled = false
            page.skipOp = null
            page.skipEd = null
            page.opAutoSkipped = false
            page.edAutoSkipped = false
            page.justSkipped = ""
            page.autoRetried = false
            if (page.learnMode) page.startLearning()
            // This page is reused for the next episode rather than rebuilt,
            // so the "already counted as watched" guard has to be cleared or
            // every episode after the first would skip its own cleanup.
            page.reportedWatched = false
            stallTimer.restart()
        }
        function onNoNextEpisode() {
            showPassiveNotification("You've reached the last episode")
        }
        function onStreamQualitiesAvailable(qualities) {
            qualityModel.clear()
            qualityModel.append({ label: "Auto" })
            for (let i = 0; i < qualities.length; i++) qualityModel.append(qualities[i])

            // Reflect whatever quality actually ended up playing: if a specific
            // quality is remembered, loadStream() already started playback at it.
            let preferred = backend.getPreferredQuality()
            let idx = 0
            for (let i = 0; i < qualityModel.count; i++) {
                if (qualityModel.get(i).label === preferred) { idx = i; break }
            }
            // QQC2 ComboBox doesn't always refresh its displayed text after the
            // model it's bound to is cleared and repopulated in place -- forcing
            // currentIndex to re-assign (even to the same value) makes it re-read.
            qualityCombo.currentIndex = -1
            qualityCombo.currentIndex = idx
        }
    }

    Timer {
        interval: 10000
        running: !video.paused && !page.loadingStream
        repeat: true
        onTriggered: backend.savePlaybackPosition(page.episodeId, page.episodeNumber, video.position, video.duration)
    }

    // Time actually spent watching, for the Stats page. Counted in the
    // player rather than inferred from episodes finished: half an episode
    // is still half an episode's time, and paused time is not watching.
    Timer {
        interval: 5000
        running: !video.paused && !page.loadingStream && video.duration > 0
        repeat: true
        onTriggered: backend.addWatchTime(interval / 1000)
    }

    // Keeps the phone remote's "now playing" readout reasonably fresh --
    // separate from the save-progress timer above since that one only runs
    // while playing (and every 10s is too stale-feeling for a live remote
    // display); this runs whenever the page is loaded, playing or paused.
    Timer {
        interval: 1500
        running: !page.loadingStream
        repeat: true
        triggeredOnStart: true
        onTriggered: backend.reportPlaybackState(video.position, video.duration, video.paused)
    }

    // Phone remote player commands -- see remote/server.py for the wire
    // format and Main.qml for the separate "open an anime" browse commands
    // this page doesn't handle. Reuses the exact same action functions as
    // the keyboard shortcuts above, so behavior is identical either way.
    Connections {
        target: backend
        function onRemoteCommand(cmd, args) {
            if (cmd === "play_pause") video.togglePause()
            else if (cmd === "seek") page.seekRelative(args)
            else if (cmd === "skip_intro") page.skipIntroNow()
            else if (cmd === "skip_outro") page.skipOutroNow()
            else if (cmd === "next_episode") page.nextEpisode()
            else if (cmd === "prev_episode") page.previousEpisode()
            else if (cmd === "volume") { if (args > 0) page.volumeUp(); else page.volumeDown() }
            // Continue on phone: the PC pauses while the phone plays, then
            // picks up from wherever the phone got to.
            else if (cmd === "pause") video.setPaused(true)
            else if (cmd === "resume_at") {
                page.seekTo(Number(args) || 0)
                video.setPaused(false)
            }
        }
    }

    // Controls fade out after a few seconds of no mouse movement, like any
    // normal video player. Movement over the page, or holding the seek
    // slider, keeps them up.
    Timer {
        id: hideTimer
        interval: 3000
        running: true // starts counting down from page load, not just after the first mouse move
        // Holding the controls (and so the pointer) up while paused matches
        // every other player, and means a paused episode never leaves the
        // user with no pointer and nothing on screen to click.
        onTriggered: if (!seekSlider.pressed && !video.paused) page.controlsVisible = false
    }

    MpvVideoItem {
        id: video
        anchors.fill: parent
        // Without this, mpv's internal threads keep running after the page is
        // popped and their callbacks fire into a deleted QML object -- see the
        // comment on MpvVideoItem.close() in mpv_video_item.py.
        Component.onDestruction: close()
        onPositionChanged: (value) => {
            if (value > 0) { page.stalled = false; stallTimer.stop() }
            if (video.duration > 0 && value >= video.duration * page.watchedThreshold) page.reportWatched()
            if (page.learnMode) learnOverlay.update(value)
            // Auto-skip: seek past the interval the moment playback enters it.
            // The *AutoSkipped guards stop this from firing again every
            // position tick for the rest of the interval (position keeps
            // reporting "inside" it for a moment after the seek lands).
            if (!page.autoSkipActive) return
            if (page.skipOp && !page.opAutoSkipped && value >= page.skipOp.start && value < page.skipOp.end) {
                page.opAutoSkipped = true
                video.seekAbsolute(page.skipOp.end)
                page.announceSkip("intro")
            }
            if (page.skipEd && !page.edAutoSkipped && value >= page.skipEd.start && value < page.skipEd.end) {
                page.edAutoSkipped = true
                video.seekAbsolute(page.skipEd.end)
                page.announceSkip("outro")
            }
        }
        onDurationChanged: (value) => {
            if (value > 0) { page.stalled = false; stallTimer.stop() }
            if (value > 0 && page.startAt >= 0) {
                video.seekAbsolute(page.startAt)
                page.startAt = -1
            }
        }
        onPlaybackError: (message) => {
            // Never-successfully-started errors (dead/expired link, transient
            // source-side hiccup) are common enough to be worth one silent
            // fresh re-resolve before bothering the user with the manual
            // Retry button -- confirmed live that re-resolving the exact
            // same episode/quality moments later can just work. Errors after
            // playback already started (a mid-episode hiccup) skip straight
            // to the toast instead, since a full reload there would be more
            // disruptive than helpful.
            if (!page.autoRetried && video.position <= 0 && video.duration <= 0) {
                page.autoRetried = true
                page.startLoad(false)
                return
            }
            page.stalled = true
            backend.noteError("Playback: " + message)
            showPassiveNotification("Playback error: " + message)
        }
        onPausedChanged: {
            page.controlsVisible = true
            hideTimer.restart()
        }
        onEndOfFile: {
            page.reportWatched()
            if (page.autoNextEnabled) page.nextEpisode()
        }
    }

    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        // The pointer sat on top of the video forever once the controls had
        // faded out. It goes away with them, and comes back on the first
        // movement (onPositionChanged below still fires while it's hidden).
        //
        // Gated on the window being active, and restored on the way out (see
        // the handlers above), because the compositor keeps whatever cursor a
        // client last set: hide the pointer and then vanish -- page popped,
        // app quit, app killed -- and the user is left with no pointer at all,
        // desktop-wide, until something else happens to set one. That is a far
        // worse bug than the one this fixes, so the hidden state is only ever
        // held while this page is genuinely in front of the user.
        cursorShape: page.pointerHidden ? Qt.BlankCursor : Qt.ArrowCursor
        onPositionChanged: { page.controlsVisible = true; hideTimer.restart() }
        onClicked: video.togglePause()
        // The scroll wheel over the picture is volume, as in most players.
        // 5% a notch of a mouse wheel; a touchpad's many small steps add up
        // to the same over the same distance.
        onWheel: (wheel) => {
            if (wheel.angleDelta.y === 0) return
            video.setMuted(false)
            video.setVolume(video.volume + wheel.angleDelta.y / 120 * 5)
            page.flashVolume()
        }
    }

    LearnOverlay {
        id: learnOverlay
        objectName: "learnOverlay"
        anchors.fill: parent
        video: video
        visible: page.learnMode && !page.loadingStream
        onWordSaved: (word) => showPassiveNotification("Saved " + word + " to your words")
    }

    ColumnLayout {
        anchors.centerIn: parent
        visible: page.loadingStream || page.stalled
        spacing: Kirigami.Units.smallSpacing

        Controls.BusyIndicator {
            // The QQC2 desktop style sets Kirigami.Theme.inherit = false on its
            // controls, which stops the app's accent reaching them -- measured
            // live: a page themed red still drew Breeze-blue Sub/Dub buttons.
            // Turning inheritance back on is what makes one accent value reach
            // every control in the app. See AppTheming.qml.
            Kirigami.Theme.inherit: true
            Layout.alignment: Qt.AlignHCenter
            visible: !page.stalled
            running: page.loadingStream && !page.stalled
        }
        Controls.Label {
            Layout.alignment: Qt.AlignHCenter
            text: page.stalled ? "Playback isn't starting" : "Loading video…"
        }
        Controls.Label {
            Layout.alignment: Qt.AlignHCenter
            visible: page.stalled
            opacity: 0.7
            text: "The stream may have expired or the source is unavailable."
        }
        Controls.Button {
            Kirigami.Theme.inherit: true
            Layout.alignment: Qt.AlignHCenter
            visible: page.stalled
            text: "Retry"
            icon.name: "view-refresh-symbolic"
            onClicked: page.startLoad()
        }
        Controls.ToolButton {
            Kirigami.Theme.inherit: true
            Layout.alignment: Qt.AlignHCenter
            visible: page.stalled
            text: "Report this problem"
            icon.name: "tools-report-bug-symbolic"
            onClicked: Qt.openUrlExternally(backend.problemReportUrl(
                "Won't play: " + (page.anime.title || "") + " episode " + page.episodeNumber))
        }
    }

    // Fullscreen hides the page's toolbar and with it the back arrow, which
    // left Esc as the only way out -- and nothing on screen said so.
    RowLayout {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.margins: Kirigami.Units.largeSpacing
        visible: page.isFullscreen && page.controlsVisible
        spacing: Kirigami.Units.largeSpacing

        AppButton {
            icon.name: "go-previous-symbolic"
            text: "Back"
            onClicked: applicationWindow().pageStack.goBack()
            Controls.ToolTip.visible: hovered
            Controls.ToolTip.text: "Back to the episode list"
        }
        Controls.Label {
            text: (page.anime && page.anime.title ? page.anime.title + " · " : "")
                  + "Episode " + page.episodeNumber
            color: "white"
            style: Text.Outline
            styleColor: Qt.rgba(0, 0, 0, 0.6)
            font.bold: true
        }
    }

    RowLayout {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: Kirigami.Units.largeSpacing
        visible: !page.loadingStream && page.controlsVisible

        AppButton {
            visible: backend.learnFeatures
            text: "\u3042"
            Layout.preferredWidth: implicitHeight * 1.3
            leftPadding: 0
            rightPadding: 0
            checkable: true
            checked: page.learnMode
            font.bold: true
            onClicked: learnPopup.opened ? learnPopup.close() : learnPopup.open()
            Controls.ToolTip.visible: hovered
            Controls.ToolTip.text: "Learn Japanese (L)"

            Controls.Popup {
                id: learnPopup
                Kirigami.Theme.inherit: true
                y: parent.height + Kirigami.Units.smallSpacing
                x: parent.width - width
                padding: Kirigami.Units.largeSpacing
                onOpened: { page.controlsVisible = true; hideTimer.stop() }
                onClosed: hideTimer.restart()

                ColumnLayout {
                    spacing: Kirigami.Units.smallSpacing
                    AppCheckBox {
                        text: "Learn Japanese"
                        checked: page.learnMode
                        onToggled: page.learnMode = checked
                    }
                    Kirigami.Separator { Layout.fillWidth: true }
                    AppCheckBox {
                        text: "Readings over kanji (furigana)"
                        enabled: page.learnMode
                        checked: learnOverlay.showFurigana
                        onToggled: { learnOverlay.showFurigana = checked; page.setLearnFlag("furigana", checked) }
                    }
                    AppCheckBox {
                        text: "Gaps between words"
                        enabled: page.learnMode
                        checked: learnOverlay.wordGaps
                        onToggled: { learnOverlay.wordGaps = checked; page.setLearnFlag("gaps", checked) }
                    }
                    AppCheckBox {
                        text: "Read along (words light up as they're said)"
                        enabled: page.learnMode
                        checked: learnOverlay.readAlong
                        onToggled: { learnOverlay.readAlong = checked; page.setLearnFlag("read_along", checked) }
                    }
                    AppCheckBox {
                        text: "Romaji"
                        enabled: page.learnMode
                        checked: learnOverlay.showRomaji
                        onToggled: { learnOverlay.showRomaji = checked; page.setLearnFlag("romaji", checked) }
                    }
                    AppCheckBox {
                        text: "English subtitles"
                        enabled: page.learnMode
                        checked: page.showEnglish
                        onToggled: { page.showEnglish = checked; page.setLearnFlag("english", checked) }
                    }
                    AppCheckBox {
                        text: "Pause while I'm pointing at a word"
                        enabled: page.learnMode
                        checked: learnOverlay.pauseOnHover
                        onToggled: { learnOverlay.pauseOnHover = checked; page.setLearnFlag("pause_hover", checked) }
                    }
                    AppCheckBox {
                        text: "Pause after each line"
                        enabled: page.learnMode
                        checked: learnOverlay.pauseEachLine
                        onToggled: { learnOverlay.pauseEachLine = checked; page.setLearnFlag("pause_line", checked) }
                    }
                    RowLayout {
                        Controls.Label { text: "Speed" }
                        Repeater {
                            model: [0.5, 0.75, 1.0]
                            AppButton {
                                required property var modelData
                                text: page.speedLabel(modelData)
                                checkable: true
                                checked: page.speed === modelData
                                onClicked: page.speed = modelData
                            }
                        }
                    }
                    RowLayout {
                        enabled: page.learnMode
                        Controls.Label { text: "Timing" }
                        Controls.Button {
                            Kirigami.Theme.inherit: true
                            text: "\u2212 0.5s"
                            onClicked: learnOverlay.offset -= 0.5
                        }
                        Controls.Label {
                            text: (learnOverlay.offset > 0 ? "+" : "") + learnOverlay.offset.toFixed(1) + "s"
                            Layout.minimumWidth: Kirigami.Units.gridUnit * 2.5
                            horizontalAlignment: Text.AlignHCenter
                        }
                        Controls.Button {
                            Kirigami.Theme.inherit: true
                            text: "+ 0.5s"
                            onClicked: learnOverlay.offset += 0.5
                        }
                    }
                    Controls.Label {
                        visible: page.learnAutoSynced
                        text: "Lined up with the English subtitles automatically."
                        color: Kirigami.Theme.positiveTextColor
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    }
                    Controls.Label {
                        text: "Japanese lines showing too early? Press +. Too late? Press \u2212.\nR replays the line."
                        opacity: 0.6
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    }
                }
            }
        }

        Controls.Button {
            Kirigami.Theme.inherit: true
            icon.name: "media-view-subtitles-symbolic"
            onClicked: subtitlePopup.opened ? subtitlePopup.close() : subtitlePopup.open()
            Controls.ToolTip.visible: hovered
            Controls.ToolTip.text: "Subtitle size and position"

            Controls.Popup {
                id: subtitlePopup
                Kirigami.Theme.inherit: true
                y: parent.height + Kirigami.Units.smallSpacing
                x: parent.width - width
                padding: Kirigami.Units.largeSpacing
                // Keeps the controls up while the popup is in use.
                onOpened: { page.controlsVisible = true; hideTimer.stop() }
                onClosed: { hideTimer.restart(); page.saveSubtitleStyle() }

                ColumnLayout {
                    spacing: Kirigami.Units.smallSpacing
                    Controls.Label { text: "Size: " + Math.round(page.subScale * 100) + "%" }
                    Controls.Slider {
                        Kirigami.Theme.inherit: true
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 14
                        from: 0.5; to: 2.0; stepSize: 0.05
                        value: page.subScale
                        onMoved: page.subScale = value
                    }
                    Controls.Label {
                        text: "Height: " + (page.subPosition >= 100 ? "bottom"
                              : (100 - page.subPosition) + "% up")
                    }
                    Controls.Slider {
                        Kirigami.Theme.inherit: true
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 14
                        from: 60; to: 100; stepSize: 1
                        value: page.subPosition
                        onMoved: page.subPosition = value
                    }
                    Controls.Button {
                        Kirigami.Theme.inherit: true
                        text: "Reset"
                        onClicked: { page.subScale = 1.0; page.subPosition = 100 }
                    }
                    Kirigami.Separator { Layout.fillWidth: true }
                    AppCheckBox {
                        text: "English subtitles on dubs"
                        checked: page.dubEnglish
                        onToggled: {
                            page.dubEnglish = checked
                            backend.setDubEnglishEnabled(checked)
                        }
                    }
                    Controls.Label {
                        text: "From the subbed version, so the wording won't\nalways match what the dub says. Next episode on."
                        opacity: 0.6
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    }
                }
            }
        }

        Controls.ComboBox {
            Kirigami.Theme.inherit: true
            id: qualityCombo
            model: qualityModel
            textRole: "label"
            onActivated: backend.selectQuality(currentIndex === 0 ? "" : currentText)
        }
        Controls.Button {
            Kirigami.Theme.inherit: true
            icon.name: "window-minimize-pip"
            enabled: page.streamUrl !== "" && video.duration > 0
            onClicked: page.toMiniPlayer()
            Controls.ToolTip.visible: hovered
            Controls.ToolTip.text: "Mini player: keep watching while you browse (I)"
        }
        Controls.Button {
            Kirigami.Theme.inherit: true
            icon.name: page.isFullscreen ? "view-restore-symbolic" : "view-fullscreen-symbolic"
            onClicked: page.toggleFullscreen()
        }
    }

    // Manual skip buttons: shown whenever playback is inside an intro/outro
    // interval, regardless of the auto-skip setting -- covers the auto-skip
    // -disabled case, and the last-episode exception where auto-skip is
    // deliberately suppressed but the option to skip manually should stay.
    RowLayout {
        anchors.right: parent.right
        anchors.bottom: bottomBar.top
        anchors.margins: Kirigami.Units.largeSpacing
        spacing: Kirigami.Units.smallSpacing

        component SkipButton: AppButton {
            property var range: null
            visible: !page.loadingStream && !!range
                && video.position >= range.start && video.position < range.end
            icon.name: "media-seek-forward-symbolic"
            display: Controls.AbstractButton.TextBesideIcon
            accented: true
        }

        AppButton {
            visible: page.justSkipped !== "" && !page.loadingStream
            text: page.justSkipped === "intro" ? "Skipped intro \u00b7 Watch it" : "Skipped outro \u00b7 Watch it"
            icon.name: "edit-undo-symbolic"
            onClicked: page.undoSkip()
        }

        SkipButton {
            range: page.skipOp
            text: "Skip Intro"
            onClicked: page.skipIntroNow()
        }
        SkipButton {
            range: page.skipEd
            text: "Skip Outro"
            onClicked: page.skipOutroNow()
        }
    }

    // A dark fade behind the controls: over a bright scene (snow, a white
    // flash) the time and the slider were white on white.
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: bottomBar.height + Kirigami.Units.gridUnit * 3
        visible: bottomBar.visible
        gradient: Gradient {
            GradientStop { position: 0; color: "transparent" }
            GradientStop { position: 1; color: Qt.rgba(0, 0, 0, 0.7) }
        }
    }

    ColumnLayout {
        id: bottomBar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: Kirigami.Units.largeSpacing
        visible: !page.loadingStream && page.controlsVisible

        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: seekSlider.implicitHeight

            Controls.Slider {
                Kirigami.Theme.inherit: true
                id: seekSlider
                anchors.fill: parent
                from: 0
                to: Math.max(video.duration, 1)
                value: video.position
                onMoved: video.seekAbsolute(value)
            }

            // Orange intro/outro markers on the seekbar groove -- an
            // approximation (Slider styling can inset the groove slightly
            // from the control's own edges) but close enough to be useful.
            Item {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                height: 4
                visible: video.duration > 0
                z: 1

                Rectangle {
                    visible: !!page.skipOp
                    color: "orange"
                    radius: 2
                    height: parent.height
                    x: page.skipOp ? (page.skipOp.start / video.duration) * parent.width : 0
                    width: page.skipOp
                        ? Math.max(2, ((page.skipOp.end - page.skipOp.start) / video.duration) * parent.width)
                        : 0
                }
                Rectangle {
                    visible: !!page.skipEd
                    color: "orange"
                    radius: 2
                    height: parent.height
                    x: page.skipEd ? (page.skipEd.start / video.duration) * parent.width : 0
                    width: page.skipEd
                        ? Math.max(2, ((page.skipEd.end - page.skipEd.start) / video.duration) * parent.width)
                        : 0
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            // Previous / play / next, in that order, because that is the
            // order every transport control has been in for forty years.
            // Both were already reachable by keyboard and from the phone
            // remote but had no button of their own here.
            Controls.Button {
                Kirigami.Theme.inherit: true
                icon.name: "media-skip-backward-symbolic"
                // Episode numbers can be fractional (x.5 specials), so
                // "there is an earlier one" is not simply number > 1.
                enabled: page.episodeNumber > page.firstEpisodeNumber
                onClicked: page.previousEpisode()
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Previous episode"
            }
            Controls.Button {
                Kirigami.Theme.inherit: true
                icon.name: video.paused ? "media-playback-start" : "media-playback-pause"
                onClicked: video.togglePause()
            }
            Controls.Button {
                Kirigami.Theme.inherit: true
                icon.name: "media-skip-forward-symbolic"
                enabled: !page.isLastEpisode
                onClicked: page.nextEpisode()
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Next episode"
            }
            // Volume: the speaker mutes, the slider sets it. Up to 130%,
            // mpv's own ceiling, for the quiet dubs.
            Controls.Button {
                Kirigami.Theme.inherit: true
                icon.name: video.muted || video.volume === 0 ? "audio-volume-muted-symbolic"
                         : video.volume < 34 ? "audio-volume-low-symbolic"
                         : video.volume < 67 ? "audio-volume-medium-symbolic"
                         : "audio-volume-high-symbolic"
                onClicked: video.setMuted(!video.muted)
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: video.muted ? "Unmute (M)" : "Mute (M)"
            }
            Controls.Slider {
                id: volumeSlider
                Kirigami.Theme.inherit: true
                Layout.preferredWidth: Kirigami.Units.gridUnit * 6
                from: 0
                to: 130
                stepSize: 1
                value: video.muted ? 0 : video.volume
                onMoved: { video.setMuted(false); video.setVolume(value) }
                Controls.ToolTip.visible: hovered || pressed
                Controls.ToolTip.text: (video.muted ? "Muted" : Math.round(video.volume) + "%") + "  (\u2191 \u2193)"
            }
            Controls.Label {
                text: page.formatTime(video.position) + " / " + page.formatTime(video.duration)
            }
            Item { Layout.fillWidth: true }
            // Plain seek steps. These used to be a pair of 85s jumps, there
            // to approximate an OP/ED length back when skip timings were
            // often missing -- the source now ships exact per-episode intro
            // and outro ranges with the stream itself, so the Skip buttons
            // handle that case properly and these can go back to being
            // ordinary seek controls.
            Controls.Button {
                Kirigami.Theme.inherit: true
                text: page.speedLabel(page.speed)
                icon.name: "speedometer"
                display: Controls.AbstractButton.TextBesideIcon
                onClicked: speedMenu.popup()
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Playback speed ([ and ])"
                Controls.Menu {
                    id: speedMenu
                    Kirigami.Theme.inherit: true
                    onOpened: { page.controlsVisible = true; hideTimer.stop() }
                    onClosed: hideTimer.restart()
                    Instantiator {
                        model: page.speeds
                        onObjectAdded: (index, object) => speedMenu.insertItem(index, object)
                        onObjectRemoved: (index, object) => speedMenu.removeItem(object)
                        delegate: Controls.MenuItem {
                            required property var modelData
                            text: page.speedLabel(modelData) + (modelData === 1 ? "  (normal)" : "")
                            checkable: true
                            checked: page.speed === modelData
                            onTriggered: page.speed = modelData
                        }
                    }
                }
            }
            Controls.Button {
                Kirigami.Theme.inherit: true
                text: "10s"
                icon.name: "media-seek-backward-symbolic"
                display: Controls.AbstractButton.TextBesideIcon
                onClicked: page.seekRelative(-10)
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Back 10 seconds (Left arrow: 5s)"
            }
            Controls.Button {
                Kirigami.Theme.inherit: true
                text: "30s"
                icon.name: "media-seek-forward-symbolic"
                display: Controls.AbstractButton.TextBesideIcon
                onClicked: page.seekRelative(30)
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Forward 30 seconds (Right arrow: 5s)"
            }
        }
    }

    Rectangle {
        anchors.centerIn: parent
        visible: page.volumeShown
        radius: Kirigami.Units.smallSpacing * 2
        color: Qt.rgba(0, 0, 0, 0.7)
        implicitWidth: volumeLabel.implicitWidth + Kirigami.Units.gridUnit * 2
        implicitHeight: volumeLabel.implicitHeight + Kirigami.Units.gridUnit
        Controls.Label {
            id: volumeLabel
            anchors.centerIn: parent
            color: "white"
            font.pixelSize: Kirigami.Units.gridUnit * 1.4
            text: page.flashText !== "" ? page.flashText
                : video.muted ? "Muted" : "Volume " + Math.round(video.volume) + "%"
        }
    }

    // "?" toggles this. Keys are the ones every other player uses, so it's
    // a reminder rather than something to learn.
    Rectangle {
        id: shortcutHelp
        visible: false
        anchors.centerIn: parent
        radius: Kirigami.Units.smallSpacing * 2
        color: Qt.rgba(0, 0, 0, 0.8)
        implicitWidth: helpGrid.implicitWidth + Kirigami.Units.gridUnit * 2
        implicitHeight: helpGrid.implicitHeight + Kirigami.Units.gridUnit * 2
        readonly property var shortcuts: [
            ["Space", "Play / pause"], ["\u2190 \u2192", "Back / forward 5s"],
            ["\u2191 \u2193 / wheel", "Volume"], ["M", "Mute"], ["F / F11", "Fullscreen"], ["I", "Mini player"],
            ["S", "Skip intro or outro"], ["N / P", "Next / previous episode"],
            ["[  ]", "Slower / faster"],
            ...(backend.learnFeatures ? [["L", "Learn Japanese on / off"], ["R", "Replay the Japanese line"]] : []),
            ["Esc", "Pause and leave fullscreen"], ["?", "This list"]
        ]
        GridLayout {
            id: helpGrid
            anchors.centerIn: parent
            columns: 2
            columnSpacing: Kirigami.Units.gridUnit
            // Flattened to key, description, key, description... so one
            // Repeater fills both columns in order.
            Repeater {
                model: [].concat(...shortcutHelp.shortcuts)
                delegate: Controls.Label {
                    required property var modelData
                    required property int index
                    text: modelData
                    color: "white"
                    font.bold: index % 2 === 0
                }
            }
        }
    }

    function formatTime(seconds) {
        if (!seconds || seconds < 0) seconds = 0
        let m = Math.floor(seconds / 60)
        let s = Math.floor(seconds % 60)
        return m + ":" + (s < 10 ? "0" : "") + s
    }
}
