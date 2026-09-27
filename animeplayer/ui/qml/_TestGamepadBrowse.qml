// Browse with a controller, at the Steam Deck's 1280x800: a run of D-pad
// presses at a person's pace, logging after each one where the highlight
// is, where it is on screen and how far the page scrolled -- so a jump
// shows as a line that doesn't follow from the one before.
import QtQuick
AppWindow {
    id: root
    width: 1280
    height: 800
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    property int shot: 0
    function log(m) { console.warn("[test] " + m) }
    function flick(item) {
        for (let p = item ? item.parent : null; p; p = p.parent) if (p instanceof Flickable) return p
        return null
    }
    function describe(label) {
        let t = gamepadNav.target
        if (!t) { log(label + ": highlight=none"); return }
        let r = gamepadNav.rectOf(t)
        let f = root.flick(t)
        log(label + ": " + String(t).split("(")[0].split("_QML")[0]
            + " '" + (t.title || t.text || "") + "'"
            + " at " + Math.round(r.x) + "," + Math.round(r.y) + " " + Math.round(r.width) + "x" + Math.round(r.height)
            + " scroll=" + (f ? Math.round(f.contentY) : "-")
            + (r.y < 0 || r.y + r.height > root.height ? "  OFF-SCREEN" : ""))
    }
    function shoot() { windowChrome.saveScreenshot(root, testShots + "/" + (++root.shot) + ".png") }
    property var homePresses: ["down", "down", "down", "down", "right", "right", "right", "right", "right",
                               "right", "right", "right", "down", "left", "down", "right", "right", "down",
                               "down", "down", "up", "up", "up", "up", "up", "up", "up"]
    property var presses: ["down", "down", "right", "right", "right", "right", "right", "right",
                           "down", "down", "down", "left", "left", "down", "down", "down", "down",
                           "down", "down", "down", "down", "down", "down", "right",
                           "down", "down", "down", "down", "down", "down", "down", "down",
                           "up", "up", "up", "left", "up", "up", "up", "up"]
    // ANIMEPLAYER_TEST_MODE=home runs the same on Home's shelves instead.
    readonly property bool onHome: testMode === "home"
    Timer { interval: 9000; running: !root.onHome; onTriggered: root.goBrowse() }
    // Steam's desktop layout (the Deck in Desktop Mode) also types a key for
    // the D-pad and A/B; the second half of the run sends both, as it does.
    readonly property var keys: ({ up: Qt.Key_Up, down: Qt.Key_Down, left: Qt.Key_Left,
                                   right: Qt.Key_Right, accept: Qt.Key_Return, back: Qt.Key_Escape })
    Timer {
        id: pacer
        interval: 350; repeat: true
        running: false
        onTriggered: {
            let presses = root.onHome ? root.homePresses : root.presses
            if (root.step >= presses.length) { stop(); Qt.quit(); return }
            let withKey = !root.onHome && root.step >= root.presses.length / 2
            let a = presses[root.step++]
            if (a === "up" && gamepadNav.target) {
                let from = gamepadNav.rectOf(gamepadNav.target)
                let near = gamepadNav.candidates().map((c) => [c, gamepadNav.rectOf(c)])
                    .filter((cr) => cr[1].y < from.y && cr[1].x < from.x + from.width && cr[1].x + cr[1].width > from.x)
                log("   above: " + near.map((cr) => String(cr[0]).split("(")[0].split("_QML")[0] + "@" + Math.round(cr[1].x) + "," + Math.round(cr[1].y) + " " + Math.round(cr[1].width) + "x" + Math.round(cr[1].height)).join(" | "))
            }
            gamepad.simulate(a)
            if (withKey) windowChrome.testKey(root, root.keys[a], 0)
            settle.restart()
            Qt.callLater(function() {
                root.describe(root.step + " " + a + (withKey ? "+key" : ""))
                let f = root.activeFocusItem
                if (withKey) log("   focus=" + String(f).split("(")[0])
            })
        }
    }
    // After the glide: what the screen shows once it has caught up.
    Timer { id: settle; interval: 260; onTriggered: { root.describe("   settled"); root.shoot() } }
    Timer { interval: 17000; running: true; onTriggered: { root.describe("start"); pacer.start() } }
}
