// Show page: resume button, favourites, tags, the readable header; the
// rounded cards on Home. Run against a throwaway database.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    property var found: null
    function log(m) { console.warn("[test] " + m) }
    function shot(n) { windowChrome.saveScreenshot(root, testShots + "/" + n + ".png") }
    Connections {
        target: backend
        function onSearchFinished(results) { if (!root.found && results.length) root.found = results[0] }
    }
    Component.onCompleted: backend.search("One Piece")
    Timer {
        interval: 5000; running: true; repeat: true
        onTriggered: {
            root.step++
            let p = root.pageStack.currentItem
            if (root.step === 1) shot("home")
            if (root.step === 2) root.goTo("browse", "DetailPage.qml", { anime: root.found })
            if (root.step === 4) {
                log("resume: " + p.resumeEpisode + " at " + p.resumeAt + " local=" + JSON.stringify(p.localProgress))
                log("tags: " + p.tags.length + " first " + JSON.stringify(p.tags.slice(0, 3).map((t) => t.name + ":" + t.rank + (t.spoiler ? "!" : ""))))
                p.toggleFavorite(2)
            }
            if (root.step === 5) {
                log("favourites: " + JSON.stringify(p.favorites) + " isFav(2)=" + p.isFavorite(2))
                shot("detail")
                p.openEpisodeMenu(0, 2)
            }
            if (root.step === 6) { shot("menu"); Qt.quit() }
        }
    }
}
