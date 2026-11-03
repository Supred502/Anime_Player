// How much room each horizontal row leaves above and below its first card.
import QtQuick
import QtQuick.Controls as Controls
AppWindow {
    id: root
    width: 1600; height: 1000
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    function walk(i, d) {
        if (!i || d > 40) return
        if (i.orientation === ListView.Horizontal && i.itemAtIndex && i.count > 0) {
            let c = i.itemAtIndex(0)
            let p = c.mapToItem(i, 0, 0)
            console.warn("[test] row h " + i.height + " card top " + p.y + " bottom room " + (i.height - p.y - c.height) + " left " + p.x + " vflick " + (i.contentHeight + i.topMargin + i.bottomMargin > i.height))
        }
        for (let ch of i.children) walk(ch, d + 1)
    }
    Timer { interval: 10000; running: true; onTriggered: { root.walk(root.pageStack.currentItem, 0); Qt.quit() } }
}
