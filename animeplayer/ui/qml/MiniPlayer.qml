// The episode, still playing, in the corner of the window while you browse.
// Started from the player (its mini player button, or I); it picks up at the
// same second, keeps saving your place, and the expand button goes back to
// the full player at wherever it has got to.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import AnimePlayer 1.0

Rectangle {
    id: mini

    // { anime, episodeId, episodeNumber, dub, url, referer, subtitle, position }
    required property var show
    signal expand(real position)
    signal closed()

    width: Kirigami.Units.gridUnit * 20
    height: Math.round(width * 9 / 16)
    radius: Kirigami.Units.smallSpacing * 2
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
        Component.onCompleted: video.loadUrl(mini.show.url, mini.show.referer, mini.show.subtitle)
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

    // How far through, always visible along the bottom edge.
    Rectangle {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        height: 3
        width: video.duration > 0 ? parent.width * video.position / video.duration : 0
        color: Kirigami.Theme.highlightColor
    }
}
