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

AppWindow {
    id: root
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
            // A real out-of-order case: the user's list has the previous
            // cour as Dropped, so opening episode 1 here should prompt.
            if (root.mode === "warn") {
                if (root.step === 1) {
                    root.pageStack.push(Qt.resolvedUrl("DetailPage.qml"), {
                        anime: {
                            slug_id: "mushoku-tensei-jobless-reincarnation-season-2-449",
                            numeric_id: "449",
                            title: "Mushoku Tensei: Jobless Reincarnation Season 2",
                            poster_url: "", kind: "TV", rating: ""
                        }
                    })
                    log("opened DetailPage")
                    return
                }
                let detail = root.pageStack.get(root.pageStack.depth - 1)
                if (root.step === 2) {
                    log("unwatched=" + JSON.stringify(
                        detail.unwatchedPrequels.map((e) => e.title + " [" + e.statusLabel + "]")))
                    // Exactly what clicking episode 1 does.
                    detail.requestEpisode(1)
                    log("requested episode 1")
                }
                return
            }
            // Drives the real Settings controls: switch scheme and accent
            // and confirm the whole window follows, not just that page.
            if (root.mode === "theme") {
                if (root.step === 1) {
                    root.pageStack.replace(Qt.resolvedUrl("SettingsPage.qml"))
                    log("opened Settings, theme=" + JSON.stringify(backend.theme))
                    return
                }
                if (root.step === 2) {
                    backend.setThemeAccent("purple")
                    log("switched accent -> " + JSON.stringify(backend.theme))
                    return
                }
                if (root.step === 3) {
                    root.pageStack.replace(Qt.resolvedUrl("HomePage.qml"))
                    log("back to Home under the new theme")
                    return
                }
                if (root.step === 5) {
                    backend.setThemeAccent("blue")
                    log("restored blue")
                }
                return
            }
            if (root.mode === "detail" || root.mode === "detail2") {
                if (root.step === 1) {
                    // A real entry with real key art, opened the same way a
                    // card click opens it.
                    root.pageStack.push(Qt.resolvedUrl("DetailPage.qml"), {
                        anime: {
                            slug_id: testMode === "detail2"
                                ? "rezero-starting-life-in-another-world-season-2-858"
                                : "attack-on-titan-season-2-98",
                            numeric_id: testMode === "detail2" ? "858" : "98",
                            title: "Attack on Titan Season 2", poster_url: "https://cdn.noitatnemucod.net/thumbnail/300x400/100/bcd84731a3eda4f4a306250769675065.jpg", kind: "TV", rating: ""
                        }
                    })
                    log("opened DetailPage")
                    return
                }
                // Only the page's declared properties -- a plain `id:` inside
                // DetailPage (episodesModel) is file-scoped and reads back as
                // undefined from out here.
                let detail = root.pageStack.get(root.pageStack.depth - 1)
                if (root.step === 2) {
                    log("loading=" + detail.loading + " pages=" + detail.pageCount
                        + " rowLength=" + detail.rowLengthFor(13) + "/" + detail.rowLengthFor(20)
                        + "/" + detail.rowLengthFor(23) + "/" + detail.rowLengthFor(24)
                        + " banner=" + (detail.bannerUrl !== "")
                        + " facts=" + JSON.stringify(detail.headerFacts().map((f) => f.text)))
                    return
                }
                if (root.step === 3) {
                    log("order=" + detail.watchOrder.length
                        + " unwatched=" + JSON.stringify(detail.unwatchedPrequels.map((e) => e.title))
                        + " related=" + detail.related.length
                        + " recs=" + detail.recommendations.length
                        + " reviews=" + detail.reviews.length)
                }
                // Scroll down so a screenshot catches the sections below the
                // episode grid.
                detail.flickable.contentY = Math.min(
                    detail.flickable.contentHeight - detail.flickable.height,
                    detail.flickable.contentY + detail.flickable.height * 0.8)
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
                    // Tri-state chips now, not single-value combos: 1 is
                    // include, 2 is exclude (see BrowsePage.tristate).
                    browse.formatStates = { "MOVIE": 1 }
                    browse.countryStates = { "CN": 1 }
                    browse.filterSort = "SCORE_DESC"
                    browse.filterMinScore = 70
                    browse.genreStates = { "Action": 1 }
                    browse.tagStates = { "Male Protagonist": 2 }
                    browse.reload()
                    log("applied filters: movie / score / China / >=70 / +Action / -Male Protagonist")
                }
                return
            }
            if (root.step === 3) {
                log("after " + (root.mode === "browse" ? "scroll" : "filter")
                    + ": " + browse.results.length + " results, filters=" + browse.filterCount
                    + (browse.results.length > 0 ? ", first=" + browse.results[0].title : "")
                    + (browse.errorMessage !== "" ? " ERROR=" + browse.errorMessage : ""))
            }
        }
    }
}
