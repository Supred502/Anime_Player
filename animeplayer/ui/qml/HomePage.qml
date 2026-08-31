import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page
    title: "Home"

    ListModel { id: continueModel }
    ListModel { id: watchingModel }
    ListModel { id: planningModel }

    Component.onCompleted: {
        backend.refreshContinueWatching()
        backend.refreshAnilistHomeLists()
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
            applicationWindow().pageStack.push(
                Qt.resolvedUrl("DetailPage.qml"),
                {
                    anime: {
                        slug_id: result.slug_id,
                        numeric_id: result.numeric_id,
                        title: result.title,
                        poster_url: result.poster_url,
                        kind: result.kind,
                        rating: ""
                    }
                }
            )
        }
        function onAnilistAnimeResolveFailed(title) {
            showPassiveNotification("Couldn't find a stream for \"" + title + "\"")
        }
    }

    // Shared card-grid section (poster + title + subtitle). A plain manual
    // layout rather than Kirigami.Card -- Card's banner+contentItem composition
    // doesn't respect explicit sizing in this Kirigami version (see SearchPage.qml).
    component Section: ColumnLayout {
        id: root
        property alias model: repeater.model
        property string heading
        property string subtitleRole: "episode_number" // model role shown under the title
        property string subtitlePrefix: "Episode "
        signal cardClicked(int index)

        Layout.fillWidth: true
        visible: repeater.count > 0
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Heading {
            level: 2
            text: root.heading
        }

        GridLayout {
            id: sectionGrid
            Layout.fillWidth: true
            readonly property int idealCellWidth: 220
            columns: Math.max(1, Math.floor(page.width / idealCellWidth))
            // Cards stretch to exactly fill the row (accounting for the gaps
            // between them) instead of leaving unused space on the right.
            readonly property real cellWidth: (page.width - (columns - 1) * columnSpacing) / columns
            rowSpacing: Kirigami.Units.largeSpacing
            columnSpacing: Kirigami.Units.largeSpacing

            Repeater {
                id: repeater
                delegate: ColumnLayout {
                    required property int index
                    required property var model
                    Layout.preferredWidth: sectionGrid.cellWidth
                    spacing: Kirigami.Units.smallSpacing

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 260
                        radius: 4
                        clip: true
                        color: Kirigami.Theme.alternateBackgroundColor

                        Image {
                            anchors.fill: parent
                            source: model.poster_url
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.cardClicked(index)
                        }
                    }

                    Controls.Label {
                        Layout.fillWidth: true
                        text: model.title
                        wrapMode: Text.WordWrap
                        font.bold: true
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }
                    Controls.Label {
                        Layout.fillWidth: true
                        text: root.subtitlePrefix + model[root.subtitleRole]
                        opacity: 0.7
                    }
                }
            }
        }
    }

    ColumnLayout {
        width: page.width
        spacing: Kirigami.Units.largeSpacing

        Section {
            heading: "Continue Watching"
            model: continueModel
            subtitleRole: "episode_number"
            onCardClicked: (index) => {
                let entry = continueModel.get(index)
                applicationWindow().pageStack.push(
                    Qt.resolvedUrl("DetailPage.qml"),
                    {
                        anime: {
                            slug_id: entry.slug_id,
                            numeric_id: entry.numeric_id,
                            title: entry.title,
                            poster_url: entry.poster_url,
                            kind: "",
                            rating: ""
                        }
                    }
                )
            }
        }

        Section {
            heading: "Watching"
            model: watchingModel
            subtitleRole: "progress"
            onCardClicked: (index) => {
                let entry = watchingModel.get(index)
                backend.openAnilistAnime(entry.anilist_id, entry.title)
            }
        }

        Section {
            heading: "Planning to Watch"
            model: planningModel
            subtitleRole: "progress"
            subtitlePrefix: ""
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
