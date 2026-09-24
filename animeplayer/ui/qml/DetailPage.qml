import QtQuick
import QtQuick.Effects
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page

    // Paints this page in the app's colour scheme -- see AppTheming.qml
    // for why this is per-page rather than set once on the window.
    AppTheming {}
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

    // Filled in by onAnimeExtrasReady, well after the episode list -- each
    // section below stays hidden until its own data lands.
    property var watchOrder: []
    property var unwatchedPrequels: []
    property var related: []
    property var recommendations: []
    property var reviews: []
    // Set once the user has answered the out-of-order prompt, so it asks at
    // most once per visit to this page rather than on every episode click.
    property bool warningAcknowledged: false

    // The user's own AniList status for this anime ("" when it isn't on their
    // list). Seeded from anilistCurrentStatus and then kept in step with what
    // the buttons on this page do, so the label matches the press without
    // waiting for a sync.
    property string listStatus: ""
    property bool listBusy: false
    readonly property int anilistId: page.anilistDetails ? (page.anilistDetails.anilist_id || 0) : 0

    // The header bleeds to the window edges, so the inset the page would
    // normally apply lives on the content items below it -- and the grids
    // that size their own columns need to know what width that leaves.
    // Not "contentWidth": that name is already a FINAL property on
    // Controls.Control, and shadowing it makes the whole page fail to load
    // with "Cannot override FINAL property".
    readonly property real bodyWidth: width - Kirigami.Units.largeSpacing * 2

    // Longer than this and the count is pinned to ten a row: a long-runner
    // is read by counting, and 1-10 / 11-20 is how people do that.
    readonly property int longRunnerEpisodes: 100
    readonly property int longRunnerColumns: 10
    // The window of row lengths worth considering. Below eight a row of a
    // 24-episode show becomes three rows; above fifteen the cells get small
    // and a row stops being countable at a glance.
    readonly property int minRowLength: 8
    readonly property int maxRowLength: 15

    function rowLengthFor(count) {
        if (count <= 0) return page.longRunnerColumns
        if (count >= page.longRunnerEpisodes) return page.longRunnerColumns
        // A short season is one row.
        if (count <= page.maxRowLength) return count

        let best = page.longRunnerColumns
        let bestGap = page.maxRowLength  // worse than any real candidate
        for (let columns = page.minRowLength; columns <= page.maxRowLength; columns++) {
            // How many cells the last row would be missing.
            let gap = (columns - (count % columns)) % columns
            // Ties go to the row closest to twelve, which is the length a
            // cour actually comes in.
            let tidier = gap < bestGap
                || (gap === bestGap && Math.abs(columns - 12) < Math.abs(best - 12))
            if (tidier) {
                best = columns
                bestGap = gap
            }
        }
        return best
    }

    readonly property var statusLabels: ({
        "CURRENT": "Watching", "PLANNING": "Planning", "COMPLETED": "Completed",
        "DROPPED": "Dropped", "PAUSED": "Paused", "REPEATING": "Rewatching"
    })

    function statusLabel(status) { return page.statusLabels[status] || status }

    function togglePlanning() {
        if (page.anilistId === 0) {
            showPassiveNotification("Still matching this to AniList -- try again in a moment.")
            return
        }
        page.listBusy = true
        backend.setListStatus(page.anilistId, page.listStatus === "PLANNING" ? "" : "PLANNING")
    }

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
        function onListStatusChanged(anilistId, status) {
            if (anilistId !== page.anilistId) return
            page.listBusy = false
            page.listStatus = status
            page.anilistLabel = status === "" ? "" : page.statusLabel(status)
            if (status === "") page.anilistProgress = 0
        }
        function onListStatusFailed(message) {
            page.listBusy = false
            showPassiveNotification(message)
        }
        function onAnilistMediaDetails(details) {
            page.anilistDetails = details
            page.listStatus = backend.listStatusOf(details.anilist_id || 0)
        }
        function onAnimeExtrasReady(extras) {
            // The backend only emits for the anime still open, but this page
            // may have been pushed twice for different shows -- check anyway.
            if (extras.slug_id !== page.anime.slug_id) return
            page.watchOrder = extras.watchOrder
            page.unwatchedPrequels = extras.unwatchedPrequels
            page.related = extras.related
            page.recommendations = extras.recommendations
            page.reviews = extras.reviews
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

    // What every play button and episode cell calls. playEpisode() itself
    // stays the unconditional version, so "Watch anyway" has something to
    // call that won't ask again.
    function requestEpisode(number) {
        if (!page.warningAcknowledged && page.unwatchedPrequels.length > 0) {
            prequelWarning.pendingEpisode = number
            prequelWarning.open()
            return
        }
        page.playEpisode(number)
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
                    GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.8) }
                }
            }

            // Dissolves the key art into the page rather than stopping at a
            // hard horizontal line partway down the window, which read as a
            // cropped box sitting on top of the page.
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: Math.round(parent.height * 0.4)
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "transparent" }
                    GradientStop {
                        position: 0.6
                        color: Qt.rgba(Kirigami.Theme.backgroundColor.r,
                                       Kirigami.Theme.backgroundColor.g,
                                       Kirigami.Theme.backgroundColor.b, 0.7)
                    }
                    GradientStop { position: 1.0; color: Kirigami.Theme.backgroundColor }
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

                        AppButton {
                            text: page.localProgress
                                ? ("Continue — Episode " + page.localProgress.episode_number)
                                : "Start Watching"
                            icon.name: "media-playback-start-symbolic"
                            accented: true
                            onClicked: page.requestEpisode(page.localProgress ? page.localProgress.episode_number : 1)
                        }

                        AppButton {
                            text: page.listBusy ? "Saving..."
                                : page.listStatus === "PLANNING" ? "In Planning"
                                : "Plan to Watch"
                            icon.name: page.listStatus === "PLANNING"
                                ? "checkmark-symbolic" : "list-add-symbolic"
                            enabled: !page.listBusy
                            checked: page.listStatus === "PLANNING"
                            // Only offered once there is an AniList match to
                            // act on -- a button that always fails is worse
                            // than no button.
                            visible: page.anilistId !== 0
                            onClicked: page.togglePlanning()
                        }

                        // A two-way switch rather than a label and two radio
                        // buttons: there are exactly two options and one is
                        // always chosen, which is what a segmented control is.
                        RowLayout {
                            spacing: 0
                            Repeater {
                                model: [{ label: "Sub", dub: false }, { label: "Dub", dub: true }]
                                AppButton {
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
                    border.color: Kirigami.Theme.neutralTextColor
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
            // in HomePage.qml/BrowsePage.qml.
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
                delegate: AppButton {
                    required property int index
                    text: (index * page.pageSize + 1) + "-" + Math.min((index + 1) * page.pageSize, episodesModel.count)
                    checkable: true
                    checked: page.currentPage === index
                    onClicked: page.showPage(index)
                }
            }
        }

        // A row length chosen to come out even, centred, rather than as many
        // episodes as happen to fit the window. Sizing columns from the width
        // laid the same show out differently at every window size, and none
        // of those numbers meant anything.
        //
        // What "even" means: a length that divides the episode count, so the
        // last row is full -- 13 episodes go 13 across, 20 go 10 and 10, 24 go
        // 12 and 12. Where nothing divides it (25, say) the one leaving the
        // fullest last row wins. Long-runners are pinned to 10, which is the
        // number people actually count in and keeps a 100-episode page a
        // neat 10x10.
        GridLayout {
            id: episodeGrid
            Layout.alignment: Qt.AlignHCenter
            Layout.leftMargin: Kirigami.Units.largeSpacing
            Layout.rightMargin: Kirigami.Units.largeSpacing
            Layout.bottomMargin: Kirigami.Units.largeSpacing

            readonly property int shownCount: pageEpisodesModel.count
            readonly property int idealColumns: page.rowLengthFor(shownCount)
            // Never more columns than fit: on a narrow window the chosen
            // count would otherwise push the grid off the right edge.
            columns: Math.max(1, Math.min(idealColumns,
                                          Math.floor(page.bodyWidth / minCellSize)))
            readonly property int minCellSize: 44
            readonly property int maxCellSize: 72
            readonly property real cellSize: Math.min(
                maxCellSize,
                (page.bodyWidth - (columns - 1) * columnSpacing) / columns)
            rowSpacing: Kirigami.Units.smallSpacing
            columnSpacing: Kirigami.Units.smallSpacing

            Repeater {
                model: pageEpisodesModel
                delegate: Rectangle {
                    id: episodeCell
                    required property var model
                    readonly property bool watched: page.anilistProgress > 0 && model.number <= page.anilistProgress
                    // !!, because `page.localProgress && ...` evaluates to
                    // null (not false) when there is no saved progress, and
                    // QML refuses to assign null to a bool.
                    readonly property bool resumeHere: !!page.localProgress
                        && page.localProgress.episode_number === model.number

                    Layout.preferredWidth: episodeGrid.cellSize
                    Layout.preferredHeight: episodeGrid.cellSize
                    // maximumWidth as well as preferred: a GridLayout hands
                    // any width left over to its columns, so preferred alone
                    // still stretched the cells into wide rectangles.
                    Layout.maximumWidth: episodeGrid.cellSize
                    Layout.maximumHeight: episodeGrid.cellSize
                    radius: Kirigami.Units.smallSpacing
                    color: cellHover.hovered ? Kirigami.Theme.highlightColor
                         : watched ? Qt.rgba(Kirigami.Theme.highlightColor.r,
                                             Kirigami.Theme.highlightColor.g,
                                             Kirigami.Theme.highlightColor.b, 0.55)
                         : Kirigami.Theme.alternateBackgroundColor
                    Behavior on color { ColorAnimation { duration: 100 } }
                    // Filler keeps its orange outline; the episode you'd
                    // resume on gets the accent one, so it's findable in a
                    // grid of a thousand.
                    border.color: model.filler ? Kirigami.Theme.neutralTextColor
                                               : Kirigami.Theme.highlightColor
                    border.width: model.filler ? 2 : (resumeHere ? 2 : 0)
                    scale: cellHover.hovered ? 1.08 : 1
                    Behavior on scale { NumberAnimation { duration: 100; easing.type: Easing.OutCubic } }
                    // Lift the hovered cell above its neighbours, or the
                    // scaled edges slide under the next cells along.
                    z: cellHover.hovered ? 1 : 0

                    Controls.Label {
                        anchors.centerIn: parent
                        text: model.number
                        font.bold: true
                        // Scaled to the cell rather than left at the default
                        // body size, which read as tiny inside a 70px box.
                        font.pixelSize: Math.max(
                            Kirigami.Theme.defaultFont.pixelSize,
                            Math.round(episodeGrid.cellSize * 0.34))
                        color: (episodeCell.watched || cellHover.hovered)
                            ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor
                    }

                    HoverHandler { id: cellHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: page.requestEpisode(model.number) }

                    Controls.ToolTip.visible: cellHover.hovered && model.title !== ""
                    Controls.ToolTip.text: model.title
                    Controls.ToolTip.delay: 400
                }
            }
        }

        // -- Everything else about this show ------------------------------
        //
        // All of it arrives together, well after the episode list, so each
        // section hides itself until its own data lands rather than the page
        // reserving space for sections that may turn out to be empty.

        SectionHeading {
            text: "Watch order"
            hint: page.unwatchedPrequels.length > 0
                ? "You haven't finished everything before this one" : ""
            visible: page.watchOrder.length > 1
        }

        // A column, not poster cards: watch order is a sequence, and reading
        // a sequence off a row of posters means reading the titles anyway.
        ColumnLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.largeSpacing
            Layout.rightMargin: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.smallSpacing
            visible: page.watchOrder.length > 1

            Repeater {
                model: page.watchOrder

                Rectangle {
                    required property var modelData
                    required property int index

                    Layout.fillWidth: true
                    implicitHeight: orderRow.implicitHeight + Kirigami.Units.largeSpacing
                    radius: Kirigami.Units.smallSpacing
                    color: modelData.current
                        ? Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g,
                                  Kirigami.Theme.highlightColor.b, 0.18)
                        : (orderHover.hovered ? Kirigami.Theme.alternateBackgroundColor : "transparent")
                    border.width: modelData.current ? 1 : 0
                    border.color: Kirigami.Theme.highlightColor

                    RowLayout {
                        id: orderRow
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.leftMargin: Kirigami.Units.largeSpacing
                        anchors.rightMargin: Kirigami.Units.largeSpacing
                        spacing: Kirigami.Units.largeSpacing

                        Controls.Label {
                            text: index + 1
                            opacity: 0.5
                            font.bold: true
                        }

                        Controls.Label {
                            Layout.fillWidth: true
                            text: modelData.title
                            font.bold: modelData.current
                            elide: Text.ElideRight
                        }

                        Controls.Label {
                            text: [modelData.year > 0 ? modelData.year : "",
                                   modelData.episodes > 0 ? modelData.episodes + " eps" : ""]
                                .filter((part) => !!part).join(" \u00b7 ")
                            opacity: 0.6
                            font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                        }

                        // Says where the user is, not just what exists -- the
                        // whole point of showing the order is to know what is
                        // still missing before this one.
                        Kirigami.Icon {
                            source: modelData.watched ? "checkmark-symbolic" : "media-playback-start-symbolic"
                            width: Kirigami.Units.iconSizes.small
                            height: width
                            opacity: modelData.watched ? 0.9 : 0.35
                            color: modelData.watched ? Kirigami.Theme.positiveTextColor
                                                     : Kirigami.Theme.textColor
                            isMask: true
                        }
                    }

                    HoverHandler { id: orderHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler {
                        onTapped: if (!modelData.current) {
                            backend.openAnilistAnime(modelData.anilist_id, modelData.title)
                        }
                    }
                }
            }
        }

        SectionHeading {
            text: "Related"
            visible: page.related.length > 0
        }

        PosterRow {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.largeSpacing
            Layout.rightMargin: Kirigami.Units.largeSpacing
            model: page.related
            visible: page.related.length > 0
            subtitleFor: (entry) => entry.reason
            onCardClicked: (index) => backend.openAnilistAnime(
                page.related[index].anilist_id, page.related[index].title)
        }

        SectionHeading {
            text: "If you liked this"
            visible: page.recommendations.length > 0
        }

        PosterRow {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.largeSpacing
            Layout.rightMargin: Kirigami.Units.largeSpacing
            model: page.recommendations
            visible: page.recommendations.length > 0
            subtitleFor: (entry) => entry.kind
            onCardClicked: (index) => backend.openAnilistAnime(
                page.recommendations[index].anilist_id, page.recommendations[index].title)
        }

        SectionHeading {
            text: "What people say"
            hint: "Summaries only \u2014 no spoilers"
            visible: page.reviews.length > 0
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.largeSpacing
            Layout.rightMargin: Kirigami.Units.largeSpacing
            Layout.bottomMargin: Kirigami.Units.gridUnit
            spacing: Kirigami.Units.smallSpacing
            visible: page.reviews.length > 0

            Repeater {
                model: page.reviews

                Rectangle {
                    required property var modelData

                    Layout.fillWidth: true
                    implicitHeight: reviewColumn.implicitHeight + Kirigami.Units.largeSpacing * 2
                    radius: Kirigami.Units.smallSpacing
                    color: Kirigami.Theme.alternateBackgroundColor

                    ColumnLayout {
                        id: reviewColumn
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.leftMargin: Kirigami.Units.largeSpacing
                        anchors.rightMargin: Kirigami.Units.largeSpacing
                        spacing: Kirigami.Units.smallSpacing

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.smallSpacing

                            Rectangle {
                                visible: modelData.score > 0
                                radius: height / 2
                                implicitWidth: scoreLabel.implicitWidth + Kirigami.Units.largeSpacing
                                implicitHeight: scoreLabel.implicitHeight + Kirigami.Units.smallSpacing
                                // Green/amber/red by the reviewer's own score,
                                // the way AniList colours them.
                                color: modelData.score >= 75 ? Kirigami.Theme.positiveTextColor
                                     : modelData.score >= 50 ? Kirigami.Theme.neutralTextColor
                                     : Kirigami.Theme.negativeTextColor

                                Controls.Label {
                                    id: scoreLabel
                                    anchors.centerIn: parent
                                    text: modelData.score
                                    color: "white"
                                    font.bold: true
                                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                                }
                            }

                            Controls.Label {
                                text: modelData.user
                                font.bold: true
                            }

                            Controls.Label {
                                text: modelData.helpful > 0
                                    ? modelData.helpful + " found this helpful" : ""
                                opacity: 0.6
                                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                            }

                            Item { Layout.fillWidth: true }

                            // The full review is deliberately not shown in the
                            // app: only the author's own summary line is
                            // reliably spoiler-free, and there is no flag on
                            // the rest to filter by.
                            Controls.ToolButton {
                                text: "Read full review"
                                icon.name: "link-symbolic"
                                onClicked: Qt.openUrlExternally(modelData.url)
                            }
                        }

                        Controls.Label {
                            Layout.fillWidth: true
                            text: modelData.summary
                            wrapMode: Text.WordWrap
                            opacity: 0.85
                        }
                    }
                }
            }
        }
    }

    // Warning before starting a season whose earlier entries are unwatched.
    // Deliberately a prompt and not a block: plenty of people rewatch out of
    // order or have watched something outside the app.
    Kirigami.PromptDialog {
        id: prequelWarning
        title: "Out of order?"
        property real pendingEpisode: -1

        standardButtons: Kirigami.Dialog.NoButton
        customFooterActions: [
            Kirigami.Action {
                text: "Watch anyway"
                icon.name: "media-playback-start-symbolic"
                onTriggered: {
                    page.warningAcknowledged = true
                    prequelWarning.close()
                    page.playEpisode(prequelWarning.pendingEpisode)
                }
            },
            Kirigami.Action {
                text: page.unwatchedPrequels.length > 0
                    ? "Open " + page.unwatchedPrequels[0].title : "Open earlier season"
                icon.name: "go-previous-symbolic"
                onTriggered: {
                    prequelWarning.close()
                    let first = page.unwatchedPrequels[0]
                    backend.openAnilistAnime(first.anilist_id, first.title)
                }
            }
        ]

        ColumnLayout {
            spacing: Kirigami.Units.smallSpacing

            Controls.Label {
                Layout.fillWidth: true
                Layout.maximumWidth: Kirigami.Units.gridUnit * 24
                wrapMode: Text.WordWrap
                text: page.unwatchedPrequels.length === 1
                    ? "This comes after \"" + page.unwatchedPrequels[0].title
                      + "\", which you haven't finished."
                    : "This comes after " + page.unwatchedPrequels.length
                      + " entries you haven't finished."
            }

            Repeater {
                model: page.unwatchedPrequels
                Controls.Label {
                    required property var modelData
                    text: "\u2022 " + modelData.title
                        + (modelData.progress > 0 && modelData.episodes > 0
                           ? "  (" + modelData.progress + "/" + modelData.episodes + ")" : "")
                    opacity: 0.75
                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                }
            }
        }
    }

    component SectionHeading: RowLayout {
        property alias text: sectionLabel.text
        property string hint: ""

        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.largeSpacing
        Layout.rightMargin: Kirigami.Units.largeSpacing
        Layout.topMargin: Kirigami.Units.largeSpacing
        spacing: Kirigami.Units.smallSpacing

        Rectangle {
            Layout.preferredWidth: 4
            Layout.preferredHeight: sectionLabel.implicitHeight * 0.8
            radius: 2
            color: Kirigami.Theme.highlightColor
        }
        Kirigami.Heading {
            id: sectionLabel
            level: 3
        }
        Controls.Label {
            text: parent.hint
            visible: parent.hint !== ""
            opacity: 0.6
            font.pixelSize: Kirigami.Theme.smallFont.pixelSize
        }
        Item { Layout.fillWidth: true }
    }
}
