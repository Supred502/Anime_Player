// The player's controller mapping: A pauses, right seeks, up is volume,
// Select opens the on-screen controls to the highlight, B leaves.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    property var found: null
    function log(m) { console.warn("[test] " + m) }
    function video() { return findVideo(root.pageStack.currentItem) }
    function findVideo(item) {
        if (!item) return null
        if (item.hasOwnProperty("currentSubtitleText")) return item
        for (let i = 0; i < item.children.length; i++) { let f = findVideo(item.children[i]); if (f) return f }
        return null
    }
    function state() { let v = video(); return v ? "pos=" + Math.round(v.position) + " paused=" + v.paused + " vol=" + Math.round(v.volume) : "no player" }
    Connections {
        target: backend
        function onSearchFinished(results) { if (!root.found && results.length) root.found = results[0] }
    }
    Component.onCompleted: { backend.setAutoFullscreenEnabled(false); backend.search("Dorohedoro") }
    readonly property var script: [
        [5000, function() { root.goTo("browse", "DetailPage.qml", { anime: root.found }) }],
        [5000, function() { root.pageStack.currentItem.playEpisode(3, 200) }],
        [9000, function() { log("playing: " + state()); gamepad.action("accept") }],
        [1500, function() { log("after A: " + state()); gamepad.action("accept"); gamepad.action("right"); gamepad.action("right") }],
        [2000, function() { log("after A, right x2: " + state()); gamepad.action("down"); gamepad.action("down") }],
        [800, function() { log("after down x2: " + state()); gamepad.action("view") }],
        [800, function() { log("after Select: highlight=" + (gamepadNav.target ? (gamepadNav.target.text || String(gamepadNav.target).split("(")[0]) : "none") + " menuMode=" + gamepadNav.playerMenu) ; gamepad.action("back") }],
        [800, function() { log("after B in menu: menuMode=" + gamepadNav.playerMenu); gamepad.action("back") }],
        [2500, function() { log("after B: page=" + root.pageStack.currentItem.title + " " + state()); Qt.quit() }]
    ]
    Timer {
        interval: root.script[0][0]; running: true
        onTriggered: {
            root.script[root.step][1](); root.step++
            if (root.step < root.script.length) { interval = root.script[root.step][0]; start() }
        }
    }
}
