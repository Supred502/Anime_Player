// The episode, still playing, while you do something else. Started from the
// player (its mini player button, or I); it picks up at the same second,
// keeps saving your place, and the expand button goes back to the full
// player at wherever it has got to.
//
// Normally in a window of its own, over other apps (`floating`: dragged to
// move, pulled at the corner to resize -- see AppWindow). Where a second
// window can't work -- the Steam Deck's Gaming Mode shows one at a time --
// it sits in the corner of the app's window instead.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import AnimePlayer 1.0

Rectangle {
    id: mini

    // { anime, episodeId, episodeNumber, dub, url, referer, subtitle, position }
    required property var show
    property bool floating: false
    signal expand(real position)
    signal closed()
    signal moveRequested()
    signal resizeRequested()

    implicitWidth: Kirigami.Units.gridUnit * 20
    implicitHeight: Math.round(implicitWidth * 9 / 16)
    radius: mini.floating ? 0 : Kirigami.Units.smallSpacing * 2
    color: "black"
    border.width: 1
    border.color: Qt.rgba(1, 1, 1, 0.15)
    clip: true

    property bool seeked: false
    function volumeNow() { return Math.round(video.volume) + (video.muted ? " (muted)" : "") }
    readonly property bool hovered: hover.hovered

    MpvVideoItem {
        id: video
        anchors.fill: parent
        anchors.margins: 1
        Component.onDestruction: close()
        Component.onCompleted: {
            // The volume the full player was at (see PlayerPage).
            let saved = parseFloat(backend.learnOption("volume"))
            if (saved >= 0) video.setVolume(saved)
            video.setMuted(backend.learnOption("muted") === "true")
            video.loadUrl(mini.show.url, mini.show.referer, mini.show.subtitle)
        }
        onDurationChanged: (value) => {
            if (value > 0 && !mini.seeked) {
                mini.seeked = true
                video.seekAbsolute(mini.show.position)
            }
        }
        onEndOfFile: mini.closed()
    }

    // Your place, every few seconds, under the show this episode belongs to
    // (not whichever show's page is open meanwhile).
    function savePlace() {
        if (video.position > 0)
            backend.saveProgressFor(mini.show.anime, mini.show.episodeId, mini.show.episodeNumber, video.position)
    }
    Timer { interval: 5000; running: true; repeat: true; onTriggered: mini.savePlace() }
    // The screen stays on while it plays, as in the full player.
    readonly property bool playing: video.duration > 0 && !video.paused
    onPlayingChanged: backend.setKeepScreenAwake(mini.playing)
    // The media keys, from whatever app is in front (see media_session.py).
    function publishMedia() {
        if (video.duration <= 0) return
        mediaSession.update(mini.show.anime.title || "", "Episode " + mini.show.episodeNumber,
                            mini.show.anime.poster_url || "", video.duration, !video.paused, false, false)
    }
    Connections {
        target: video
        function onPausedChanged() { mini.publishMedia() }
        function onDurationChanged() { mini.publishMedia() }
    }
    Connections {
        target: mediaSession
        function onAction(name) {
            if (name === "playpause") video.togglePause()
            else if (name === "play") video.setPaused(false)
            else if (name === "pause") video.setPaused(true)
        }
    }
    Component.onDestruction: {
        mediaSession.clear()
        mini.savePlace()
        backend.setKeepScreenAwake(false)
    }

    HoverHandler { id: hover }
    // When the window was last picked up to move. The compositor does the
    // move and hands the press back afterwards, which read as a click (and
    // a second one as a double-click, which opened the full player): a
    // click that soon after a move is ignored.
    property real movedAt: 0
    TapHandler {
        onTapped: if (Date.now() - mini.movedAt > 700) video.togglePause()
        // In the app's corner only; the floating window has its button.
        onDoubleTapped: if (!mini.floating && Date.now() - mini.movedAt > 700) mini.expand(video.position)
    }
    // Floating: dragged anywhere on the picture moves the window. The
    // compositor does the moving (startSystemMove), which is the only way a
    // Wayland window can be moved, and gives snapping for free.
    DragHandler {
        // Not from the resize grip: this took drags that started there (or
        // left it as the pointer moved on) and moved the window instead.
        enabled: mini.floating && !gripHover.hovered && !gripDrag.active
        target: null
        onActiveChanged: if (active) { mini.movedAt = Date.now(); mini.moveRequested() }
    }
    // The scroll wheel anywhere on it is volume. A MouseArea taking only
    // the wheel (clicks pass through to the handlers below): a WheelHandler
    // here never saw the wheel at all.
    MouseArea {
        anchors.fill: parent
        z: 10
        acceptedButtons: Qt.NoButton
        onWheel: (wheel) => {
            if (wheel.angleDelta.y === 0) return
            // From where the last notch left it: the player reports its
            // volume back a moment later, and quick notches read the old one.
            let base = volumeFlash.running ? mini.volumeTarget : video.volume
            mini.volumeTarget = Math.max(0, Math.min(130, base + wheel.angleDelta.y / 120 * 5))
            video.setMuted(false)
            video.setVolume(mini.volumeTarget)
            volumeFlash.restart()
        }
    }
    // What the wheel just did, on the picture for a moment.
    property real volumeTarget: 0
    Timer { id: volumeFlash; interval: 1000 }
    Rectangle {
        anchors.centerIn: parent
        z: 9
        visible: volumeFlash.running
        radius: Kirigami.Units.smallSpacing * 2
        color: Qt.rgba(0, 0, 0, 0.7)
        implicitWidth: volumeText.implicitWidth + Kirigami.Units.gridUnit
        implicitHeight: volumeText.implicitHeight + Kirigami.Units.smallSpacing * 2
        Controls.Label {
            id: volumeText
            anchors.centerIn: parent
            color: "white"
            font.bold: true
            text: video.muted ? "Muted" : "Volume " + Math.round(mini.volumeTarget || video.volume) + "%"
        }
    }
    focus: true
    Keys.onPressed: (event) => {
        if (event.key === Qt.Key_Space || event.key === Qt.Key_MediaTogglePlayPause) video.togglePause()
        else if (event.key === Qt.Key_MediaPlay) video.setPaused(false)
        else if (event.key === Qt.Key_MediaPause) video.setPaused(true)
        else if (event.key === Qt.Key_Left) video.seekAbsolute(Math.max(0, video.position - 5))
        else if (event.key === Qt.Key_Right) video.seekAbsolute(video.position + 5)
        else if (event.key === Qt.Key_Up) { video.setMuted(false); video.setVolume(video.volume + 10) }
        else if (event.key === Qt.Key_Down) video.setVolume(video.volume - 10)
        else if (event.key === Qt.Key_M) video.setMuted(!video.muted)
        else if (event.key === Qt.Key_Escape) mini.closed()
        else if (event.key === Qt.Key_Return || event.key === Qt.Key_F) mini.expand(video.position)
        else return
        event.accepted = true
    }

    // Controls, over the video while the pointer is on it.
    Rectangle {
        anchors.fill: parent
        visible: mini.hovered || video.paused
        gradient: Gradient {
            GradientStop { position: 0; color: Qt.rgba(0, 0, 0, 0.7) }
            GradientStop { position: 0.4; color: "transparent" }
            GradientStop { position: 0.7; color: "transparent" }
            GradientStop { position: 1; color: Qt.rgba(0, 0, 0, 0.7) }
        }

        RowLayout {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Kirigami.Units.smallSpacing
            Controls.Label {
                Layout.fillWidth: true
                Layout.leftMargin: mini.floating ? Kirigami.Units.gridUnit * 1.2 : Kirigami.Units.smallSpacing
                elide: Text.ElideRight
                color: "white"
                font.bold: true
                text: (mini.show.anime.title || "") + " · Episode " + mini.show.episodeNumber
            }
            Controls.ToolButton {
                icon.name: "view-fullscreen-symbolic"
                icon.color: "white"
                onClicked: mini.expand(video.position)
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Back to the full player"
            }
            Controls.ToolButton {
                icon.name: "window-close-symbolic"
                icon.color: "white"
                onClicked: mini.closed()
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Stop"
            }
        }

        // The media buttons, along the bottom: back and forward ten seconds
        // either side of play/pause, the time, and mute. Clear of the
        // bottom-right corner, where the resize grip is.
        RowLayout {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: Kirigami.Units.smallSpacing
            anchors.rightMargin: Kirigami.Units.smallSpacing
            anchors.bottomMargin: Kirigami.Units.smallSpacing
            spacing: 0
            MiniButton {
                iconName: "media-seek-backward-symbolic"
                tip: "Back 10 seconds (\u2190: 5)"
                onClicked: video.seekAbsolute(Math.max(0, video.position - 10))
            }
            MiniButton {
                iconName: video.paused ? "media-playback-start-symbolic" : "media-playback-pause-symbolic"
                tip: video.paused ? "Play (Space)" : "Pause (Space)"
                onClicked: video.togglePause()
            }
            MiniButton {
                iconName: "media-seek-forward-symbolic"
                tip: "Forward 10 seconds (\u2192: 5)"
                onClicked: video.seekAbsolute(video.position + 10)
            }
            Controls.Label {
                Layout.leftMargin: Kirigami.Units.smallSpacing
                color: "white"
                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                function clock(s) {
                    s = Math.max(0, Math.floor(s))
                    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0")
                }
                text: clock(video.position) + " / " + clock(video.duration)
            }
            Item { Layout.fillWidth: true }
            MiniButton {
                iconName: video.muted || video.volume === 0 ? "audio-volume-muted-symbolic"
                        : video.volume < 50 ? "audio-volume-low-symbolic" : "audio-volume-high-symbolic"
                tip: (video.muted ? "Unmute" : "Mute (M)") + " \u2014 scroll for volume ("
                     + Math.round(video.volume) + "%)"
                onClicked: video.setMuted(!video.muted)
            }
        }
    }

    component MiniButton: Controls.ToolButton {
        property string iconName: ""
        property string tip: ""
        icon.name: iconName
        icon.color: "white"
        Controls.ToolTip.visible: hovered
        Controls.ToolTip.text: tip
    }

    // Floating: a grip in the top-left corner resizes the window. Top-left,
    // not bottom-right: the window lives in the screen's bottom-right corner,
    // where a bottom-right grip can only be pulled off the screen -- it could
    // shrink, never grow. The compositor does the resizing (the only way a
    // Wayland window's position can move with its edge); AppWindow puts the
    // shape back to 16:9 when it's let go.
    Item {
        visible: mini.floating && (mini.hovered || video.paused)
        anchors.left: parent.left
        anchors.top: parent.top
        width: Kirigami.Units.gridUnit * 1.2
        height: width
        z: 5
        Canvas {
            anchors.fill: parent
            onPaint: {
                let c = getContext("2d")
                c.strokeStyle = "rgba(255,255,255,0.8)"
                c.lineWidth = 1.5
                for (let i = 1; i <= 3; i++) {
                    c.beginPath()
                    c.moveTo(i * 5, 2)
                    c.lineTo(2, i * 5)
                    c.stroke()
                }
            }
        }
        HoverHandler { id: gripHover; cursorShape: Qt.SizeFDiagCursor }
        DragHandler {
            id: gripDrag
            target: null
            grabPermissions: PointerHandler.TakeOverForbidden
            onActiveChanged: if (active) {
                mini.movedAt = Date.now()
                mini.resizeRequested()
            }
        }
    }

    // How far through, always visible along the bottom edge.
    Rectangle {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        height: 3
        width: video.duration > 0 ? parent.width * video.position / video.duration : 0
        // The app's accent itself: in a window of its own the pages'
        // theming (AppTheming) doesn't reach it.
        color: backend.theme.accent || Kirigami.Theme.highlightColor
    }
}
