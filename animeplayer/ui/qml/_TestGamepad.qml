// Drives the app through the same actions a controller's buttons produce,
// and pictures each step. The real controller's connection is logged too.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    function log(m) { console.warn("[test] " + m) }
    function press(a) { gamepad.action(a) }
    function describe() {
        let n = gamepadNav
        let t = n.target
        return "page=" + (root.pageStack.currentItem ? root.pageStack.currentItem.title : "?")
             + " highlight=" + (t ? String(t).split("(")[0] + (t.text ? " '" + t.text + "'" : "")
                                   + (t.title ? " '" + t.title + "'" : "") : "none")
             + " ring=" + n.active
    }
    function shoot(name) { windowChrome.saveScreenshot(root, testShots + "/" + name + ".png") }
    Connections {
        target: gamepad
        function onConnected(name) { log("REAL controller connected: " + name) }
    }
    readonly property var script: [
        [8000, function() { log("connected now: " + gamepad.isConnected()); press("down") }],
        [900, function() { log("after down: " + describe()); shoot("1-first-highlight") }],
        [700, function() { press("down"); }],
        [700, function() { press("right"); press("right") }],
        [900, function() { log("after down,right,right: " + describe()); shoot("2-moved") }],
        [700, function() { press("accept") }],
        [6000, function() { log("after A: " + describe()); shoot("3-opened") }],
        [700, function() { press("back") }],
        [2500, function() { log("after B: " + describe()) }],
        [700, function() { press("rb") }],
        [3000, function() { log("after RB: " + describe() + " section=" + root.section) }],
        [700, function() { press("y") }],
        [2500, function() { log("after Y: " + describe()); shoot("4-keyboard") }],
        [300, function() { press("accept") }],   // types the first key the highlight is on
        [300, function() { let s = gamepadNav.scope(); let c = gamepadNav.candidates()
                           log("keyboard scope=" + String(s).split("(")[0] + " candidates=" + c.length
                               + " target in them=" + (c.indexOf(gamepadNav.target) >= 0))
                           press("right"); log("after right: " + describe()); press("accept") }],
        [300, function() { press("y") }],        // space
        [300, function() { press("x") }],        // delete
        [800, function() { log("typed so far: '" + gamepadNav.keyboardText() + "'"); shoot("5-typed") }],
        [300, function() { press("back") }],
        [1000, function() { log("keyboard closed: " + !gamepadNav.keyboardOpen()); Qt.quit() }]
    ]
    Timer {
        interval: root.script[0][0]; running: true
        onTriggered: {
            root.script[root.step][1]()
            root.step++
            if (root.step < root.script.length) { interval = root.script[root.step][0]; start() }
        }
    }
}
