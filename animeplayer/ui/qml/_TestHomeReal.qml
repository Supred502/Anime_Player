// Live driver for the home page and the browse page, against the real
// source. Run with:
//
//   ANIMEPLAYER_TEST_QML=_TestHomeReal.qml .venv/bin/python -m animeplayer
//
// ANIMEPLAYER_TEST_MODE picks what it does:
//   home    (default) waits for the rows, then scrolls the page in steps so a
//           screenshot can catch the shelves below the hero
//   browse  opens BrowsePage and reports what came back
//   filter  opens BrowsePage and applies a filter through the real controls
//
// Scrolling rather than just asserting the models are populated: the bugs
// this page is prone to are layout ones (a shelf collapsed to zero height, a
// row sized to its heading), and a populated model says nothing about those.
import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root
    title: "Anime Player"
    width: 1280
    height: 800
    pageStack.columnView.columnResizeMode: Kirigami.ColumnView.SingleColumn
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")

    readonly property string mode: testMode === "" ? "home" : testMode
    property int step: 0

    // console.warn, not console.log: Qt's logging rules drop QML debug-level
    // output even with the message handler installed in __main__.py.
    function log(message) { console.warn("[test] " + message) }

    function homePage() { return pageStack.get(pageStack.depth - 1) }

    function reportRows() {
        let page = homePage()
        let rows = page.sourceRows
        for (let i = 0; i < rows.length; i++) {
            let cards = page.rowData[rows[i].key] || []
            log(rows[i].label + ": " + cards.length + " ("
                + (page.rowState[rows[i].key] || "?") + ")"
                + (cards.length > 0 ? " first=" + cards[0].title : ""))
        }
        log("spotlight: " + page.spotlight.length
            + (page.spotlight.length > 0 ? " first=" + page.spotlight[0].title : ""))
    }

    Timer {
        interval: 4000
        running: true
        repeat: true
        onTriggered: {
            root.step++
            if (root.mode === "home") {
                if (root.step === 1) { root.reportRows(); return }
                let flick = root.homePage().flickable
                flick.contentY = Math.min(flick.contentHeight - flick.height,
                                          flick.contentY + flick.height * 0.85)
                log("scrolled to " + Math.round(flick.contentY) + "/"
                    + Math.round(flick.contentHeight))
                return
            }
            if (root.mode === "detail") {
                if (root.step === 1) {
                    // A real entry with real key art, opened the same way a
                    // card click opens it.
                    root.pageStack.push(Qt.resolvedUrl("DetailPage.qml"), {
                        anime: {
                            slug_id: "attack-on-titan-240", numeric_id: "240",
                            title: "Attack on Titan", poster_url: "https://cdn.noitatnemucod.net/thumbnail/300x400/100/bcd84731a3eda4f4a306250769675065.jpg", kind: "TV", rating: ""
                        }
                    })
                    log("opened DetailPage")
                    return
                }
                // Only the page's declared properties -- a plain `id:` inside
                // DetailPage (episodesModel) is file-scoped and reads back as
                // undefined from out here.
                let detail = root.pageStack.get(root.pageStack.depth - 1)
                log("loading=" + detail.loading + " pages=" + detail.pageCount
                    + " banner=" + (detail.bannerUrl !== "")
                    + " facts=" + JSON.stringify(detail.headerFacts().map((f) => f.text)))
                return
            }
            if (root.step === 1) {
                root.pageStack.push(Qt.resolvedUrl("BrowsePage.qml"),
                                    { startCategory: "most-popular", startLabel: "Most Popular" })
                log("opened BrowsePage")
                return
            }
            let browse = root.pageStack.get(root.pageStack.depth - 1)
            if (root.step === 2) {
                log("results: " + browse.results.length + " hasMore=" + browse.hasMore
                    + " genres=" + browse.genres.length
                    + (browse.results.length > 0 ? " first=" + browse.results[0].title : "")
                    + (browse.errorMessage !== "" ? " ERROR=" + browse.errorMessage : ""))
                if (root.mode === "browse") {
                    // Infinite scroll: jump near the bottom and see page 2 land.
                    browse.flickable.contentY = browse.flickable.contentHeight
                    log("scrolled to bottom")
                } else {
                    browse.filtersOpen = true
                    browse.filterType = "movie"
                    browse.filterSort = "avg_score"
                    browse.toggleGenre("romance")
                    log("applied filters: movie / score / romance")
                }
                return
            }
            if (root.step === 3) {
                log("after " + (root.mode === "browse" ? "scroll" : "filter")
                    + ": " + browse.results.length + " results, filtered=" + browse.filtered
                    + (browse.results.length > 0 ? ", first=" + browse.results[0].title : "")
                    + (browse.errorMessage !== "" ? " ERROR=" + browse.errorMessage : ""))
            }
        }
    }
}
