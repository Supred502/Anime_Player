// Searching Browse: everywhere until a filter is touched, within them after.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    function log(m) { console.warn("[test] " + m) }
    function first(p) { return p.results.slice(0, 3).map((r) => r.title).join(" | ") }
    Timer {
        interval: 8000; running: true; repeat: true
        onTriggered: {
            root.step++
            let p = root.pageStack.currentItem
            switch (root.step) {
            case 1: root.goBrowse(); break
            case 2: log("opened on '" + p.presetLabel + "' filtered=" + p.filtered + " touched=" + p.filtersTouched)
                    p.setQuery("That Time I Got Reincarnated as a Slime"); p.submitSearch(); break
            case 3: log("untouched search: " + p.results.length + " results: " + root.first(p) + " note=" + p.searchingWithinFilters)
                    p.formatStates = { "TV": 1 }; p.reload(); break
            case 4: log("after touching a filter: " + p.results.length + " results: " + root.first(p) + " note=" + p.searchingWithinFilters)
                    windowChrome.saveScreenshot(root, testShots + "/within.png"); break
            case 5: Qt.quit(); break
            }
        }
    }
}
