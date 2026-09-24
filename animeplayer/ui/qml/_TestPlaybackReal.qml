// Live end-to-end driver: walks the REAL pages through the REAL navigation
// path (Browse -> Detail -> Player) against the live source, the way a user
// would. Not a unit test -- the lifecycle bugs in this app only show up on
// the actual pageStack push path. Run with:
//   ANIMEPLAYER_TEST_QML=_TestPlaybackReal.qml python -m animeplayer
import QtQuick
import org.kde.kirigami as Kirigami

AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("BrowsePage.qml")

    property string query: "Dorohedoro"
    // ANIMEPLAYER_TEST_PAUSE lets a screenshot land mid-flow.
    property string pause: testPause
    property var detailPage: null
    property bool typed: false

    // console.warn, not console.log: the message handler in __main__.py only
    // receives what Qt's logging rules let through, and debug-level QML output
    // is filtered out by default -- a log() built on console.log prints
    // nothing at all while warnings from the same file appear fine.
    // Timestamped: the interesting question about this flow is not whether
    // each step happens but how long the user waits for it.
    property double t0: 0
    function log(msg) {
        if (root.t0 === 0) root.t0 = Date.now()
        console.warn("[E2E] +" + (Date.now() - root.t0) + "ms " + msg)
    }

    Connections {
        target: backend
        // browseFinished, not searchFinished: BrowsePage runs every lookup --
        // keyword included -- through the filter path now, and a driver still
        // listening on the old signal sat waiting forever.
        function onBrowseFinished(payload) {
            // The page loads its default catalog on construction, so ignore
            // everything until our own query has actually been typed --
            // otherwise the driver opens whatever happened to be top of the
            // default listing.
            if (!root.typed) return
            let results = payload.results
            root.log("search -> " + results.length + " results; first=" +
                     (results.length ? results[0].title + " (" + results[0].slug_id + ")" : "NONE"))
            if (!results.length) return
            searchDone.restart()
        }
        function onBrowseFailed(message) { root.log("SEARCH FAILED: " + message) }
        function onEpisodesFinished(episodes) {
            root.log("episodes -> " + episodes.length)
            if (episodes.length) episodesDone.restart()
        }
        function onEpisodesFailed(message) { root.log("EPISODES FAILED: " + message) }
        function onStreamReady(url, referer, sub) {
            root.log("streamReady url=" + url.substring(0, 60) + "... referer=" + referer +
                     " sub=" + (sub ? "yes" : "NONE"))
        }
        function onStreamFailed(message) { root.log("STREAM FAILED: " + message) }
        function onSkipTimesReady(times) {
            root.log("skipTimes op=" + JSON.stringify(times.op) + " ed=" + JSON.stringify(times.ed))
        }
        function onStreamQualitiesAvailable(q) {
            root.log("qualities -> " + JSON.stringify(q))
        }
    }

    // Kick off the search through the real page's own field, not by calling
    // backend.search() directly, so the browse page's own wiring is covered.
    Timer {
        running: true; interval: 1500
        onTriggered: {
            let page = root.pageStack.currentItem
            root.log("typing into BrowsePage")
            // The page opens on a ranked preset (Top Airing), and presets are
            // real filters now -- searching a finished show underneath one
            // correctly returns nothing. Clear them first, which is what a
            // user typing a title means.
            page.clearFilters()
            root.typed = true
            page.setQuery(root.query)
            page.load(1)
        }
    }

    Timer {
        id: searchDone; interval: Number(root.pause) || 1200
        onTriggered: {
            let page = root.pageStack.currentItem
            root.log("clicking first search result")
            page.openResult(0)
        }
    }

    // Holds the auto-hiding controls open and parks playback inside the
    // outro window, so a screenshot can show the real control bar and the
    // Skip Outro button rather than a bare video frame.
    Timer {
        running: true; interval: 25000; repeat: false
        onTriggered: {
            let page = root.pageStack.currentItem
            if (page && page.hasOwnProperty("controlsVisible")) {
                page.controlsVisible = true
                page.seekRelative(1100)
                root.log("parked in outro, controls pinned")
            }
        }
    }
    // ANIMEPLAYER_TEST_HIDECONTROLS forces the faded-out state on, twice a
    // second, so the hidden-controls/hidden-cursor look can be screenshotted
    // even while a real pointer is moving over the window and re-showing them.
    Timer {
        running: testHideControls !== ""; interval: 500; repeat: true
        onTriggered: {
            let page = root.pageStack.currentItem
            if (page && page.hasOwnProperty("controlsVisible")) page.controlsVisible = false
        }
    }
    Timer {
        running: testHideControls === ""; interval: 26000; repeat: true
        onTriggered: {
            let page = root.pageStack.currentItem
            if (page && page.hasOwnProperty("controlsVisible")) page.controlsVisible = true
        }
    }

    Timer {
        id: episodesDone; interval: Number(root.pause) || 1500
        onTriggered: {
            let page = root.pageStack.currentItem
            root.log("clicking episode 1")
            page.playEpisode(page.firstEpisodeNumber())
        }
    }
}
