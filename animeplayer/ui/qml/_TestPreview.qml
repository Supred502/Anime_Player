// The hover preview, triggered the way resting the pointer does.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("SeasonalPage.qml")
    function log(m) { console.warn("[test] " + m) }
    function findCard(item) {
        if (item.hasOwnProperty("anilistId") && item.hasOwnProperty("posterUrl") && item.visible && item.title) return item
        for (let i = 0; i < item.children.length; i++) {
            let f = findCard(item.children[i]); if (f) return f
        }
        return null
    }
    Timer {
        interval: 7000; running: true
        onTriggered: {
            let card = root.findCard(root.pageStack.currentItem)
            root.showPreview(card, card)
            shot.start()
        }
    }
    Timer {
        id: shot; interval: 3000
        onTriggered: {
            log("preview: " + JSON.stringify(root.previewInfo).slice(0, 200))
            windowChrome.saveScreenshot(root, testShots + "/preview.png")
            Qt.quit()
        }
    }
}
