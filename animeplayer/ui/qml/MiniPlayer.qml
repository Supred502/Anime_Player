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
    Component.onDestruction: {
        mini.savePlace()
        backend.setKeepScreenAwake(false)
    }

    HoverHandler { id: hover }
    TapHandler {
        onTapped: video.togglePause()
        onDoubleTapped: mini.expand(video.position)
    }
    // Floating: dragged anywhere on the picture moves the window. The
    // compositor does the moving (startSystemMove), which is the only way a
    // Wayland window can be moved, and gives snapping for free.
    DragHandler {
        enabled: mini.floating
        target: null
        onActiveChanged: if (active) mini.moveRequested()
    }
    WheelHandler {
        onWheel: (event) => {
            if (event.angleDelta.y === 0) return
            video.setMuted(false)
            video.setVolume(video.volume + event.angleDelta.y / 120 * 5)
        }
    }
    focus: true
    Keys.onPressed: (event) => {
        if (event.key === Qt.Key_Space || event.key === Qt.Key_MediaTogglePlayPause) video.togglePause()
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
                Layout.leftMargin: Kirigami.Units.smallSpacing
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

        Controls.ToolButton {
            anchors.centerIn: parent
            icon.name: video.paused ? "media-playback-start-symbolic" : "media-playback-pause-symbolic"
            icon.color: "white"
            icon.width: Kirigami.Units.iconSizes.medium
            icon.height: Kirigami.Units.iconSizes.medium
            onClicked: video.togglePause()
        }

        Controls.Label {
            anchors.left: parent.left
            anchors.bottom: parent.bottom
            anchors.margins: Kirigami.Units.smallSpacing * 2
            color: "white"
            font.pixelSize: Kirigami.Theme.smallFont.pixelSize
            function clock(s) {
                s = Math.max(0, Math.floor(s))
                return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0")
            }
            text: clock(video.position) + " / " + clock(video.duration)
        }
    }

    // Floating: a grip in the bottom-right corner resizes the window.
    Item {
        visible: mini.floating && (mini.hovered || video.paused)
        anchors.right: parent.right
        anchors.bottom: parent.bottom
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
                    c.moveTo(width - i * 5, height - 2)
                    c.lineTo(width - 2, height - i * 5)
                    c.stroke()
                }
            }
        }
        HoverHandler { cursorShape: Qt.SizeFDiagCursor }
        DragHandler {
            target: null
            onActiveChanged: if (active) mini.resizeRequested()
        }
    }

    // How far through, always visible along the bottom edge.
    Rectangle {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        height: 3
        width: video.duration > 0 ? parent.width * video.position / video.duration : 0
        color: Kirigami.Theme.highlightColor
    }
}
