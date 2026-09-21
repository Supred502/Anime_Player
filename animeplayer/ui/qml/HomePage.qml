import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page
    title: "Home"

    // True between asking for a random pick and the answer arriving. That
    // round trip involves an AniList page plus a source lookup, so without
    // this the button looks like it did nothing for a couple of seconds.
    property bool surprising: false

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
        }
    ]

    ListModel { id: continueModel }
    ListModel { id: watchingModel }
    ListModel { id: planningModel }

    Component.onCompleted: {
        backend.refreshContinueWatching()
        backend.refreshAnilistHomeLists()
    }

    function openAnime(entry) {
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

    Connections {
        target: backend
        function onContinueWatchingChanged(entries) {
            continueModel.clear()
            for (let i = 0; i < entries.length; i++) continueModel.append(entries[i])
        }
        function onAnilistWatchingChanged(entries) {
            watchingModel.clear()
            for (let i = 0; i < entries.length; i++) watchingModel.append(entries[i])
        }
        function onAnilistPlanningChanged(entries) {
            planningModel.clear()
            for (let i = 0; i < entries.length; i++) planningModel.append(entries[i])
        }
        function onAnilistAnimeResolved(result) {
            page.surprising = false
            page.openAnime(result)
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

    // Shared card-grid section. A plain manual layout rather than
    // Kirigami.Card -- Card's banner+contentItem composition doesn't respect
    // explicit sizing in this Kirigami version (see SearchPage.qml).
    component Section: ColumnLayout {
        id: root
        property alias model: repeater.model
        property string heading
        signal cardClicked(int index)
        // Filled in per row -- each row describes a different kind of entry,
        // so the card text comes from the section rather than from one
        // hardcoded model role.
        property var subtitleFor: (entry) => ""
        property var fractionFor: (entry) => 0

        visible: repeater.count > 0
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Heading {
            level: 2
            text: root.heading
        }

        GridLayout {
            id: sectionGrid
            Layout.fillWidth: true
            readonly property int idealCellWidth: Kirigami.Units.gridUnit * 11
            // page.availableWidth, not page.width: the page is wider than the
            // area its content actually gets (padding plus the scrollbar), and
            // measuring the page itself pushed the last column of every row
            // off the right edge. Not this layout's own width either -- that
            // is derived from these cells, so reading it here would be
            // circular, and the grid settled at one column per row.
            columns: Math.max(1, Math.floor(page.availableWidth / idealCellWidth))
            readonly property real cellWidth: (page.availableWidth - (columns - 1) * columnSpacing) / columns
            rowSpacing: Kirigami.Units.largeSpacing
            columnSpacing: Kirigami.Units.largeSpacing

            Repeater {
                id: repeater
                delegate: AnimeCard {
                    required property int index
                    required property var model

                    Layout.preferredWidth: sectionGrid.cellWidth
                    // Measured from the column width, not from this card's own
                    // width -- see AnimeCard's note on heightForWidth.
                    Layout.preferredHeight: heightForWidth(sectionGrid.cellWidth)
                    posterUrl: model.poster_url || ""
                    title: model.title
                    subtitle: root.subtitleFor(model)
                    watchedFraction: root.fractionFor(model)
                    onClicked: root.cardClicked(index)
                }
            }
        }
    }

    ColumnLayout {
        id: contentColumn
        width: page.availableWidth
        spacing: Kirigami.Units.largeSpacing * 2

        Section {
            // Set here rather than inside the Section declaration: an inline
            // component's own Layout.fillWidth doesn't reach its instances,
            // which left every row sized to the width of its heading text.
            Layout.fillWidth: true
            heading: "Continue Watching"
            model: continueModel
            subtitleFor: (entry) => "Episode " + entry.episode_number
            // The poster's resume bar needs a fraction, and an entry whose
            // duration was never recorded would otherwise divide by zero.
            fractionFor: (entry) => entry.duration_seconds > 0
                ? entry.position_seconds / entry.duration_seconds : 0
            onCardClicked: (index) => page.openAnime(continueModel.get(index))
        }

        Section {
            // Set here rather than inside the Section declaration: an inline
            // component's own Layout.fillWidth doesn't reach its instances,
            // which left every row sized to the width of its heading text.
            Layout.fillWidth: true
            heading: "Watching"
            model: watchingModel
            // "Episode 0" was what an unstarted entry used to read as, which
            // says the opposite of what it means.
            subtitleFor: (entry) => entry.progress > 0 ? "Episode " + entry.progress + " watched"
                                                       : "Not started yet"
            onCardClicked: (index) => {
                let entry = watchingModel.get(index)
                backend.openAnilistAnime(entry.anilist_id, entry.title)
            }
        }

        Section {
            // Set here rather than inside the Section declaration: an inline
            // component's own Layout.fillWidth doesn't reach its instances,
            // which left every row sized to the width of its heading text.
            Layout.fillWidth: true
            heading: "Planning to Watch"
            model: planningModel
            // Every entry in this row has progress 0 by definition, so the
            // old subtitle was a column of bare "0"s.
            subtitleFor: (entry) => "On your plan-to-watch list"
            onCardClicked: (index) => {
                let entry = planningModel.get(index)
                backend.openAnilistAnime(entry.anilist_id, entry.title)
            }
        }

        Kirigami.PlaceholderMessage {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.gridUnit * 4
            visible: continueModel.count === 0 && watchingModel.count === 0 && planningModel.count === 0
            text: "Nothing here yet"
            explanation: "Search for an anime, or log in to AniList in Settings to sync your lists"
            icon.name: "video-television"
        }
    }
}
