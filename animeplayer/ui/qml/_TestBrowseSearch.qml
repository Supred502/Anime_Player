// Browse must not come back stuck on an old search: search, touch a filter
// (which saves the page's state), leave, come back.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    function log(m) { console.warn("[test] " + m) }
    function field(p) { return p.browseState().keyword + "' loading=" + p.loading + " err='" + p.errorMessage }
    Timer {
        interval: 9000; running: true; repeat: true
        onTriggered: {
            root.step++
            let p = root.pageStack.currentItem
            switch (root.step) {
            case 1: root.goBrowse(); break
            case 2:
                p.setQuery("That Time I Got Reincarnated as a Slime")
                p.submitSearch()
                break
            case 3:
                log("searched: box='" + root.field(p) + "' results=" + p.results.length + " first=" + (p.results[0] ? p.results[0].title : "-"))
                p.formatStates = { "TV": 1 }
                p.reload()          // a filter change: this is what used to save the search
                break
            case 4:
                log("saved state keyword='" + backend.browseState().keyword + "'")
                root.goHome()
                break
            case 5: root.goBrowse(); break
            case 6:
                log("back on Browse: box='" + root.field(p) + "' results=" + p.results.length + " first=" + (p.results[0] ? p.results[0].title : "-") + " TV filter kept=" + (p.formatStates["TV"] === 1))
                p.setQuery("slime"); p.submitSearch()
                break
            case 7:
                log("searched again: first=" + (p.results[0] ? p.results[0].title : "-"))
                p.setQuery("")
                p.submitSearch()       // what emptying the box does now (onTextEdited)
                break
            case 8:
                log("box emptied: results=" + p.results.length + " first=" + (p.results[0] ? p.results[0].title : "-") + " lastSearch='" + p.lastSearch + "'")
                Qt.quit()
                break
            }
        }
    }
}
