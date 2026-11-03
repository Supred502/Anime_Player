// The player's toolbars and the speed menu, for a look. Screenshots are
// taken from outside (spectacle): grabbing the window stalls while mpv draws.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    property var found: null
    function log(m) { console.warn("[test] " + m) }
    function find(item, name) {
        if (!item) return null
        if (item.objectName === name) return item
        for (let i = 0; i < item.children.length; i++) {
            let hit = find(item.children[i], name)
            if (hit) return hit
        }
        return null
    }
    Connections {
        target: backend
        function onSearchFinished(results) { if (!root.found && results.length) root.found = results[0] }
    }
    Component.onCompleted: { backend.setAutoFullscreenEnabled(false); backend.search("Frieren") }
    Timer {
        interval: 6000; running: true; repeat: true
        onTriggered: {
            root.step++
            let p = root.pageStack.currentItem
            if (root.step === 1) root.goTo("browse", "DetailPage.qml", { anime: root.found })
            if (root.step === 2) p.playEpisode(1, 60)
            if (root.step === 4) { p.controlsVisible = true; log("shot: bar") }
            if (root.step === 5) {
                let b = find(p, "speedButton")
                let at = b.mapToItem(null, b.width / 2, b.height / 2)
                windowChrome.click(root, at.x, at.y, false)
                log("shot: menu")
            }
            if (root.step === 7) Qt.quit()
        }
    }
    function video_pause(p) { let v = find(p, "video"); if (v && !v.paused) v.togglePause() }
}
