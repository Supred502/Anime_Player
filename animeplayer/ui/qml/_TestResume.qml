// Continue resumes at the second you left, not just the episode.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    property var found: null
    function log(m) { console.warn("[test] " + m) }
    Connections {
        target: backend
        function onSearchFinished(results) { if (!root.found && results.length) root.found = results[0] }
    }
    Component.onCompleted: { backend.setAutoFullscreenEnabled(false); backend.search(testMode || "Dorohedoro") }
    Timer {
        interval: 5000; running: true; repeat: true
        onTriggered: {
            root.step++
            let p = root.pageStack.currentItem
            if (root.step === 1) root.goTo("browse", "DetailPage.qml", { anime: root.found })
            if (root.step === 2) p.playEpisode(2, 400)
            if (root.step === 6) { log("leaving the player"); root.pageStack.goBack() }
            if (root.step === 7) {
                log("progress " + JSON.stringify(p.localProgress) + " -> resume ep " + p.resumeEpisode + " at " + p.resumeAt)
                p.continueWatching()
            }
            if (root.step === 10) {
                log("player now: episode " + p.episodeNumber + " state " + JSON.stringify(backend.phoneStateForTest ? "" : ""))
                root.pageStack.goBack()
            }
            if (root.step === 11) {
                log("after second visit: " + JSON.stringify(p.localProgress))
                Qt.quit()
            }
        }
    }
}
