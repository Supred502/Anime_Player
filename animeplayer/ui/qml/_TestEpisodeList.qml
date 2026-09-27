// A show's page in list view, with AniList's episode titles and thumbnails.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property var found: null
    function log(m) { console.warn("[test] " + m) }
    Connections {
        target: backend
        function onSearchFinished(results) { if (!root.found && results.length) root.found = results[0] }
    }
    Component.onCompleted: backend.search(testMode || "Frieren")
    Timer {
        interval: 4000; running: true
        onTriggered: { root.goTo("browse", "DetailPage.qml", { anime: root.found }); next.start() }
    }
    Timer {
        id: next; interval: 8000
        onTriggered: {
            let p = root.pageStack.currentItem
            p.listView = true
            log("art for " + Object.keys(p.episodeArt).length + " episodes")
            p.flickable.contentY = 380
            shot.start()
        }
    }
    Timer {
        id: shot; interval: 2500
        onTriggered: { windowChrome.saveScreenshot(root, testShots + "/list.png"); Qt.quit() }
    }
}
