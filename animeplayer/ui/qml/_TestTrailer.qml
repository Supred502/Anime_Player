// Opens Frieren, waits for AniList's trailer id, plays it in the overlay.
import QtQuick
AppWindow {
    id: root
    width: 1600; height: 1000
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    function log(m) { console.warn("[test] " + m) }
    TrailerOverlay { id: t }
    Connections {
        target: backend
        function onSearchFinished(results) {
            if (results.length && root.pageStack.depth === 1)
                root.pageStack.push(Qt.resolvedUrl("DetailPage.qml"), { anime: results[0] })
        }
        function onTrailerReady(id, v, a) { root.log("ready " + id + " audio=" + (a !== "")) }
        function onTrailerFailed(id, m) { root.log("failed " + m) }
    }
    Component.onCompleted: backend.search("Frieren")
    Timer {
        interval: 500; running: true; repeat: true
        property bool started: false
        onTriggered: {
            let p = root.pageStack.currentItem
            if (!started && p && p.trailer) { started = true; root.log("trailer id " + p.trailer); t.play(p.trailer) }
        }
    }
    Timer { interval: 40000; running: true; onTriggered: { root.log("status '" + t.status + "' visible " + t.visible); Qt.quit() } }
}
