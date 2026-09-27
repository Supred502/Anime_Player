// Plays an episode (and in ANIMEPLAYER_TEST_MODE=mini, hands it to the mini
// player), then quits: the process must exit cleanly, not crash. It used to
// segfault on every quit made mid-episode -- see MpvVideoItem.close_all().
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    property var found: null
    Connections {
        target: backend
        function onSearchFinished(results) { if (!root.found && results.length) root.found = results[0] }
    }
    Component.onCompleted: { backend.setAutoFullscreenEnabled(false); backend.search("Frieren") }
    Timer {
        interval: 5000; running: true; repeat: true
        onTriggered: {
            root.step++
            if (root.step === 1) root.goTo("browse", "DetailPage.qml", { anime: root.found })
            if (root.step === 2) root.pageStack.currentItem.playEpisode(1, 300)
            if (root.step === 4 && testMode === "mini") root.pageStack.currentItem.toMiniPlayer()
            if (root.step === 6) { console.warn("[test] quitting"); Qt.quit() }
        }
    }
}
