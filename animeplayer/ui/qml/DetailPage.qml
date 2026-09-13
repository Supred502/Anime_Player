import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page
    property var anime: ({})
    title: anime.title || "Details"

    ListModel { id: episodesModel }     // full list, source of truth
    ListModel { id: pageEpisodesModel } // just the currently-shown page of pageSize
    property bool loading: true
    property string anilistLabel: ""
    property int anilistProgress: 0
    property var localProgress: null
    property bool dub: false
    property var anilistDetails: null // {average_score, genres, format, episodes, description, cover_url}

    readonly property int pageSize: 100
    property int currentPage: 0
    readonly property int pageCount: Math.max(1, Math.ceil(episodesModel.count / pageSize))

    Component.onCompleted: {
        backend.loadEpisodes(anime.slug_id, anime.numeric_id, anime.title, anime.poster_url)
        page.localProgress = backend.getLocalProgress(anime.slug_id)
    }

    Connections {
        target: backend
        function onEpisodesFinished(episodes) {
            page.loading = false
            episodesModel.clear()
            for (let i = 0; i < episodes.length; i++) episodesModel.append(episodes[i])

            // Land on the page containing the resume episode, if any.
            let startIndex = 0
            if (page.localProgress) {
                for (let i = 0; i < episodesModel.count; i++) {
                    if (episodesModel.get(i).number === page.localProgress.episode_number) {
                        startIndex = i
                        break
                    }
                }
            }
            page.showPage(Math.floor(startIndex / page.pageSize))
        }
        function onAnimeRemapped(mapping) {
            // The id this page was opened with turned out to belong to a
            // different (or no longer existing) entry and was re-resolved by
            // title. Adopt the corrected one, or this page would keep saving
            // and reading progress under an id nothing else uses.
            let updated = page.anime
            updated.slug_id = mapping.slug_id
            updated.numeric_id = mapping.numeric_id
            page.anime = updated
            page.localProgress = backend.getLocalProgress(mapping.slug_id)
        }
        function onEpisodesFailed(message) {
            page.loading = false
            showPassiveNotification("Failed to load episodes: " + message)
        }
        function onAnilistCurrentStatus(label, progress) {
            page.anilistLabel = label
            page.anilistProgress = progress
        }
        function onAnilistMediaDetails(details) {
            page.anilistDetails = details
        }
        function onFillerEpisodesUpdated(episodeNumbers) {
            // The streaming source had no filler data for this show; these came from the
            // Jikan (MAL) fallback instead. Mark them in both the full list and
            // whatever page is currently shown.
            let asSet = {}
            for (let i = 0; i < episodeNumbers.length; i++) asSet[episodeNumbers[i]] = true
            for (let i = 0; i < episodesModel.count; i++) {
                if (asSet[episodesModel.get(i).number]) episodesModel.setProperty(i, "filler", true)
            }
            for (let i = 0; i < pageEpisodesModel.count; i++) {
                if (asSet[pageEpisodesModel.get(i).number]) pageEpisodesModel.setProperty(i, "filler", true)
            }
        }
    }

    function showPage(index) {
        page.currentPage = Math.max(0, Math.min(index, page.pageCount - 1))
        pageEpisodesModel.clear()
        let start = page.currentPage * page.pageSize
        let end = Math.min(start + page.pageSize, episodesModel.count)
        for (let i = start; i < end; i++) pageEpisodesModel.append(episodesModel.get(i))
    }

    function firstEpisodeNumber() {
        return episodesModel.count > 0 ? episodesModel.get(0).number : -1
    }

    function playEpisode(number) {
        for (let i = 0; i < episodesModel.count; i++) {
            let ep = episodesModel.get(i)
            if (ep.number === number) {
                applicationWindow().pageStack.push(
                    Qt.resolvedUrl("PlayerPage.qml"),
                    { anime: page.anime, episodeId: ep.episode_id, episodeNumber: ep.number, dub: page.dub }
                )
                return
            }
        }
    }

    ColumnLayout {
        width: page.width
        spacing: Kirigami.Units.largeSpacing

        RowLayout {
            Layout.fillWidth: true
            Image {
                source: (page.anilistDetails && page.anilistDetails.cover_url) || page.anime.poster_url
                Layout.preferredWidth: 120
                Layout.preferredHeight: 170
                fillMode: Image.PreserveAspectCrop
            }
            ColumnLayout {
                Layout.fillWidth: true
                Controls.Label {
                    text: page.anime.title
                    font.pointSize: 18
                    font.bold: true
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
                Controls.Label {
                    text: (page.anime.kind || "") + (page.anime.rating ? " · ★" + page.anime.rating : "")
                    opacity: 0.7
                }
                Controls.Label {
                    visible: page.anilistLabel !== ""
                    text: "AniList: " + page.anilistLabel + (page.anilistProgress > 0 ? " · Episode " + page.anilistProgress : "")
                    color: Kirigami.Theme.highlightColor
                    font.bold: true
                }
                Controls.Label {
                    visible: !!page.anilistDetails
                    text: page.anilistDetails ? (
                        (page.anilistDetails.format || "") +
                        (page.anilistDetails.episodes ? " · " + page.anilistDetails.episodes + " episodes" : "") +
                        (page.anilistDetails.average_score ? " · AniList " + page.anilistDetails.average_score + "%" : "") +
                        (page.anilistDetails.genres && page.anilistDetails.genres.length ? " · " + page.anilistDetails.genres.join(", ") : "")
                    ) : ""
                    opacity: 0.7
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
                Controls.Label {
                    visible: !!(page.anilistDetails && page.anilistDetails.description)
                    text: page.anilistDetails ? page.anilistDetails.description : ""
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                    maximumLineCount: 4
                    elide: Text.ElideRight
                    opacity: 0.85
                }

                RowLayout {
                    Controls.Button {
                        text: page.localProgress
                            ? ("Continue — Episode " + page.localProgress.episode_number)
                            : "Start Watching"
                        icon.name: "media-playback-start-symbolic"
                        onClicked: page.playEpisode(page.localProgress ? page.localProgress.episode_number : 1)
                    }
                    Controls.Label { text: "Audio:" }
                    Controls.ButtonGroup { id: audioGroup }
                    Controls.RadioButton {
                        text: "Sub"
                        checked: !page.dub
                        Controls.ButtonGroup.group: audioGroup
                        onToggled: if (checked) page.dub = false
                    }
                    Controls.RadioButton {
                        text: "Dub"
                        checked: page.dub
                        Controls.ButtonGroup.group: audioGroup
                        onToggled: if (checked) page.dub = true
                    }
                }
            }
        }

        Controls.BusyIndicator {
            running: page.loading
            visible: page.loading
            Layout.alignment: Qt.AlignHCenter
        }

        GridLayout {
            // A RowLayout (and, tried next, a Flow) here both overflowed past
            // the right edge of the screen for long shows (e.g. 1176-episode
            // One Piece -> 12 page buttons) -- neither actually wrapped inside
            // ScrollablePage's implicit Flickable no matter what width they
            // were bound to. A GridLayout with an explicit, width-derived
            // column count sidesteps that entirely -- same deterministic
            // pattern already used for episodeGrid below and the card grids
            // in HomePage.qml/SearchPage.qml.
            id: pageButtonGrid
            visible: page.pageCount > 1
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignHCenter
            readonly property int idealButtonWidth: 110
            columns: Math.max(1, Math.floor((applicationWindow().width - Kirigami.Units.gridUnit * 2) / idealButtonWidth))
            rowSpacing: Kirigami.Units.smallSpacing
            columnSpacing: Kirigami.Units.smallSpacing

            Repeater {
                model: page.pageCount
                delegate: Controls.Button {
                    required property int index
                    text: (index * page.pageSize + 1) + "-" + Math.min((index + 1) * page.pageSize, episodesModel.count)
                    checkable: true
                    checked: page.currentPage === index
                    onClicked: page.showPage(index)
                }
            }
        }

        GridLayout {
            id: episodeGrid
            Layout.fillWidth: true
            readonly property int idealCellSize: 56
            columns: Math.max(1, Math.floor(page.width / idealCellSize))
            // Cells stretch to exactly fill the row (accounting for the gaps
            // between them) instead of leaving unused space on the right.
            readonly property real cellSize: (page.width - (columns - 1) * columnSpacing) / columns
            rowSpacing: Kirigami.Units.smallSpacing
            columnSpacing: Kirigami.Units.smallSpacing

            Repeater {
                model: pageEpisodesModel
                delegate: Rectangle {
                    id: episodeCell
                    required property var model
                    readonly property bool watched: page.anilistProgress > 0 && model.number <= page.anilistProgress

                    Layout.preferredWidth: episodeGrid.cellSize
                    Layout.preferredHeight: episodeGrid.cellSize
                    radius: 4
                    color: watched ? Kirigami.Theme.highlightColor : Kirigami.Theme.alternateBackgroundColor
                    border.color: "orange"
                    border.width: model.filler ? 2 : 0

                    Controls.Label {
                        anchors.centerIn: parent
                        text: model.number
                        font.bold: true
                        color: episodeCell.watched ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.playEpisode(model.number)
                    }
                }
            }
        }
    }
}
