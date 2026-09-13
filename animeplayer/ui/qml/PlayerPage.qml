import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import AnimePlayer 1.0

Kirigami.Page {
    id: page
    property var anime: ({})
    property int episodeId: 0
    property real episodeNumber: 0
    property bool dub: false
    title: (anime.title || "") + " - Episode " + episodeNumber
    padding: 0
    focus: true // needed for Keys.onPressed below to actually receive events

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
        page.startLoad()
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

    Component.onDestruction: {
        backend.setKeepScreenAwake(false)
        if (page.isFullscreen) applicationWindow().visibility = Window.Windowed
    }

    function toggleFullscreen() {
        page.isFullscreen = !page.isFullscreen
        applicationWindow().visibility = page.isFullscreen ? Window.FullScreen : Window.Windowed
        page.globalToolBarStyle = page.isFullscreen ? Kirigami.ApplicationHeaderStyle.None : page.normalToolBarStyle
    }

    // Shared actions -- used by both the keyboard shortcuts below and by
    // remote-control commands (see onRemoteCommand in the Connections block),
    // so there's exactly one implementation of each behavior.
    function seekRelative(deltaSeconds) {
        video.seekAbsolute(Math.max(0, Math.min(video.duration, video.position + deltaSeconds)))
    }
    function skipIntroNow() {
        if (page.skipOp) { page.opAutoSkipped = true; video.seekAbsolute(page.skipOp.end) }
    }
    function skipOutroNow() {
        if (page.skipEd) { page.edAutoSkipped = true; video.seekAbsolute(page.skipEd.end) }
    }
    function nextEpisode() { backend.loadNextEpisode(page.episodeNumber, page.dub) }
    function previousEpisode() { backend.loadPreviousEpisode(page.episodeNumber, page.dub) }
    function volumeUp() { video.setVolume(video.volume + 10) }
    function volumeDown() { video.setVolume(video.volume - 10) }
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
        }
    }

    Connections {
        target: backend
        function onStreamReady(url, referer, subtitleUrl) {
            page.loadingStream = false
            page.stalled = false
            stallTimer.restart()
            // referer and subtitleUrl are both load-bearing, not optional
            // extras -- see MpvVideoItem.loadUrl.
            video.loadUrl(url, referer, subtitleUrl)
        }
        function onStreamFailed(message) {
            page.loadingStream = false
            showPassiveNotification("Playback failed: " + message)
        }
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
            page.autoRetried = false
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
        onTriggered: backend.savePlaybackPosition(page.episodeId, page.episodeNumber, video.position)
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
            // Auto-skip: seek past the interval the moment playback enters it.
            // The *AutoSkipped guards stop this from firing again every
            // position tick for the rest of the interval (position keeps
            // reporting "inside" it for a moment after the seek lands).
            if (!page.autoSkipActive) return
            if (page.skipOp && !page.opAutoSkipped && value >= page.skipOp.start && value < page.skipOp.end) {
                page.opAutoSkipped = true
                video.seekAbsolute(page.skipOp.end)
            }
            if (page.skipEd && !page.edAutoSkipped && value >= page.skipEd.start && value < page.skipEd.end) {
                page.edAutoSkipped = true
                video.seekAbsolute(page.skipEd.end)
            }
        }
        onDurationChanged: (value) => { if (value > 0) { page.stalled = false; stallTimer.stop() } }
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
            showPassiveNotification("Playback error: " + message)
        }
        onPausedChanged: {
            page.controlsVisible = true
            hideTimer.restart()
        }
        onEndOfFile: {
            if (page.autoNextEnabled) page.nextEpisode()
        }
    }

    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        // The pointer sat on top of the video forever once the controls had
        // faded out. It goes away with them, and comes back on the first
        // movement (onPositionChanged below still fires while it's hidden).
        cursorShape: page.controlsVisible ? Qt.ArrowCursor : Qt.BlankCursor
        onPositionChanged: { page.controlsVisible = true; hideTimer.restart() }
        onClicked: video.togglePause()
    }

    ColumnLayout {
        anchors.centerIn: parent
        visible: page.loadingStream || page.stalled
        spacing: Kirigami.Units.smallSpacing

        Controls.BusyIndicator {
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
            Layout.alignment: Qt.AlignHCenter
            visible: page.stalled
            text: "Retry"
            icon.name: "view-refresh-symbolic"
            onClicked: page.startLoad()
        }
    }

    RowLayout {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: Kirigami.Units.largeSpacing
        visible: !page.loadingStream && page.controlsVisible

        Controls.ComboBox {
            id: qualityCombo
            model: qualityModel
            textRole: "label"
            onActivated: backend.selectQuality(currentIndex === 0 ? "" : currentText)
        }
        Controls.Button {
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

        component SkipButton: Controls.Button {
            property var range: null
            visible: !page.loadingStream && range
                && video.position >= range.start && video.position < range.end
            icon.name: "media-seek-forward-symbolic"
            display: Controls.AbstractButton.TextBesideIcon
            highlighted: true
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
            Controls.Button {
                icon.name: video.paused ? "media-playback-start" : "media-playback-pause"
                onClicked: video.togglePause()
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
                text: "10s"
                icon.name: "media-seek-backward-symbolic"
                display: Controls.AbstractButton.TextBesideIcon
                onClicked: page.seekRelative(-10)
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Back 10 seconds (Left arrow: 5s)"
            }
            Controls.Button {
                text: "30s"
                icon.name: "media-seek-forward-symbolic"
                display: Controls.AbstractButton.TextBesideIcon
                onClicked: page.seekRelative(30)
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Forward 30 seconds (Right arrow: 5s)"
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
