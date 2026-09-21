// Live driver for the discovery paths, which a normal launch can only reach
// through several clicks. Run with:
//   ANIMEPLAYER_TEST_QML=_TestDiscoverReal.qml ANIMEPLAYER_TEST_MODE=surprise python -m animeplayer
// ANIMEPLAYER_TEST_MODE: "recommend" (default), "surprise", or "clickfirst"
// (recommend, then open the first card -- the path that resolves an AniList
// entry the user has never watched down to something playable).
import QtQuick
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root
    title: "Anime Player"
    width: 1280
    height: 800
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    pageStack.columnView.columnResizeMode: Kirigami.ColumnView.SingleColumn

    // console.warn, not console.log: the message handler in __main__.py only
    // receives what Qt's logging rules let through, and debug-level QML output
    // is filtered out by default -- a log() built on console.log prints
    // nothing at all while warnings from the same file appear fine.
    function log(msg) { console.warn("[E2E] " + msg) }

    Connections {
        target: backend
        function onAnilistAnimeResolved(result) { root.log("resolved -> " + result.title + " (" + result.slug_id + ")") }
        function onDiscoverFailed(message) { root.log("DISCOVER FAILED: " + message) }
        function onAnilistAnimeResolveErrored(message) { root.log("ERRORED: " + message) }
        function onFilterSearchFinished(payload) {
            root.log("results -> " + payload.results.length)
            if (testMode === "clickfirst") clickFirst.restart()
        }
        function onRecommendationsFailed(message) { root.log("RECS FAILED: " + message) }
        function onEpisodesFinished(episodes) { root.log("episodes -> " + episodes.length) }
    }

    // Opens the first recommendation once they land, in "clickfirst" mode.
    Timer {
        id: clickFirst
        interval: 500
        onTriggered: {
            root.log("opening first card")
            root.pageStack.currentItem.openResult(0)
        }
    }

    Timer {
        interval: 1200
        running: true
        onTriggered: {
            if (testMode === "surprise") backend.surpriseMe()
            // Through the real toolbar action, not by calling the backend:
            // the action navigates first and then drives the page it landed
            // on, which is the part that can silently do nothing.
            else root.pageStack.currentItem.actions[1].trigger()
        }
    }
}
