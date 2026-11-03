// The show's trailer, played in the app: Game Mode on the Deck has no
// browser to send anyone to. yt-dlp finds the stream (backend.resolveTrailer);
// the video item only exists while this is open, so mpv is gone with it.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import AnimePlayer 1.0

Controls.Popup {
    id: overlay

    property string youtubeId: ""
    property string status: ""   // "" while playing; else what to say instead

    function play(id) {
        youtubeId = id
        status = "Loading trailer..."
        open()
        backend.resolveTrailer(id)
    }

    parent: Controls.Overlay.overlay
    anchors.centerIn: parent
    width: parent ? parent.width : 0
    height: parent ? parent.height : 0
    modal: true
    padding: 0
    closePolicy: Controls.Popup.CloseOnEscape
    background: Rectangle { color: "black" }
    onClosed: youtubeId = ""

    Connections {
        target: backend
        function onTrailerReady(id, video, audio) {
            if (id !== overlay.youtubeId || !player.item) return
            overlay.status = ""
            player.item.loadUrlWithAudio(video, audio)
        }
        function onTrailerFailed(id, message) {
            if (id === overlay.youtubeId) overlay.status = message
        }
    }

    contentItem: Item {
        Loader {
            id: player
            anchors.fill: parent
            active: overlay.visible
            sourceComponent: MpvVideoItem {
                Component.onDestruction: close()
                onEndOfFile: overlay.close()
                onPlaybackError: (message) => overlay.status = "Couldn't play the trailer: " + message
            }
        }

        // Click the picture to pause, as in the player.
        TapHandler { onTapped: if (player.item) player.item.togglePause() }

        Controls.Label {
            anchors.centerIn: parent
            visible: overlay.status !== ""
            text: overlay.status
            color: "white"
            font.pixelSize: Kirigami.Theme.defaultFont.pixelSize * 1.3
        }

        AppButton {
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.margins: Kirigami.Units.largeSpacing * 2
            text: "Back"
            icon.name: "go-previous-symbolic"
            onClicked: overlay.close()
        }
    }
}
