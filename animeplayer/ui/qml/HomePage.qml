// The home page: a featured hero, then the user's own in-progress rows, then
// the streaming source's own rankings as horizontal shelves.
//
// Every row here is a plain JS array rather than a ListModel. A ListModel
// fixes its role set from the first row appended, and these rows are fed by
// three different producers (the local watch history, AniList, the source's
// catalog) -- the mismatch is exactly what used to render the literal word
// "undefined" across the app. An array of the objects the backend already
// emits has no roles to get out of step.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page

    // Paints this page in the app's colour scheme -- see AppTheming.qml
    // for why this is per-page rather than set once on the window.
    AppTheming {}
    title: "Home"
    // The hero runs edge to edge; the padding that would normally inset it
    // is applied per-row instead (see contentColumn).
    topPadding: 0
    leftPadding: 0
    rightPadding: 0

    // True between asking for a random pick and the answer arriving. That
    // round trip involves a catalog page plus a source lookup, so without
    // this the button looks like it did nothing for a couple of seconds.
    property bool surprising: false

    property var spotlight: []
    property var continueWatching: []
    property var watching: []
    property var planning: []

    // key -> card array, and key -> "loading"/"ready"/"failed". Reassigned
    // rather than mutated in place: QML only notifies on assignment for
    // `var` properties, and mutating these left the shelves blank.
    property var rowData: ({})
    property var rowState: ({})

    // Assigned once rather than left as a live binding on backend.homeRows():
    // the row list never changes, and a binding that reads `backend` gets
    // re-evaluated during teardown after the context property is gone, which
    // printed an intermittent "Cannot call method 'homeRows' of null" on quit.
    property var sourceRows: []

    actions: [
        Kirigami.Action {
            text: page.surprising ? "Finding one..." : "Surprise Me"
            icon.name: "media-playlist-shuffle-symbolic"
            enabled: !page.surprising
            tooltip: "Open a random anime you haven't watched"
            onTriggered: {
                page.surprising = true
                backend.surpriseMe()
            }
        },
        Kirigami.Action {
            text: "Recommend Me"
            icon.name: "games-highscores-symbolic"
            tooltip: "Shows picked from what you've already watched"
            onTriggered: {
                let search = applicationWindow().pageStack.replace(Qt.resolvedUrl("SearchPage.qml"))
                search.loadRecommendations()
            }
        },
        Kirigami.Action {
            text: "Browse"
            icon.name: "view-list-details-symbolic"
            tooltip: "Every catalog, with filters"
            onTriggered: applicationWindow().pageStack.replace(Qt.resolvedUrl("BrowsePage.qml"))
        }
    ]

    Component.onCompleted: {
        page.sourceRows = backend.homeRows()
        backend.refreshContinueWatching()
        backend.refreshAnilistHomeLists()
        for (let i = 0; i < page.sourceRows.length; i++) page.setRowState(page.sourceRows[i].key, "loading")
        backend.refreshHomeFeed()
    }

    function setRowState(key, state) {
        let next = Object.assign({}, page.rowState)
        next[key] = state
        page.rowState = next
    }

    function setRowData(key, cards) {
        let next = Object.assign({}, page.rowData)
        next[key] = cards
        page.rowData = next
    }

    // Everything the source itself served (hero, shelves) already carries a
    // slug, so it opens straight onto DetailPage with no lookup at all --
    // unlike an AniList card, which has to be matched to the source first.
    function openSourceEntry(entry) {
        applicationWindow().pageStack.push(
            Qt.resolvedUrl("DetailPage.qml"),
            {
                anime: {
                    slug_id: entry.slug_id,
                    numeric_id: entry.numeric_id,
                    title: entry.title,
                    poster_url: entry.poster_url || "",
                    kind: entry.kind || "",
                    rating: entry.rating || ""
                }
            }
        )
    }

    function openCatalog(key, label) {
        applicationWindow().pageStack.push(
            Qt.resolvedUrl("BrowsePage.qml"), { startCategory: key, startLabel: label }
        )
    }

    Connections {
        target: backend
        function onContinueWatchingChanged(entries) { page.continueWatching = entries }
        function onAnilistWatchingChanged(entries) { page.watching = entries }
        function onAnilistPlanningChanged(entries) { page.planning = entries }
        function onHomeSpotlightReady(entries) { page.spotlight = entries }
        function onHomeRowReady(key, cards) {
            page.setRowData(key, cards)
            page.setRowState(key, "ready")
        }
        function onHomeRowFailed(key, message) {
            page.setRowState(key, "failed")
        }
        function onAnilistAnimeResolved(result) {
            page.surprising = false
            page.openSourceEntry(result)
        }
        function onAnilistAnimeResolveFailed(title) {
            page.surprising = false
            showPassiveNotification("Couldn't find a stream for \"" + title + "\"")
        }
        function onAnilistAnimeResolveErrored(message) {
            page.surprising = false
            showPassiveNotification("Couldn't reach the streaming source: " + message)
        }
        function onDiscoverFailed(message) {
            page.surprising = false
            showPassiveNotification(message)
        }
    }

    ColumnLayout {
        id: contentColumn
        width: page.availableWidth
        spacing: Kirigami.Units.gridUnit

        SpotlightBanner {
            Layout.fillWidth: true
            model: page.spotlight
            onWatchClicked: (index) => page.openSourceEntry(page.spotlight[index])
        }

        // One inset applied to everything below the hero, rather than page
        // padding: the hero is meant to bleed to the window edges and the
        // shelves are not.
        ColumnLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.largeSpacing
            Layout.rightMargin: Kirigami.Units.largeSpacing
            Layout.bottomMargin: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.gridUnit * 1.5

            PosterRow {
                Layout.fillWidth: true
                heading: "Continue Watching"
                model: page.continueWatching
                subtitleFor: (entry) => "Episode " + entry.episode_number
                // The poster's resume bar needs a fraction, and an entry whose
                // duration was never recorded would otherwise divide by zero.
                fractionFor: (entry) => entry.duration_seconds > 0
                    ? entry.position_seconds / entry.duration_seconds : 0
                onCardClicked: (index) => page.openSourceEntry(page.continueWatching[index])
            }

            PosterRow {
                Layout.fillWidth: true
                heading: "Watching"
                model: page.watching
                // "Episode 0" was what an unstarted entry used to read as,
                // which says the opposite of what it means.
                subtitleFor: (entry) => entry.progress > 0 ? "Episode " + entry.progress + " watched"
                                                           : "Not started yet"
                onCardClicked: (index) => backend.openAnilistAnime(
                    page.watching[index].anilist_id, page.watching[index].title)
            }

            Repeater {
                model: page.sourceRows

                PosterRow {
                    required property var modelData

                    Layout.fillWidth: true
                    heading: modelData.label
                    model: page.rowData[modelData.key] || []
                    loading: page.rowState[modelData.key] === "loading"
                    // Trending and Top Airing are rankings, and the number is
                    // the whole point of them; Latest Completed is a list that
                    // happens to be in date order, where numbering it would
                    // claim an order it doesn't have.
                    ranked: modelData.key === "trending" || modelData.key === "top-airing"
                    showSeeAll: true
                    emptyHint: page.rowState[modelData.key] === "failed"
                        ? "Couldn't load this row." : ""
                    subtitleFor: (entry) => [entry.kind, entry.duration]
                        .filter((part) => !!part).join(" · ")
                    onCardClicked: (index) => page.openSourceEntry(page.rowData[modelData.key][index])
                    onSeeAllClicked: page.openCatalog(modelData.catalog, modelData.label)
                }
            }

            PosterRow {
                Layout.fillWidth: true
                heading: "Planning to Watch"
                model: page.planning
                // Every entry in this row has progress 0 by definition, so the
                // old subtitle was a column of bare "0"s.
                subtitleFor: (entry) => "On your plan-to-watch list"
                onCardClicked: (index) => backend.openAnilistAnime(
                    page.planning[index].anilist_id, page.planning[index].title)
            }
        }
    }
}
