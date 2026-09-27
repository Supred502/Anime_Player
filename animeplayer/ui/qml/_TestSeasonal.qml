// The Seasonal page: this season, then a step back.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("SeasonalPage.qml")
    function log(m) { console.warn("[test] " + m) }
    Timer {
        interval: 7000; running: true
        onTriggered: {
            let p = root.pageStack.currentItem
            log(p.title + ": " + p.cards.length + " shows; TV " + p.shown(p.groups[0]).length)
            windowChrome.saveScreenshot(root, testShots + "/seasonal.png")
            p.step(-1)
            back.start()
        }
    }
    Timer {
        id: back; interval: 6000
        onTriggered: {
            let p = root.pageStack.currentItem
            log(p.title + ": " + p.cards.length + " shows")
            Qt.quit()
        }
    }
}
