// Leaving the player while its controls are faded must give the pointer back.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    property var found: null
    property var player: null
    function log(m) { console.warn("[test] " + m) }
    Connections {
        target: backend
        function onSearchFinished(results) { if (!root.found && results.length) root.found = results[0] }
    }
    Connections {
        target: root.player
        ignoreUnknownSignals: true
        function onPointerHiddenChanged() { root.log("pointerHidden -> " + root.player.pointerHidden + " controls=" + root.player.controlsVisible + " active=" + root.player.Window.active + " current=" + root.player.isCurrentPage + " again=" + root.player.showingPointerAgain) }
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
                root.player = p
                p.controlsVisible = false
                root.log("controls hidden; window active=" + root.active + " hidden=" + p.pointerHidden)
            }
            if (root.step === 5) { root.log("going back"); root.pageStack.goBack() }
            if (root.step === 6) { root.log("now on " + root.pageStack.currentItem); Qt.quit() }
        }
    }
}
