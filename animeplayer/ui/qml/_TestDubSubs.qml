// A dub with English subtitles: what the player gets and shows.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    property var found: null
    function log(m) { console.warn("[test] " + m) }
    Connections {
        target: backend
        function onSearchFinished(results) { if (!root.found && results.length) root.found = results[0] }
        function onStreamReady(url, referer, sub) { log("streamReady sub=" + sub) }
        function onDubEnglishReady(url) { log("dubEnglishReady " + url) }
    }
    Component.onCompleted: { backend.setAutoFullscreenEnabled(false); backend.search(testMode || "Dorohedoro") }
    Timer {
        interval: 5000; running: true; repeat: true
        onTriggered: {
            root.step++
            let p = root.pageStack.currentItem
            if (root.step === 1) root.goTo("browse", "DetailPage.qml", { anime: root.found })
            if (root.step === 2) { p.dub = true; p.playEpisode(1, 300) }
            if (root.step >= 5 && root.step <= 8) {
                let v = root.findVideo(p)
                log("t=" + Math.round(v.position) + " subtitle on screen: " + JSON.stringify(v.currentSubtitleText()))
            }
            if (root.step === 9) Qt.quit()
        }
    }
    function findVideo(item) {
        if (item.hasOwnProperty("currentSubtitleText") ) return item
        for (let i = 0; i < item.children.length; i++) { let f = findVideo(item.children[i]); if (f) return f }
        return null
    }
}
