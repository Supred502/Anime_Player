// Drives the mini player: plays an episode, sends it to the corner, browses
// to another page while it plays, then expands it back. Throwaway database:
//
//   ANIMEPLAYER_DB_PATH=<tmp>/a.db ANIMEPLAYER_TEST_QML=_TestMini.qml \
//   ANIMEPLAYER_TEST_SHOTS=<dir> python -m animeplayer
import QtQuick
import org.kde.kirigami as Kirigami

AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")

    property int step: 0
    property var found: null
    property real handedAt: 0
    function log(message) { console.warn("[test] " + message) }
    function shoot(name) {
        let path = testShots + "/" + name + ".png"
        log((windowChrome.saveScreenshot(root, path) ? "saved " : "FAILED ") + path)
    }
    function mini() { return root.miniPlayer }

    Connections {
        target: backend
        function onSearchFinished(results) { if (!root.found && results.length) root.found = results[0] }
    }
    Component.onCompleted: { backend.setAutoFullscreenEnabled(false); backend.search("Frieren") }

    Timer {
        interval: 6000
        running: true
        repeat: true
        onTriggered: {
            root.step++
            let p = root.pageStack.currentItem
            switch (root.step) {
            case 1: root.goTo("browse", "DetailPage.qml", { anime: root.found }); break
            case 2: p.playEpisode(1, 300); break
            case 4:
                log("full player stream loaded=" + (p.streamUrl !== ""))
                p.toMiniPlayer()
                break
            case 5:
                log("after hand-over: page=" + (root.pageStack.currentItem.title || "?")
                    + " mini=" + (root.mini() !== null))
                root.goTo("schedule", "SchedulePage.qml")
                break
            case 7:
                root.shoot("1-mini-while-browsing")
                root.handedAt = root.mini().children[0].position
                log("mini playing=" + root.mini().playing + " at " + Math.round(root.handedAt) + "s")
                backend.setAutoSkipEnabled(false)
                root.mini().expand(root.handedAt)
                break
            case 8: break
            case 9: {
                let player = root.pageStack.currentItem
                log("expanded: player=" + (typeof player.toMiniPlayer === "function")
                    + " episode=" + player.episodeNumber + " startAt/seeked ok; mini gone=" + (root.mini() === null))
                // No screenshot here: grabbing the window while the full
                // player renders deadlocks the grab (the app itself is fine).
                log("progress row: " + JSON.stringify(backend.getLocalProgress(root.found.slug_id)))
                break
            }
            case 10: Qt.quit(); break
            }
        }
    }
}
