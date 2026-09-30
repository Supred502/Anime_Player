// The media keys reaching the floating mini player: the test sends MPRIS
// PlayPause from outside (as KDE does for the key) and this logs the state.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int tick: 0
    property var found: null
    function log(m) { console.warn("[test] " + m) }
    Connections {
        target: backend
        function onSearchFinished(results) { if (!root.found && results.length) root.found = results[0] }
    }
    Component.onCompleted: { backend.setAutoFullscreenEnabled(false); backend.search("Frieren") }
    Timer {
        interval: 1000; running: true; repeat: true
        onTriggered: {
            root.tick++
            let p = root.pageStack.currentItem
            if (root.tick === 6) root.goTo("browse", "DetailPage.qml", { anime: root.found })
            if (root.tick === 12) p.playEpisode(1, 300)
            if (root.tick === 26) p.toMiniPlayer()
            if (root.tick >= 32 && root.tick % 3 === 0 && root.miniPlayer)
                root.log("t=" + root.tick + " mini playing=" + root.miniPlayer.playing)
            if (root.tick === 34) root.miniPlayer.resizeTo(500)
            if (root.tick === 35) {
                let w = root.miniPlayer.Window.window
                root.log("after resizeTo(500): window " + w.width + "x" + w.height + " ratio " + (w.width / w.height).toFixed(3))
                root.miniPlayer.resizeTo(10)
            }
            if (root.tick === 36) {
                let w = root.miniPlayer.Window.window
                root.log("after resizeTo(10): window " + w.width + "x" + w.height)
            }
            if (root.tick === 50) Qt.quit()
        }
    }
}
