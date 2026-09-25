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
    // The next Japanese broadcast, when the show is still airing. Only ever
    // the sub: no public API publishes a dub schedule, so the page says how
    // far behind the dub currently is rather than inventing a date for it.
    property string airingStatus: ""
    property int nextEpisode: 0
    property int nextAiringAt: 0
    // Ticks so the countdown counts down rather than freezing at whatever it
    // said when the page opened.
    property real nowSeconds: Date.now() / 1000

    readonly property bool airingSoon: page.nextAiringAt > 0
        && page.nextAiringAt > page.nowSeconds

    // How many dubbed episodes are behind the subbed ones, from the source's
    // own two counts (AniList has neither).
    // The card that opened the page may carry them; the source's own page
    // is asked every time regardless (see backend.audioCountsReady), since
    // many ways in carry no counts and a dub gains episodes weekly.
    property int fetchedSubCount: -1
    property int fetchedDubCount: -1
    readonly property int subCount: page.fetchedSubCount >= 0 ? page.fetchedSubCount : (page.anime.sub_count || 0)
    readonly property int dubCount: page.fetchedDubCount >= 0 ? page.fetchedDubCount : (page.anime.dub_count || 0)
    // Whether the dub count is actually known -- a card with no counts
    // reads as 0, which must not hide every episode.
    readonly property bool dubCountKnown: page.fetchedDubCount >= 0 || (page.anime.sub_count || 0) > 0

    // The episodes the chosen audio actually has. The source's dub count
    // means "the first N" -- verified live on One Piece (1155 of 1179:
    // 1155 has a dub server, 1156 doesn't) -- so the dub list is a prefix of
    // the sub one, and with Dub selected nothing past it is offered.
    readonly property int shownEpisodeCount: page.dub && page.dubCountKnown
        ? Math.min(page.dubCount, episodesModel.count) : episodesModel.count
    // Deferred, and through one named function: Qt.callLater collapses
    // repeat calls of the *same* function into one. The list is filled a row
    // at a time, so this count changes once per episode -- and with a fresh
    // arrow function each time, One Piece queued 1179 rebuilds of a
    // 100-cell page and froze the window.
    onShownEpisodeCountChanged: Qt.callLater(page.reshowCurrentPage)
    function reshowCurrentPage() { page.showPage(page.currentPage) }
    readonly property int dubBehind: page.subCount > 0 && page.dubCount > 0
        ? Math.max(0, page.subCount - page.dubCount) : 0

    function countdownText(seconds) {
        if (seconds <= 0) return "any moment"
        let days = Math.floor(seconds / 86400)
        let hours = Math.floor((seconds % 86400) / 3600)
        let minutes = Math.floor((seconds % 3600) / 60)
        if (days > 0) return days + "d " + hours + "h"
        if (hours > 0) return hours + "h " + minutes + "m"
        return minutes + "m"
    }
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

    // The episode grid is left-aligned with a panel beside it, rather than
    // centred in the whole width. Centring a 10-wide grid in a wide window
    // left a column of empty page down both sides and nothing to read.
    readonly property int sidePanelWidth: Kirigami.Units.gridUnit * 15
    readonly property bool showSidePanel: page.bodyWidth > Kirigami.Units.gridUnit * 42
    readonly property real episodeAreaWidth: page.bodyWidth
        - (page.showSidePanel ? page.sidePanelWidth + Kirigami.Units.largeSpacing * 2 : 0)

    // Everything watched already. Worth its own name because "the episode
    // after the last one you saw" is episode 13 of a 12-episode show, which
    // is what the panel offered to play before this existed.
    readonly property bool allWatched: episodesModel.count > 0
        && page.anilistProgress >= episodesModel.count

    // Where the user would land on pressing play: the episode they stopped
    // partway through if there is one, otherwise the one after AniList's
    // progress, otherwise the beginning -- which is also where a finished
    // show sends them, since starting over is the only thing left.
    readonly property real resumeEpisode: {
        if (page.localProgress) return page.localProgress.episode_number
        if (page.anilistProgress > 0 && !page.allWatched) return page.anilistProgress + 1
        return page.firstEpisodeNumber()
    }

    // Best available count of what's been seen. AniList is authoritative when
    // the show is on the user's list; otherwise local playback is all there
    // is, and reaching episode N means N-1 are behind you.
    readonly property int watchedCount: Math.max(
        page.anilistProgress,
        page.localProgress ? Math.max(0, Math.round(page.localProgress.episode_number) - 1) : 0)

    // Set from the database once this show has been matched to AniList, and
    // written straight back when toggled -- see backend.isAnilistIgnored.
    property bool ignoreAnilist: false
    onAnilistIdChanged: {
        if (page.anilistId !== 0) page.ignoreAnilist = backend.isAnilistIgnored(page.anilistId)
    }

    // episode_id -> {status, progress} for this anime, refreshed whenever the
    // backend says something changed. A plain object reassigned wholesale, for
    // the same reason the home rows are arrays: QML only notifies `var`
    // properties on assignment.
    property var downloadState: ({})
    // Assigned once rather than bound: whether ffmpeg exists cannot change
    // while the app runs, and a binding that reads `backend` is re-evaluated
    // during teardown after the context property is gone.
    property bool canDownload: false
    // Keeps the next few episodes saved as you watch -- see
    // backend.setAutoDownload.
    property bool autoDownload: false
    // The audio it saves, chosen when it was switched on -- not the Sub/Dub
    // toggle, which only says what the next click will play.
    property bool autoDownloadDub: false

    function refreshDownloads() {
        if (!page.anime.slug_id) return
        let next = {}
        let rows = backend.downloadsFor(page.anime.slug_id)
        for (let i = 0; i < rows.length; i++) {
            let row = rows[i]
            // Keyed by episode and audio together: the sub and the dub are two
            // separate files (see the downloads table).
            next[row.episode_id + ":" + (row.dub ? 1 : 0)] =
                { status: row.status, progress: 0, message: row.message }
        }
        page.downloadState = next
    }

    function downloadKey(episodeId) { return episodeId + ":" + (page.dub ? 1 : 0) }

    function downloadFor(episodeId) {
        return page.downloadState[page.downloadKey(episodeId)] || null
    }

    function episodeSpec(episodeId, number) {
        return {
            episode_id: episodeId,
            dub: page.dub,
            slug_id: page.anime.slug_id,
            numeric_id: page.anime.numeric_id || "",
            title: page.anime.title || "",
            poster_url: page.coverUrl,
            episode_number: number
        }
    }

    function toggleDownload(episodeId, number) {
        let existing = page.downloadFor(episodeId)
        if (existing === null || existing.status === "failed") {
            backend.downloadEpisode(page.episodeSpec(episodeId, number))
        } else if (existing.status === "ready") {
            backend.removeDownload(episodeId, page.dub)
        } else {
            backend.cancelDownload(episodeId, page.dub)
        }
    }

    // Everything on the page currently shown, skipping what is already saved
    // or already running -- pressing this twice must not queue the season
    // twice.
    function downloadShownPage() {
        let specs = []
        for (let i = 0; i < pageEpisodesModel.count; i++) {
            let ep = pageEpisodesModel.get(i)
            let existing = page.downloadFor(ep.episode_id)
            if (existing === null || existing.status === "failed") {
                specs.push(page.episodeSpec(ep.episode_id, ep.number))
            }
        }
        if (specs.length === 0) {
            showPassiveNotification("Everything on this page is already saved or downloading.")
            return
        }
        backend.downloadEpisodes(specs)
        showPassiveNotification("Saving " + specs.length + " episode"
                                + (specs.length === 1 ? "" : "s") + "...")
    }

    function episodeTitleFor(number) {
        for (let i = 0; i < episodesModel.count; i++) {
            let ep = episodesModel.get(i)
            if (ep.number === number) return ep.title || ""
        }
        return ""
    }

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
    readonly property int pageCount: Math.max(1, Math.ceil(page.shownEpisodeCount / pageSize))

    Timer {
        // A minute, not a second: the countdown is shown in days and hours,
        // so a per-second tick would repaint sixty times for nothing.
        interval: 60000
        running: page.airingSoon
        repeat: true
        onTriggered: page.nowSeconds = Date.now() / 1000
    }

    Component.onCompleted: {
        backend.loadEpisodes(anime.slug_id, anime.numeric_id, anime.title, anime.poster_url)
        page.localProgress = backend.getLocalProgress(anime.slug_id)
        page.canDownload = backend.canDownload()
        page.autoDownload = backend.isAutoDownload(anime.slug_id)
        page.autoDownloadDub = backend.autoDownloadDub(anime.slug_id)
        page.refreshDownloads()
    }

    Connections {
        target: backend
        function onDownloadsChanged() { page.refreshDownloads() }
        function onDownloadProgress(episodeId, dub, fraction, bytesWritten) {
            let key = episodeId + ":" + (dub ? 1 : 0)
            let existing = page.downloadState[key]
            if (!existing) return
            // Rebuilt rather than mutated in place: assigning into the nested
            // object notifies nothing, and the bars would sit at zero for the
            // whole download.
            let next = Object.assign({}, page.downloadState)
            next[key] = { status: "downloading", progress: fraction, message: "" }
            page.downloadState = next
        }
        function onDownloadFailed(message) { showPassiveNotification(message) }
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
        function onAudioCountsReady(slug, subbed, dubbed) {
            if (slug !== page.anime.slug_id) return
            page.fetchedSubCount = subbed
            page.fetchedDubCount = dubbed
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
            page.airingStatus = extras.airingStatus || ""
            page.nextEpisode = extras.nextEpisode || 0
            page.nextAiringAt = extras.nextAiringAt || 0
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
        let end = Math.min(start + page.pageSize, page.shownEpisodeCount)
        for (let i = start; i < end; i++) pageEpisodesModel.append(episodesModel.get(i))
    }

    function pageEpisodesCount() { return pageEpisodesModel.count }
    function lastShownNumber() {
        return pageEpisodesModel.count > 0 ? pageEpisodesModel.get(pageEpisodesModel.count - 1).number : -1
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
            // The QQC2 desktop style sets Kirigami.Theme.inherit = false on its
            // controls, which stops the app's accent reaching them -- measured
            // live: a page themed red still drew Breeze-blue Sub/Dub buttons.
            // Turning inheritance back on is what makes one accent value reach
            // every control in the app. See AppTheming.qml.
            Kirigami.Theme.inherit: true
            running: page.loading
            visible: page.loading
            Layout.alignment: Qt.AlignHCenter
        }

        // What is still to come. Only drawn for a show that is actually
        // still running -- on a finished series there is nothing to say and a
        // permanently empty strip is worse than none.
        Rectangle {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.largeSpacing
            Layout.rightMargin: Kirigami.Units.largeSpacing
            Layout.preferredHeight: airingRow.implicitHeight + Kirigami.Units.largeSpacing
            visible: page.airingSoon || (page.airingStatus === "RELEASING" && page.dubBehind > 0)
            radius: Kirigami.Units.smallSpacing
            color: Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g,
                           Kirigami.Theme.highlightColor.b, 0.12)
            border.width: 1
            border.color: Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g,
                                  Kirigami.Theme.highlightColor.b, 0.35)

            RowLayout {
                id: airingRow
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Kirigami.Units.largeSpacing
                anchors.rightMargin: Kirigami.Units.largeSpacing
                spacing: Kirigami.Units.largeSpacing

                Kirigami.Icon {
                    source: "clock-symbolic"
                    isMask: true
                    color: Kirigami.Theme.highlightColor
                    implicitWidth: Kirigami.Units.iconSizes.small
                    implicitHeight: Kirigami.Units.iconSizes.small
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0

                    Controls.Label {
                        visible: page.airingSoon
                        text: "Episode " + page.nextEpisode + " (sub) airs in "
                            + page.countdownText(page.nextAiringAt - page.nowSeconds)
                        font.bold: true
                    }
                    Controls.Label {
                        visible: page.airingSoon
                        text: Qt.formatDateTime(new Date(page.nextAiringAt * 1000),
                                                "dddd d MMMM, h:mm ap")
                        opacity: 0.7
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    }
                    Controls.Label {
                        Layout.fillWidth: true
                        // Said plainly rather than as a second countdown: no
                        // public source publishes dub air dates, so the only
                        // honest thing to report is the gap that exists now.
                        visible: page.dubBehind > 0 || page.dubCount === 0
                        text: page.dubCount === 0
                            ? "No dub available yet."
                            : "Dub is " + page.dubBehind + " episode"
                              + (page.dubBehind === 1 ? "" : "s") + " behind ("
                              + page.dubCount + " of " + page.subCount + " dubbed)."
                        opacity: 0.8
                        wrapMode: Text.WordWrap
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    }
                }
            }
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
                text: page.dub && page.dubCountKnown
                    ? page.shownEpisodeCount + " dubbed"
                      + (page.shownEpisodeCount < episodesModel.count
                         ? " of " + episodesModel.count : "")
                    : episodesModel.count + " available"
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

            AppButton {
                // "This page", not "this season": a long-runner is paged in
                // hundreds, and a button on One Piece that quietly starts
                // eleven hundred downloads is a trap rather than a
                // convenience.
                text: page.pageCount > 1 ? "Save these" : "Save season"
                icon.name: "folder-download-symbolic"
                visible: page.canDownload && episodesModel.count > 0
                onClicked: page.downloadShownPage()
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Save every episode shown below for offline watching"
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
                    text: (index * page.pageSize + 1) + "-" + Math.min((index + 1) * page.pageSize, page.shownEpisodeCount)
                    checkable: true
                    checked: page.currentPage === index
                    onClicked: page.showPage(index)
                }
            }
        }

        Kirigami.PlaceholderMessage {
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.largeSpacing
            visible: page.dub && page.dubCountKnown && page.dubCount === 0 && episodesModel.count > 0
            icon.name: "audio-volume-muted-symbolic"
            text: "No dubbed episodes yet"
            explanation: "Switch to Sub to watch the " + episodesModel.count + " that are out."
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
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.largeSpacing
            Layout.rightMargin: Kirigami.Units.largeSpacing
            Layout.bottomMargin: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.largeSpacing * 2

            GridLayout {
                id: episodeGrid
                Layout.alignment: Qt.AlignTop | Qt.AlignLeft

                readonly property int shownCount: pageEpisodesModel.count
                readonly property int idealColumns: page.rowLengthFor(shownCount)
                // Never more columns than fit: on a narrow window the chosen
                // count would otherwise push the grid off the right edge.
                columns: Math.max(1, Math.min(idealColumns,
                                              Math.floor(page.episodeAreaWidth / minCellSize)))
                readonly property int minCellSize: 44
                readonly property int maxCellSize: 72
                readonly property real cellSize: Math.min(
                    maxCellSize,
                    (page.episodeAreaWidth - (columns - 1) * columnSpacing) / columns)
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

                        // Saved / downloading marker. A corner dot rather
                        // than a badge: a hundred badges in a grid of a
                        // hundred cells is just noise, and the only question
                        // being answered here is "is this one on disk".
                        Rectangle {
                            readonly property var state: page.downloadFor(model.episode_id)
                            visible: state !== null
                            anchors.top: parent.top
                            anchors.right: parent.right
                            anchors.margins: 3
                            width: Math.max(6, Math.round(episodeGrid.cellSize * 0.16))
                            height: width
                            radius: width / 2
                            color: !state ? "transparent"
                                 : state.status === "ready" ? Kirigami.Theme.positiveTextColor
                                 : state.status === "failed" ? Kirigami.Theme.negativeTextColor
                                 : Kirigami.Theme.neutralTextColor
                        }

                        // Fills along the bottom edge as the episode saves, so
                        // a queue of them reads at a glance.
                        Rectangle {
                            readonly property var state: page.downloadFor(model.episode_id)
                            visible: !!state && state.status === "downloading"
                            anchors.left: parent.left
                            anchors.bottom: parent.bottom
                            anchors.margins: 2
                            height: 3
                            radius: 1.5
                            width: (parent.width - 4) * (state ? state.progress : 0)
                            color: Kirigami.Theme.highlightColor
                        }

                        HoverHandler { id: cellHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: page.requestEpisode(model.number) }
                        // Right-click saves or removes it. A second button on
                        // every cell would double the grid's weight for
                        // something used on a handful of episodes.
                        TapHandler {
                            acceptedButtons: Qt.RightButton
                            onTapped: if (page.canDownload) page.toggleDownload(model.episode_id, model.number)
                        }

                        Controls.ToolTip.visible: cellHover.hovered
                        Controls.ToolTip.text: {
                            let parts = []
                            if (model.title !== "") parts.push(model.title)
                            let state = page.downloadFor(model.episode_id)
                            if (state && state.status === "ready") parts.push("Saved -- right-click to remove")
                            else if (state && state.status === "downloading") parts.push("Saving... right-click to cancel")
                            else if (state && state.status === "queued") parts.push("Queued -- right-click to cancel")
                            else if (state && state.status === "failed") parts.push("Failed: " + state.message)
                            else if (page.canDownload) parts.push("Right-click to save offline")
                            return parts.join("\n")
                        }
                        Controls.ToolTip.delay: 400
                    }
                }
            }

            // Soaks up whatever is left over so the grid stays pinned left
            // and the panel stays pinned right, at every window width.
            Item { Layout.fillWidth: true; Layout.preferredHeight: 1 }

            // The panel beside the grid. What belongs next to a wall of
            // numbers is the answer to "which one do I press" -- so: where
            // you are, what's next, and the one per-show setting worth having
            // to hand.
            Rectangle {
                Layout.preferredWidth: page.sidePanelWidth
                Layout.alignment: Qt.AlignTop
                Layout.preferredHeight: sidePanel.implicitHeight + Kirigami.Units.largeSpacing * 2
                visible: page.showSidePanel && episodesModel.count > 0
                radius: Kirigami.Units.mediumSpacing
                color: Kirigami.Theme.alternateBackgroundColor

                ColumnLayout {
                    id: sidePanel
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: Kirigami.Units.largeSpacing
                    spacing: Kirigami.Units.smallSpacing

                    Controls.Label {
                        text: page.allWatched ? "Watch again"
                            : page.watchedCount > 0 ? "Up next" : "Start watching"
                        font.bold: true
                        opacity: 0.6
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    }

                    Kirigami.Heading {
                        level: 3
                        text: page.resumeEpisode > 0 ? "Episode " + page.resumeEpisode : "--"
                    }

                    Controls.Label {
                        Layout.fillWidth: true
                        text: page.episodeTitleFor(page.resumeEpisode)
                        visible: text !== ""
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        opacity: 0.75
                    }

                    AppButton {
                        Layout.fillWidth: true
                        Layout.topMargin: Kirigami.Units.smallSpacing
                        accented: true
                        icon.name: "media-playback-start-symbolic"
                        text: page.allWatched ? "Play" : page.watchedCount > 0 ? "Continue" : "Play"
                        enabled: page.resumeEpisode > 0
                        onClicked: page.requestEpisode(page.resumeEpisode)
                    }

                    Kirigami.Separator {
                        Layout.fillWidth: true
                        Layout.topMargin: Kirigami.Units.largeSpacing
                        Layout.bottomMargin: Kirigami.Units.smallSpacing
                    }

                    Controls.Label {
                        text: "Progress"
                        font.bold: true
                        opacity: 0.6
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 6
                        radius: 3
                        color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                                       Kirigami.Theme.textColor.b, 0.15)

                        Rectangle {
                            anchors.left: parent.left
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            width: parent.width * Math.min(1, episodesModel.count > 0
                                ? page.watchedCount / episodesModel.count : 0)
                            radius: parent.radius
                            color: Kirigami.Theme.highlightColor
                            Behavior on width { NumberAnimation { duration: 150 } }
                        }
                    }

                    Controls.Label {
                        text: page.watchedCount + " of " + episodesModel.count + " watched"
                        opacity: 0.7
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    }

                    Kirigami.Separator {
                        Layout.fillWidth: true
                        Layout.topMargin: Kirigami.Units.largeSpacing
                        Layout.bottomMargin: Kirigami.Units.smallSpacing
                        visible: page.anilistId !== 0
                    }

                    AppCheckBox {
                        Layout.fillWidth: true
                        visible: page.anilistId !== 0
                        text: "Don't sync to AniList"
                        checked: page.ignoreAnilist
                        onToggled: {
                            page.ignoreAnilist = checked
                            backend.setAnilistIgnored(page.anilistId, checked)
                        }
                    }

                    Controls.Label {
                        Layout.fillWidth: true
                        visible: page.anilistId !== 0
                        text: "Watching this won't touch your AniList progress. "
                            + "The buttons above still work."
                        wrapMode: Text.WordWrap
                        opacity: 0.6
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    }

                    Kirigami.Separator {
                        Layout.fillWidth: true
                        Layout.topMargin: Kirigami.Units.largeSpacing
                        Layout.bottomMargin: Kirigami.Units.smallSpacing
                        visible: page.canDownload
                    }

                    AppCheckBox {
                        Layout.fillWidth: true
                        visible: page.canDownload
                        text: "Keep the next 10 episodes saved ("
                            + ((page.autoDownload ? page.autoDownloadDub : page.dub) ? "dub" : "sub") + ")"
                        checked: page.autoDownload
                        onToggled: {
                            page.autoDownload = checked
                            page.autoDownloadDub = page.dub
                            backend.setAutoDownload(page.anime.slug_id, checked, page.dub,
                                                    page.resumeEpisode)
                            if (checked) showPassiveNotification("Saving the next episodes in the background")
                        }
                    }

                    Controls.Label {
                        Layout.fillWidth: true
                        visible: page.canDownload
                        text: "For long shows. Each episode you finish queues one more, and "
                            + "older ones are cleared as you go. Downloads slow down while "
                            + "you're watching, so they never interrupt the episode on screen."
                        wrapMode: Text.WordWrap
                        opacity: 0.6
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    }
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
                                Kirigami.Theme.inherit: true
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
