// Drives the Library for real: makes a tab, adds a show to it from the
// show's own page, queues three downloads, reorders them, and screenshots
// each step. Run against a throwaway database:
//
//   ANIMEPLAYER_DB_PATH=<tmp>/a.db ANIMEPLAYER_TEST_QML=_TestLibrary.qml \
//   ANIMEPLAYER_TEST_SHOTS=<dir> python -m animeplayer
import QtQuick
import org.kde.kirigami as Kirigami

AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")

    property int step: 0
    property var found: null
    property var episodes: []
    function log(message) { console.warn("[test] " + message) }
    function shoot(name) {
        let path = testShots + "/" + name + ".png"
        log((windowChrome.saveScreenshot(root, path) ? "saved " : "FAILED ") + path)
    }
    function current() { return root.pageStack.currentItem }

    Connections {
        target: backend
        function onSearchFinished(results) { if (!root.found && results.length) root.found = results[0] }
        function onEpisodesFinished(episodes) { root.episodes = episodes }
    }
    Component.onCompleted: backend.search("Frieren")

    Timer {
        interval: 5000
        running: true
        repeat: true
        onTriggered: {
            root.step++
            let p = root.current()
            switch (root.step) {
            case 1:
                root.goTo("browse", "DetailPage.qml", { anime: root.found })
                break
            case 2: {
                let id = backend.createLibraryList("Next 30 days")
                p.toggleLibrary(id)
                log("tabs for show: " + JSON.stringify(p.libraryTabs) + " button=" + (p.libraryTabs.length ? "In Library" : "Library"))
                // Episodes 1-3, queued the way the page's own buttons do it.
                backend.downloadEpisodes([0, 1, 2].map(
                    (i) => p.episodeSpec(root.episodes[i].episode_id, root.episodes[i].number)))
                root.shoot("1-detail-in-library")
                break
            }
            case 3:
                root.goTo("library", "LibraryPage.qml")
                break
            case 4:
                p.showTab("downloads")
                log("queue: " + p.queue.map((d) => d.episode_number + ":" + d.status).join(", "))
                root.shoot("2-queue")
                backend.moveDownload(p.queue[2].episode_id, false, 0)
                break
            case 5:
                log("after moving 3 to the front: " + p.queue.map((d) => d.episode_number + ":" + d.status).join(", "))
                root.shoot("3-queue-reordered")
                break
            case 6: {
                let lists = backend.libraryLists()
                p.showTab(String(lists[0].id))
                log("tab " + lists[0].name + ": " + p.cards.map((c) => c.title).join(", "))
                break
            }
            case 7:
                root.shoot("4-user-tab")
                p.showTab("planning")
                break
            case 8:
                root.shoot("5-planning")
                for (let d of backend.downloadQueue()) backend.cancelDownload(d.episode_id, d.dub)
                log("after cancelling: " + backend.downloadQueue().length + " left")
                break
            case 9: Qt.quit(); break
            }
        }
    }
}
