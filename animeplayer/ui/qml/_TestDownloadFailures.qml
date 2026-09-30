// A whole queue failing (run with the network cut off): the retries say so,
// the line stops after two failures in a row, "Retry all" starts them again.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int tick: 0
    function log(m) { console.warn("[test] " + m) }
    function queue() {
        return backend.allDownloads().sort((a, b) => a.episode_number - b.episode_number)
            .map((d) => d.episode_number + ":" + d.status + (d.message ? "(" + d.message + ")" : "")).join("  ")
    }
    Component.onCompleted: {
        let specs = []
        for (let n = 1; n <= 5; n++)
            specs.push({ episode_id: 9316 + n, dub: false, slug_id: "that-time-i-got-reincarnated-as-a-slime-486",
                         numeric_id: "486", title: "That Time I Got Reincarnated as a Slime", poster_url: "",
                         episode_number: n })
        backend.downloadEpisodes(specs)
    }
    Connections { target: backend; function onDownloadFailed(m) { root.log("NOTICE: " + m) } }
    Timer {
        interval: 1000; running: true; repeat: true
        onTriggered: {
            root.tick++
            if (root.tick === 3 || root.tick === 8 || root.tick === 40) root.log("t=" + root.tick + "s  " + root.queue())
            if (root.tick === 41) {
                root.goTo("library", "LibraryPage.qml")
            }
            if (root.tick === 43) {
                root.pageStack.currentItem.showTab("downloads")
            }
            if (root.tick === 45) {
                windowChrome.saveScreenshot(root, testShots + "/downloads-failed.png")
                root.log("retry all -> " + backend.retryFailedDownloads())
            }
            if (root.tick === 46) root.log("after retry all: " + root.queue())
            if (root.tick === 47) {
                for (let d of backend.allDownloads()) backend.cancelDownload(d.episode_id, d.dub)
                Qt.quit()
            }
        }
    }
}
