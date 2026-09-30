// Browse's filter panel: closed the first time, then as it was left.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    function log(m) { console.warn("[test] " + m) }
    Timer {
        interval: 2500; running: true; repeat: true
        onTriggered: {
            root.step++
            let p = root.pageStack.currentItem
            switch (root.step) {
            case 1: root.goBrowse(); break
            case 2: log("first open: panel open=" + p.filtersOpen); p.filtersOpen = true; root.goHome(); break
            case 3: root.goBrowse(); break
            case 4: log("after opening it: panel open=" + p.filtersOpen); p.filtersOpen = false; root.goHome(); break
            case 5: root.goTo("browse", "BrowsePage.qml", { startGenre: "Action" }); break
            case 6: log("opened at a genre: panel open=" + p.filtersOpen + ", filters=" + p.filterCount); Qt.quit(); break
            }
        }
    }
}
