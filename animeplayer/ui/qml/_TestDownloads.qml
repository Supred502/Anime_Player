// Real downloads: a dub and two subbed episodes, reporting every status
// change and failure until they finish.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    property var found: null
    property var episodes: []
    function log(m) { console.warn("[test] " + m) }
    Connections {
        target: backend
        function onSearchFinished(results) { if (!root.found && results.length) root.found = results[0] }
        function onEpisodesFinished(list) { root.episodes = list }
        function onDownloadFailed(message) { log("FAILED: " + message) }
    }
    Component.onCompleted: backend.search(testMode || "Dorohedoro")
    Timer {
        interval: 5000; running: true; repeat: true
        onTriggered: {
            root.step++
            let p = root.pageStack.currentItem
            if (root.step === 1) root.goTo("browse", "DetailPage.qml", { anime: root.found })
            if (root.step === 2) {
                p.dub = true
                backend.downloadEpisodes([p.episodeSpec(root.episodes[0].episode_id, 1)])
                p.dub = false
                backend.downloadEpisodes([0, 1].map((i) => p.episodeSpec(root.episodes[i].episode_id, root.episodes[i].number)))
            }
            if (root.step > 2) {
                let rows = backend.allDownloads()
                log(rows.map((r) => r.episode_number + (r.dub ? "dub" : "sub") + ":" + r.status
                             + (r.message ? "(" + r.message + ")" : "")).join("  "))
                if (rows.length > 0 && rows.every((r) => r.status === "ready" || r.status === "failed")) Qt.quit()
            }
        }
    }
}
