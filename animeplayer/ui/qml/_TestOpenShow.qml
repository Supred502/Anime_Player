// How long opening a show's page holds up the window: to the first frame,
// then the longest gap between frames while its data arrives.
import QtQuick
AppWindow {
    id: root
    width: 1600; height: 1000
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property var found: null
    property real started: 0
    property real last: 0
    property real worst: 0
    property int rounds: 0
    function log(m) { console.warn("[test] " + m) }
    Connections {
        target: backend
        function onSearchFinished(results) { if (!root.found && results.length) root.found = results[0] }
    }
    Component.onCompleted: backend.search(Qt.application.arguments.indexOf("frieren") >= 0 ? "Frieren" : "One Piece")
    FrameAnimation {
        running: true
        onTriggered: {
            let now = Date.now()
            if (root.started && root.last === 0) { root.log("first frame " + (now - root.started) + " ms"); root.last = now; return }
            if (root.last) { root.worst = Math.max(root.worst, now - root.last); root.last = now }
        }
    }
    Timer {
        interval: 5000; running: true; repeat: true
        onTriggered: {
            if (root.started) {
                root.log("worst frame gap after: " + root.worst + " ms")
                root.started = 0; root.last = 0; root.worst = 0
                root.pageStack.goBack()
                if (++root.rounds >= 3) Qt.quit()
                return
            }
            root.started = Date.now()
            root.pageStack.push(Qt.resolvedUrl("DetailPage.qml"), { anime: root.found })
        }
    }
}
