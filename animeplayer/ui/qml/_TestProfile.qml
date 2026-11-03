// Grabs the Profile page's tabs to PNGs (works with the screen locked).
import QtQuick
AppWindow {
    id: root
    width: 1600; height: 1000
    pageStack.initialPage: Qt.resolvedUrl("ProfilePage.qml")
    property var tabs: ["history", "overview", "friends", "computer"]
    property int step: 0
    Timer {
        interval: 5000; running: true; repeat: true
        onTriggered: {
            let i = Math.floor(root.step / 2)
            if (i >= root.tabs.length) { Qt.quit(); return }
            if (root.step % 2 === 0) root.pageStack.currentItem.tab = root.tabs[i]
            else root.pageStack.grabToImage((r) => r.saveToFile(Qt.application.arguments[Qt.application.arguments.length - 1] + "/" + root.tabs[i] + ".png"))
            root.step++
        }
    }
}
