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
    property var genres: []
    property var continueWatching: []
    property var planning: []
    property var newEpisodes: []
    property real nowSeconds: Date.now() / 1000

    // A minute is fine grain for a countdown shown in days and hours.
    Timer {
        interval: 60000
        running: page.newEpisodes.length > 0
        repeat: true
        onTriggered: page.nowSeconds = Date.now() / 1000
    }

    function countdownText(seconds) {
        let days = Math.floor(seconds / 86400)
        let hours = Math.floor((seconds % 86400) / 3600)
        let minutes = Math.floor((seconds % 3600) / 60)
        if (days > 0) return days + "d " + hours + "h"
        if (hours > 0) return hours + "h " + minutes + "m"
        return minutes + "m"
    }
    property string becauseTitle: ""
    property var becauseCards: []

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
            onTriggered: applicationWindow().goBrowse({ startWithRecommendations: true })
        }
    ]

    Component.onCompleted: {
        page.sourceRows = backend.homeRows()
        backend.fetchAnilistGenres()
        backend.refreshContinueWatching()
        backend.refreshAnilistHomeLists()
        page.newEpisodes = backend.newEpisodes()
        backend.refreshBecauseYouWatched()
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
                    rating: entry.rating || "",
                    // Carried through so the detail page can say how far the
                    // dub is behind the sub. The source publishes both counts
                    // on the card and nothing else knows them -- AniList has
                    // no dub data at all.
                    sub_count: entry.sub_count || 0,
                    dub_count: entry.dub_count || 0
                }
            }
        )
    }

    // A merged Continue Watching row holds two kinds of entry: ones played on
    // this machine, which carry a source slug and open straight away, and
    // ones AniList says are in progress, which have to be matched to the
    // source first.
    function openContinueEntry(entry) {
        if (entry.slug_id) page.openSourceEntry(entry)
        else backend.openAnilistAnime(entry.anilist_id, entry.title)
    }

    function openCatalog(key, label) {
        applicationWindow().goBrowse({ startCategory: key, startLabel: label })
    }

    Connections {
        target: backend
        function onAnilistGenresLoaded(list) {
            // AniList has nineteen genres, so they all fit -- minus the adult
            // one, which is not a mood anyone wants offered on a home page.
            page.genres = list.filter((name) => name !== "Hentai")
        }
        function onContinueWatchingChanged(entries) { page.continueWatching = entries }
        function onAnilistPlanningChanged(entries) { page.planning = entries }
        function onNewEpisodesChanged(entries) { page.newEpisodes = entries }
        function onBecauseYouWatchedReady(title, cards) {
            page.becauseTitle = title
            page.becauseCards = cards
        }
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
            onWatchClicked: (index) => page.openContinueEntry(page.spotlight[index])
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

            // Wide cards rather than another poster shelf: this is the row
            // people come to the page for, and eight identical shelves made
            // it impossible to find at a glance.
            ColumnLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing
                visible: page.continueWatching.length > 0

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing
                    Rectangle {
                        Layout.preferredWidth: 4
                        Layout.preferredHeight: resumeHeading.implicitHeight * 0.8
                        radius: 2
                        color: Kirigami.Theme.highlightColor
                    }
                    Kirigami.Heading {
                        id: resumeHeading
                        level: 3
                        text: "Continue Watching"
                    }
                    Item { Layout.fillWidth: true }
                }

                ListView {
                    id: resumeRow
                    Layout.fillWidth: true
                    Layout.preferredHeight: Kirigami.Units.gridUnit * 7
                    orientation: ListView.Horizontal
                    spacing: Kirigami.Units.largeSpacing
                    clip: true
                    reuseItems: true
                    boundsBehavior: Flickable.StopAtBounds
                    model: page.continueWatching

                    delegate: ResumeCard {
                        required property var modelData
                        required property int index

                        width: Math.min(Kirigami.Units.gridUnit * 22,
                                        Math.max(Kirigami.Units.gridUnit * 15,
                                                 page.availableWidth / 2.4))
                        height: resumeRow.height - Kirigami.Units.smallSpacing
                        posterUrl: modelData.poster_url || ""
                        title: modelData.title
                        subtitle: "Episode " + modelData.episode_number
                        // An entry whose duration was never recorded would
                        // otherwise divide by zero.
                        watchedFraction: modelData.duration_seconds > 0
                            ? modelData.position_seconds / modelData.duration_seconds : 0
                        onClicked: page.openContinueEntry(page.continueWatching[index])
                    }
                }
            }

            // Shows being followed that have aired something not yet
            // watched. Right under Continue Watching: it's the same question
            // -- "what do I watch now" -- answered by the schedule.
            PosterRow {
                Layout.fillWidth: true
                visible: page.newEpisodes.length > 0
                heading: "New Episodes"
                model: page.newEpisodes
                subtitleFor: (entry) => entry.reason || ""
                // Counting down to the next one. Reads page.nowSeconds so the
                // badge re-evaluates as the clock below ticks.
                badgeFor: (entry) => entry.next_airing_at > page.nowSeconds
                    ? "Ep " + entry.next_episode + " in " + page.countdownText(entry.next_airing_at - page.nowSeconds)
                    : ""
                onCardClicked: (index) => page.openContinueEntry(page.newEpisodes[index])
            }

            PosterRow {
                Layout.fillWidth: true
                visible: page.becauseCards.length > 0
                heading: "Because you watched " + page.becauseTitle
                model: page.becauseCards
                subtitleFor: (entry) => [entry.kind, entry.rating ? "\u2605 " + entry.rating : ""]
                    .filter((part) => !!part).join(" · ")
                onCardClicked: (index) => backend.openAnilistAnime(
                    page.becauseCards[index].anilist_id, page.becauseCards[index].title)
            }

            // Breaks up the run of shelves, and turns the filters people
            // actually use into one click instead of five.
            ColumnLayout {
                Layout.fillWidth: true
                Layout.topMargin: Kirigami.Units.smallSpacing
                spacing: Kirigami.Units.smallSpacing
                visible: page.genres.length > 0

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing
                    Rectangle {
                        Layout.preferredWidth: 4
                        Layout.preferredHeight: genreHeading.implicitHeight * 0.8
                        radius: 2
                        color: Kirigami.Theme.highlightColor
                    }
                    Kirigami.Heading {
                        id: genreHeading
                        level: 3
                        text: "In the mood for"
                    }
                    Item { Layout.fillWidth: true }
                }

                Flow {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    Repeater {
                        model: page.genres

                        Controls.Button {
                            // The QQC2 desktop style sets Kirigami.Theme.inherit = false on its
                            // controls, which stops the app's accent reaching them -- measured
                            // live: a page themed red still drew Breeze-blue Sub/Dub buttons.
                            // Turning inheritance back on is what makes one accent value reach
                            // every control in the app. See AppTheming.qml.
                            Kirigami.Theme.inherit: true
                            id: genreChip
                            required property var modelData
                            text: modelData
                            hoverEnabled: true
                            leftPadding: Kirigami.Units.largeSpacing
                            rightPadding: Kirigami.Units.largeSpacing

                            background: Rectangle {
                                radius: height / 2
                                color: genreChip.hovered
                                    ? Qt.rgba(Kirigami.Theme.highlightColor.r,
                                              Kirigami.Theme.highlightColor.g,
                                              Kirigami.Theme.highlightColor.b, 0.2)
                                    : Kirigami.Theme.alternateBackgroundColor
                                border.width: 1
                                border.color: genreChip.hovered ? Kirigami.Theme.highlightColor
                                                                : "transparent"
                                Behavior on color { ColorAnimation { duration: 100 } }
                            }
                            contentItem: Controls.Label {
                                text: genreChip.text
                                color: Kirigami.Theme.textColor
                                horizontalAlignment: Text.AlignHCenter
                            }

                            onClicked: applicationWindow().goBrowse({ startGenre: modelData })
                        }
                    }
                }
            }

            Repeater {
                model: page.sourceRows

                PosterRow {
                    required property var modelData

                    Layout.fillWidth: true
                    heading: modelData.label
                    model: page.rowData[modelData.key] || []
                    // The first shelf is the headline one, so it gets more
                    // room; the rest are deliberately smaller.
                    cardWidth: modelData.key === "trending" ? Kirigami.Units.gridUnit * 11
                                                            : Kirigami.Units.gridUnit * 9
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
                showSeeAll: true
                onSeeAllClicked: applicationWindow().goBrowse({ startListStatus: "PLANNING" })
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
