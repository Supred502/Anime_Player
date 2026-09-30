// The player's volume controls: turned down, remembered for the next episode.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    property var found: null
    function log(m) { console.warn("[test] " + m) }
    function video(p) { return p.findChild ? null : null }
    Connections {
        target: backend
        function onSearchFinished(results) { if (!root.found && results.length) root.found = results[0] }
    }
    Component.onCompleted: { backend.setAutoFullscreenEnabled(false); backend.search("Frieren") }
    // Six presses of Down, at a person's pace.
    Timer {
        id: volumeSteps
        property int n: 0
        interval: 250; repeat: true
        onTriggered: { root.pageStack.currentItem.volumeDown(); if (++n === 6) stop() }
    }
    Timer {
        interval: 6000; running: true; repeat: true
        onTriggered: {
            root.step++
            let p = root.pageStack.currentItem
            switch (root.step) {
            case 1: root.goTo("browse", "DetailPage.qml", { anime: root.found }); break
            case 2: p.playEpisode(1, 200); break
            case 4:
                volumeSteps.start()
                p.controlsVisible = true
                break
            case 5:
                // (No window grab while the player renders: it deadlocks the
                // grab -- a desktop screenshot is taken from outside instead.)
                log("saved volume option=" + backend.learnOption("volume") + " muted=" + backend.learnOption("muted"))
                root.pageStack.goBack()
                break
            case 6: p.playEpisode(2, 100); break
            case 8:
                p.controlsVisible = true
                log("next episode: learnOption volume=" + backend.learnOption("volume"))
                Qt.quit()
                break
            }
        }
    }
}
