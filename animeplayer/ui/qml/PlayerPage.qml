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

    function startLoad() {
        page.loadingStream = true
        page.stalled = false
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
    Component.onDestruction: {
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
        function onStreamReady(url) {
            page.loadingStream = false
            page.stalled = false
            stallTimer.restart()
            video.loadUrl(url)
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
        onTriggered: if (!seekSlider.pressed) page.controlsVisible = false
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
            page.stalled = true
            showPassiveNotification("Playback error: " + message)
        }
        onEndOfFile: {
            if (page.autoNextEnabled) page.nextEpisode()
        }
    }

    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
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
    Controls.Button {
        anchors.right: parent.right
        anchors.bottom: bottomBar.top
        anchors.margins: Kirigami.Units.largeSpacing
        visible: !page.loadingStream && page.skipOp
            && video.position >= page.skipOp.start && video.position < page.skipOp.end
        text: "Skip Intro"
        icon.name: "media-seek-forward-symbolic"
        onClicked: page.skipIntroNow()
    }
    Controls.Button {
        anchors.right: parent.right
        anchors.bottom: bottomBar.top
        anchors.margins: Kirigami.Units.largeSpacing
        visible: !page.loadingStream && page.skipEd
            && video.position >= page.skipEd.start && video.position < page.skipEd.end
        text: "Skip Outro"
        icon.name: "media-seek-forward-symbolic"
        onClicked: page.skipOutroNow()
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
            Controls.Button {
                icon.name: video.paused ? "media-playback-start" : "media-playback-pause"
                onClicked: video.togglePause()
            }
            Controls.Label {
                text: page.formatTime(video.position) + " / " + page.formatTime(video.duration)
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
