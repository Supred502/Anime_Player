// Where an episode counts as watched: the outro's start when it's known.
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
    Component.onCompleted: { backend.setAutoFullscreenEnabled(false); backend.search("Frieren") }
    Timer {
        interval: 6000; running: true; repeat: true
        onTriggered: {
            root.step++
            let p = root.pageStack.currentItem
            if (root.step === 1) root.goTo("browse", "DetailPage.qml", { anime: root.found })
            if (root.step === 2) p.playEpisode(1, 60)
            if (root.step === 4) {
                log("outro " + JSON.stringify(p.skipEd) + ", counts as watched at " + Math.round(p.watchedAt)
                    + "s"
                    + ", in player=" + root.inPlayer + ", reported=" + p.reportedWatched)
                Qt.quit()
            }
        }
    }
}
