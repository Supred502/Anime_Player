// How long each section takes to appear after its nav entry is clicked:
// from the click to the next frame drawn (the GUI thread is blocked between).
import QtQuick
AppWindow {
    id: root
    width: 1600; height: 1000
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    function log(m) { console.warn("[test] " + m) }
    property real started: 0
    property string what: ""
    FrameAnimation {
        running: true
        onTriggered: if (root.started) { root.log(root.what + ": " + (Date.now() - root.started) + " ms to the next frame"); root.started = 0 }
    }
    property var stops: [["Browse", () => root.goBrowse()], ["Home", () => root.goHome()],
                         ["Seasonal", () => root.goSeasonal("season")], ["Home again", () => root.goHome()],
                         ["Library", () => root.goTo("library", "LibraryPage.qml")], ["Continue", () => root.goContinue()],
                         ["Profile", () => root.goTo("profile", "ProfilePage.qml")], ["Settings", () => root.goSettings()],
                         ["Home, third time", () => root.goHome()]]
    property int i: 0
    Timer {
        interval: 4000; running: true; repeat: true
        onTriggered: {
            if (root.i >= root.stops.length) { Qt.quit(); return }
            root.what = root.stops[root.i][0]
            root.started = Date.now()
            root.stops[root.i][1]()
            root.i++
        }
    }
}
