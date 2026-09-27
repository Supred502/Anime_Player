// The home page's spotlight: what it picked and why, then opens the first
// pick through its Watch Now button's handler.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    function log(m) { console.warn("[test] " + m) }
    Timer {
        interval: 9000; running: true
        onTriggered: {
            let home = root.pageStack.currentItem
            log("spotlight: " + home.spotlight.map((s) => s.reason + ": " + s.title).join(" | "))
            windowChrome.saveScreenshot(root, testShots + "/home.png")
            home.openContinueEntry(home.spotlight[0])
            next.start()
        }
    }
    Timer {
        id: next; interval: 6000
        onTriggered: { log("opened: " + root.pageStack.currentItem.title); Qt.quit() }
    }
}
