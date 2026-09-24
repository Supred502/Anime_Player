import QtQuick
import QtQuick.Effects
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

    // The header bleeds to the window edges, so the inset the page would
    // normally apply lives on the content items below it -- and the grids
    // that size their own columns need to know what width that leaves.
    // Not "contentWidth": that name is already a FINAL property on
    // Controls.Control, and shadowing it makes the whole page fail to load
    // with "Cannot override FINAL property".
    readonly property real bodyWidth: width - Kirigami.Units.largeSpacing * 2

    function hasFillerEpisodes() {
        for (let i = 0; i < pageEpisodesModel.count; i++) {
            if (pageEpisodesModel.get(i).filler) return true
        }
        return false
    }

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

    // The header's chip strip. Built as data rather than as a column of
    // conditionally-visible Labels because what's known about a show arrives
    // in two waves: the card that opened this page knows its format, and the
    // AniList lookup lands a second later with the rest. The AniList facts
    // supersede the card's, so they replace them here rather than appearing
    // beside them repeating the same format back.
    function headerFacts() {
        let facts = []
        if (page.anilistLabel !== "") {
            facts.push({
                text: page.anilistLabel + (page.anilistProgress > 0
                    ? " · Episode " + page.anilistProgress : ""),
                accent: true
            })
        }
        let details = page.anilistDetails
        if (details) {
            if (details.format) facts.push({ text: details.format, accent: false })
            if (details.episodes) facts.push({ text: details.episodes + " episodes", accent: false })
            if (details.average_score) facts.push({ text: "★ " + details.average_score + "%", accent: false })
            let genres = details.genres || []
            // Capped: some entries carry eight or nine genres, which turns
            // the strip into three more lines of chips than the synopsis.
            for (let i = 0; i < Math.min(4, genres.length); i++) {
                facts.push({ text: genres[i], accent: false })
            }
        } else {
            if (page.anime.kind) facts.push({ text: page.anime.kind, accent: false })
            if (page.anime.rating) facts.push({ text: "★ " + page.anime.rating, accent: false })
        }
        return facts
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

    // The page bleeds its header to the window edges, like the home page's
    // hero; the inset is applied to the content below it instead.
    topPadding: 0
    leftPadding: 0
    rightPadding: 0

    readonly property string bannerUrl:
        (anilistDetails && anilistDetails.banner_url) || ""
    readonly property string coverUrl:
        (anilistDetails && anilistDetails.cover_url) || anime.poster_url || ""

    ColumnLayout {
        width: page.width
        spacing: Kirigami.Units.largeSpacing

        // Header: key art behind the poster and the title block. AniList only
        // has a wide banner for the better-known entries, so when there isn't
        // one this falls back to the cover art itself, cropped wide and
        // darkened -- which still reads as key art rather than as a gap.
        Item {
            Layout.fillWidth: true
            implicitHeight: Math.max(headerContent.implicitHeight + Kirigami.Units.gridUnit * 2,
                                     Kirigami.Units.gridUnit * 16)

            Image {
                anchors.fill: parent
                source: page.bannerUrl !== "" ? page.bannerUrl : page.coverUrl
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                verticalAlignment: Image.AlignTop
                // The cover fallback is portrait art stretched across a wide
                // box, so it gets blurred to read as a backdrop rather than
                // as a badly cropped poster.
                layer.enabled: page.bannerUrl === ""
                layer.effect: MultiEffect { blurEnabled: true; blur: 1.0; blurMax: 48 }
            }

            Rectangle {
                anchors.fill: parent
                gradient: Gradient {
                    GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0.55) }
                    GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.88) }
                }
            }

            RowLayout {
                id: headerContent
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Kirigami.Units.largeSpacing
                anchors.rightMargin: Kirigami.Units.largeSpacing
                spacing: Kirigami.Units.largeSpacing

                Rectangle {
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 9
                    Layout.preferredHeight: Math.round(width * 1.5)
                    Layout.alignment: Qt.AlignTop
                    radius: Kirigami.Units.mediumSpacing
                    clip: true
                    color: Qt.rgba(1, 1, 1, 0.08)

                    Image {
                        anchors.fill: parent
                        source: page.coverUrl
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop
                    spacing: Kirigami.Units.smallSpacing

                    Controls.Label {
                        text: page.anime.title
                        color: "white"
                        font.pointSize: 20
                        font.bold: true
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }

                    // Facts as chips rather than one run-on line. The old
                    // version joined format, episode count, score and every
                    // genre with dots into a single paragraph that wrapped
                    // across three lines and read as prose.
                    Flow {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing

                        Repeater {
                            model: page.headerFacts()
                            Rectangle {
                                required property var modelData
                                radius: height / 2
                                color: modelData.accent ? Kirigami.Theme.highlightColor
                                                        : Qt.rgba(1, 1, 1, 0.16)
                                width: factLabel.implicitWidth + Kirigami.Units.largeSpacing
                                height: factLabel.implicitHeight + Kirigami.Units.smallSpacing

                                Controls.Label {
                                    id: factLabel
                                    anchors.centerIn: parent
                                    text: modelData.text
                                    color: "white"
                                    font.bold: modelData.accent
                                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                                }
                            }
                        }
                    }

                    Controls.Label {
                        visible: !!(page.anilistDetails && page.anilistDetails.description)
                        text: page.anilistDetails ? page.anilistDetails.description : ""
                        color: "white"
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        Layout.topMargin: Kirigami.Units.smallSpacing
                        maximumLineCount: 4
                        elide: Text.ElideRight
                        opacity: 0.8
                    }

                    RowLayout {
                        Layout.topMargin: Kirigami.Units.smallSpacing
                        spacing: Kirigami.Units.largeSpacing

                        Controls.Button {
                            text: page.localProgress
                                ? ("Continue — Episode " + page.localProgress.episode_number)
                                : "Start Watching"
                            icon.name: "media-playback-start-symbolic"
                            highlighted: true
                            onClicked: page.playEpisode(page.localProgress ? page.localProgress.episode_number : 1)
                        }

                        // A two-way switch rather than a label and two radio
                        // buttons: there are exactly two options and one is
                        // always chosen, which is what a segmented control is.
                        RowLayout {
                            spacing: 0
                            Repeater {
                                model: [{ label: "Sub", dub: false }, { label: "Dub", dub: true }]
                                Controls.Button {
                                    required property var modelData
                                    text: modelData.label
                                    checkable: true
                                    checked: page.dub === modelData.dub
                                    onClicked: page.dub = modelData.dub
                                }
                            }
                        }
                    }
                }
            }
        }

        Controls.BusyIndicator {
            running: page.loading
            visible: page.loading
            Layout.alignment: Qt.AlignHCenter
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.largeSpacing
            Layout.rightMargin: Kirigami.Units.largeSpacing
            visible: episodesModel.count > 0
            spacing: Kirigami.Units.smallSpacing

            Rectangle {
                Layout.preferredWidth: 4
                Layout.preferredHeight: episodesHeading.implicitHeight * 0.8
                radius: 2
                color: Kirigami.Theme.highlightColor
            }
            Kirigami.Heading {
                id: episodesHeading
                level: 3
                text: "Episodes"
            }
            Controls.Label {
                text: episodesModel.count + " available"
                opacity: 0.6
            }
            Item { Layout.fillWidth: true }
            // Only worth explaining when there is something orange to explain.
            RowLayout {
                spacing: Kirigami.Units.smallSpacing
                visible: page.hasFillerEpisodes()
                Rectangle {
                    width: Kirigami.Units.iconSizes.small
                    height: width
                    radius: 3
                    color: "transparent"
                    border.color: "orange"
                    border.width: 2
                }
                Controls.Label {
                    text: "Filler"
                    opacity: 0.6
                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                }
            }
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
            Layout.leftMargin: Kirigami.Units.largeSpacing
            Layout.rightMargin: Kirigami.Units.largeSpacing
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
            Layout.leftMargin: Kirigami.Units.largeSpacing
            Layout.rightMargin: Kirigami.Units.largeSpacing
            Layout.bottomMargin: Kirigami.Units.largeSpacing
            readonly property int idealCellSize: 56
            columns: Math.max(1, Math.floor(page.bodyWidth / idealCellSize))
            // Cells stretch to exactly fill the row (accounting for the gaps
            // between them) instead of leaving unused space on the right.
            readonly property real cellSize: (page.bodyWidth - (columns - 1) * columnSpacing) / columns
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
