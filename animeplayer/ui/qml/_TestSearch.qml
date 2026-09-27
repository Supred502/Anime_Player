// Search history and "did you mean": a misspelt search, the suggestion,
// the history dropdown, and removing an entry from it.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    function log(m) { console.warn("[test] " + m) }
    Connections {
        target: backend
        function onSearchFinished(list) { log("searchFinished " + list.length) }
        function onSearchFailed(message) { log("searchFailed " + message) }
        function onSearchSuggestion(q, t) { log("suggestion for " + q + ": " + t) }
    }
    function field(p) { return p.header.children[0].children[0] }
    Component.onCompleted: {
        backend.clearSearchHistory()
        backend.addSearchHistory("Dorohedoro")
        backend.addSearchHistory("One Piece")
    }
    Timer {
        interval: 4000; running: true; repeat: true
        onTriggered: {
            root.step++
            let p = root.pageStack.currentItem
            if (root.step === 1) root.goBrowse()
            if (root.step === 2) { p.setQuery("freiren"); p.submitSearch() }
            if (root.step === 5) {
                log("results=" + p.results.length + " suggestion=" + p.suggestion)
                windowChrome.saveScreenshot(root, testShots + "/1-did-you-mean.png")
            }
            if (root.step === 6) {
                p.setQuery("")
                root.field(p).forceActiveFocus()
                p.showHistory()
                log("history shown: " + JSON.stringify(p.historyShown))
            }
            if (root.step === 7) {
                windowChrome.saveScreenshot(root, testShots + "/2-history.png")
                p.forgetSearch("One Piece")
                log("after removing One Piece: " + JSON.stringify(backend.searchHistory()))
            }
            if (root.step === 8) {
                p.suggestion = "Frieren: Beyond Journey's End"; p.suggestionFor = "freiren"
                p.acceptSuggestion()
            }
            if (root.step === 10) {
                log("after accepting: results=" + p.results.length + " first=" + (p.results[0] || {}).title
                    + " history=" + JSON.stringify(backend.searchHistory()))
                Qt.quit()
            }
        }
    }
}
