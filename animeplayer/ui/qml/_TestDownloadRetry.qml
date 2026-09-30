// Downloads that died mid-queue (the database says so at start: "failed,
// Interrupted"), then one click each on the show's page. Seed the throwaway
// database first with rows left "queued"/"downloading".
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    readonly property var eps: [[9317, 1], [9318, 2], [9319, 3]]
    function log(m) { console.warn("[test] " + m) }
    function states(p) {
        return root.eps.map((e) => { let d = p.downloadFor(e[0]); return e[1] + ":" + (d ? d.status : "none") }).join(" ")
    }
    Timer {
        interval: 5000; running: true; repeat: true
        onTriggered: {
            root.step++
            let p = root.pageStack.currentItem
            switch (root.step) {
            case 1:
                root.pageStack.push(Qt.resolvedUrl("DetailPage.qml"), { anime: {
                    slug_id: "that-time-i-got-reincarnated-as-a-slime-486", numeric_id: "486",
                    title: "That Time I Got Reincarnated as a Slime", poster_url: "", kind: "", rating: "" } })
                break
            case 2:
                log("before: " + root.states(p))
                for (let e of root.eps) p.toggleDownload(e[0], e[1])
                log("right after one click each: " + root.states(p))
                break
            case 3:
                log("5s later: " + root.states(p) + " queue=" + backend.downloadQueue().map((d) => d.episode_number + ":" + d.status).join(","))
                for (let e of root.eps) backend.cancelDownload(e[0], false)
                break
            case 4: Qt.quit(); break
            }
        }
    }
}
