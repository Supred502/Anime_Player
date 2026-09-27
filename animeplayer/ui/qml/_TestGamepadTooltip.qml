// Rests the controller highlight on an episode until its tooltip shows,
// then keeps moving: it must not get stuck.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property var found: null
    property int step: 0
    function log(m) { console.warn("[test] " + m) }
    function name(t) { return t ? (t.text || (t.model ? "episode " + t.model.number : String(t).split("(")[0])) : "none" }
    Connections {
        target: backend
        function onSearchFinished(results) { if (!root.found && results.length) root.found = results[0] }
    }
    Component.onCompleted: backend.search("Frieren")
    Timer {
        interval: 3000; running: true; repeat: true
        onTriggered: {
            root.step++
            if (root.step === 1) root.goTo("browse", "DetailPage.qml", { anime: root.found })
            if (root.step === 3) { let p = root.pageStack.currentItem; p.listView = false
                                   for (let i = 0; i < 12; i++) {
                                       gamepad.action("down")
                                       let t = gamepadNav.target
                                       if (t && t.model && t.model.number !== undefined) break
                                   } }
            if (root.step === 5) {
                let tips = 0; let ov = gamepadNav.overlay.children
                for (let i = 0; i < ov.length; i++) if (ov[i].visible && String(ov[i]).indexOf("PopupItem") >= 0) tips++
                log("resting on " + name(gamepadNav.target) + " open popups=" + tips + " scope=" + String(gamepadNav.scope()).split("(")[0])
            }
            if (root.step === 6) { gamepad.action("right"); gamepad.action("right") }
            if (root.step === 7) { log("after right x2: " + name(gamepadNav.target)); Qt.quit() }
        }
    }
}
