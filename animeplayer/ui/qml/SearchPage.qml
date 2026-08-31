import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page
    title: "Search"

    property bool searching: false
    property bool loadingMore: false
    property bool filterMode: false // true once genre/tag filters (or recommendations) are applied -- switches click-through + result shape
    property bool showingRecommendations: false
    property int resultPage: 1
    property bool hasMore: false
    property string recommendationsMessage: ""

    ListModel { id: resultsModel }
    ListModel { id: genreModel }   // {name, state} -- state: 0 neutral, 1 include, 2 exclude
    ListModel { id: tagModel }     // {name, state}, filtered view of allTags
    ListModel { id: statusModel }  // {name, key, state} -- "my list" status, fixed set, not fetched from anywhere
    ListModel { id: formatModel }  // {name, key, state} -- AniList MediaFormat enum, fixed set
    property var allTags: []       // full tag list from AniList
    property var tagStates: ({})   // name -> 1/2, persists across tag-filter retyping (tagModel gets rebuilt on every keystroke)

    Component.onCompleted: {
        backend.fetchAnilistGenres()
        backend.fetchAnilistTags()
        statusModel.append({ name: "Watching", key: "CURRENT", state: 0 })
        statusModel.append({ name: "Planning", key: "PLANNING", state: 0 })
        statusModel.append({ name: "Completed", key: "COMPLETED", state: 0 })
        statusModel.append({ name: "Dropped", key: "DROPPED", state: 0 })
        statusModel.append({ name: "Paused", key: "PAUSED", state: 0 })
        statusModel.append({ name: "Rewatching", key: "REPEATING", state: 0 })
        statusModel.append({ name: "Not in my list", key: "NOT_IN_LIST", state: 0 })
        formatModel.append({ name: "TV", key: "TV", state: 0 })
        formatModel.append({ name: "TV Short", key: "TV_SHORT", state: 0 })
        formatModel.append({ name: "Movie", key: "MOVIE", state: 0 })
        formatModel.append({ name: "Special", key: "SPECIAL", state: 0 })
        formatModel.append({ name: "OVA", key: "OVA", state: 0 })
        formatModel.append({ name: "ONA", key: "ONA", state: 0 })
        formatModel.append({ name: "Music", key: "MUSIC", state: 0 })
    }

    Connections {
        target: backend
        function onSearchFinished(results) {
            page.searching = false
            page.filterMode = false
            page.showingRecommendations = false
            page.hasMore = false
            page.recommendationsMessage = ""
            resultsModel.clear()
            for (let i = 0; i < results.length; i++) {
                // anilistLabel/anilistProgress start empty and are filled in later
                // by onAnilistStatusesResolved, once that background match finishes.
                // Declaring them here up front keeps the role set consistent across
                // every row -- ListModel doesn't like a role appearing only on some.
                let r = results[i]
                r.anilistLabel = ""
                r.anilistProgress = 0
                r.source = "anidb"
                resultsModel.append(r)
            }
        }
        function onSearchFailed(message) {
            page.searching = false
            page.loadingMore = false
            showPassiveNotification("Search failed: " + message)
        }
        function onFilterSearchFinished(payload) {
            page.searching = false
            page.loadingMore = false
            page.filterMode = true
            page.resultPage = payload.page
            page.hasMore = payload.hasMore
            page.recommendationsMessage = ""
            if (payload.page <= 1) resultsModel.clear()
            for (let i = 0; i < payload.results.length; i++) {
                let r = payload.results[i]
                r.source = "anilist"
                resultsModel.append(r)
            }
        }
        function onRecommendationsFailed(message) {
            page.searching = false
            page.filterMode = false
            page.showingRecommendations = false
            resultsModel.clear()
            page.recommendationsMessage = message
        }
        function onAnilistStatusesResolved(matches) {
            for (let i = 0; i < resultsModel.count; i++) {
                let slugId = resultsModel.get(i).slug_id
                if (matches[slugId] !== undefined) {
                    resultsModel.setProperty(i, "anilistLabel", matches[slugId].label)
                    resultsModel.setProperty(i, "anilistProgress", matches[slugId].progress)
                }
            }
        }
        function onAnilistGenresLoaded(genres) {
            genreModel.clear()
            for (let i = 0; i < genres.length; i++) genreModel.append({ name: genres[i], state: 0 })
        }
        function onAnilistTagsLoaded(tags) {
            page.allTags = tags
            page.applyTagFilterText("")
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

    function applyTagFilterText(text) {
        tagModel.clear()
        let needle = text.toLowerCase()
        let shown = 0
        for (let i = 0; i < page.allTags.length && shown < 200; i++) {
            if (needle === "" || page.allTags[i].toLowerCase().includes(needle)) {
                tagModel.append({ name: page.allTags[i], state: page.tagStates[page.allTags[i]] || 0 })
                shown++
            }
        }
    }

    // Cycles a chip through neutral -> include -> exclude -> neutral. Genres
    // live entirely in genreModel (never rebuilt), but tagModel is rebuilt on
    // every filter keystroke, so tag selections are tracked separately in
    // tagStates and re-applied in applyTagFilterText() so they survive that.
    function cycleGenre(index) {
        let next = (genreModel.get(index).state + 1) % 3
        genreModel.setProperty(index, "state", next)
    }
    function cycleStatus(index) {
        let next = (statusModel.get(index).state + 1) % 3
        statusModel.setProperty(index, "state", next)
    }
    function cycleFormat(index) {
        let next = (formatModel.get(index).state + 1) % 3
        formatModel.setProperty(index, "state", next)
    }
    function cycleTag(index) {
        let name = tagModel.get(index).name
        let next = (tagModel.get(index).state + 1) % 3
        tagModel.setProperty(index, "state", next)
        // Reassign (not mutate in place): page.tagStates is a plain JS object,
        // and QML's property-change notification for `var` properties only
        // fires on assignment, not on mutating an existing object's contents --
        // in-place mutation left bindings like the "Filters (N)" count button
        // stale until something else happened to force a re-evaluation.
        let updated = Object.assign({}, page.tagStates)
        if (next === 0) delete updated[name]
        else updated[name] = next
        page.tagStates = updated
    }

    function genreFilters() {
        let include = [], exclude = []
        for (let i = 0; i < genreModel.count; i++) {
            let row = genreModel.get(i)
            if (row.state === 1) include.push(row.name)
            else if (row.state === 2) exclude.push(row.name)
        }
        return { include: include, exclude: exclude }
    }

    function tagFilters() {
        let include = [], exclude = []
        for (let name in page.tagStates) {
            if (page.tagStates[name] === 1) include.push(name)
            else if (page.tagStates[name] === 2) exclude.push(name)
        }
        return { include: include, exclude: exclude }
    }

    function statusFilters() {
        let include = [], exclude = []
        for (let i = 0; i < statusModel.count; i++) {
            let row = statusModel.get(i)
            if (row.state === 1) include.push(row.key)
            else if (row.state === 2) exclude.push(row.key)
        }
        return { include: include, exclude: exclude }
    }

    function formatFilters() {
        let include = [], exclude = []
        for (let i = 0; i < formatModel.count; i++) {
            let row = formatModel.get(i)
            if (row.state === 1) include.push(row.key)
            else if (row.state === 2) exclude.push(row.key)
        }
        return { include: include, exclude: exclude }
    }

    function activeFilterCount() {
        let n = 0
        for (let i = 0; i < genreModel.count; i++) if (genreModel.get(i).state !== 0) n++
        for (let name in page.tagStates) if (page.tagStates[name] !== 0) n++
        for (let i = 0; i < statusModel.count; i++) if (statusModel.get(i).state !== 0) n++
        for (let i = 0; i < formatModel.count; i++) if (formatModel.get(i).state !== 0) n++
        return n
    }

    header: RowLayout {
        width: page.width
        Controls.TextField {
            id: queryField
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.smallSpacing
            placeholderText: "Search anime..."
            onAccepted: page.doSearch()
        }
        Controls.Button {
            text: page.activeFilterCount() > 0 ? "Filters (" + page.activeFilterCount() + ")" : "Filters"
            icon.name: "view-filter-symbolic"
            onClicked: filterSheet.open()
        }
        Controls.Button {
            text: "Search"
            onClicked: page.doSearch()
        }
    }

    function doSearch() {
        let g = page.genreFilters()
        let t = page.tagFilters()
        let s = page.statusFilters()
        let f = page.formatFilters()
        let hasFilters = g.include.length + g.exclude.length + t.include.length + t.exclude.length
            + s.include.length + s.exclude.length + f.include.length + f.exclude.length > 0
        page.showingRecommendations = false
        if (hasFilters) {
            page.searching = true
            page.resultPage = 1
            resultsModel.clear()
            backend.searchByFilters(
                queryField.text, g.include, g.exclude, t.include, t.exclude,
                s.include, s.exclude, f.include, f.exclude, 1
            )
            return
        }
        if (queryField.text.trim().length === 0) {
            page.loadRecommendations()
            return
        }
        page.searching = true
        resultsModel.clear()
        backend.search(queryField.text)
    }

    function loadRecommendations() {
        page.searching = true
        page.filterMode = true
        page.showingRecommendations = true
        page.hasMore = false
        page.recommendationsMessage = ""
        resultsModel.clear()
        backend.loadRecommendations()
    }

    function loadMore() {
        if (!page.hasMore || page.loadingMore) return
        let g = page.genreFilters()
        let t = page.tagFilters()
        let s = page.statusFilters()
        let f = page.formatFilters()
        page.loadingMore = true
        backend.searchByFilters(
            queryField.text, g.include, g.exclude, t.include, t.exclude,
            s.include, s.exclude, f.include, f.exclude, page.resultPage + 1
        )
    }

    Kirigami.OverlaySheet {
        id: filterSheet
        title: "Filter by genre / tags"

        // A plain Item, not the ColumnLayout itself, is what gets a forced
        // width/height -- ColumnLayout is meant to receive its geometry FROM
        // a parent (that's what makes Layout.fillHeight children inside it
        // redistribute correctly); self-assigning height directly on a
        // ColumnLayout didn't trigger that redistribution; the Tags
        // ScrollView still rendered at its full unwrapped size regardless
        // (confirmed live: filterColumn.height read back correctly as the
        // capped value, but children still visually overflowed past it).
        // anchors.fill here is genuine parent-imposed sizing instead.
        Item {
            id: filterBox
            // Kirigami.OverlaySheet's own source (templates/OverlaySheet.qml)
            // computes its width/height from Layout.preferredWidth/Height on
            // this content item FIRST, only falling back to implicitWidth/
            // Height if those are unset -- Layout.preferredWidth is
            // authoritative and doesn't depend on any child content state.
            Layout.preferredWidth: Math.min(820, applicationWindow().width - Kirigami.Units.gridUnit * 4)
            implicitWidth: Layout.preferredWidth
            width: Layout.preferredWidth
            // Also capping the height the same way, for the opposite reason:
            // OverlaySheet wraps ALL of this content in one big Flickable of
            // its own, so if the natural (unwrapped) height of everything
            // below exceeds the window, the WHOLE sheet scrolls as one lump --
            // genres, tags, my list, buttons all sliding out of view together.
            // Bounding the sheet's own height to the window and giving only
            // the Tags ScrollView Layout.fillHeight below means the outer
            // sheet never needs to scroll at all; only Tags does, internally.
            // OverlaySheet caps its own actual popup height to fit the window
            // regardless of what's requested here. Genres/Format/My List
            // consistently render fully visible without any scrolling in
            // testing (the "2 chips per row" / too-narrow bug is what this
            // was really about); on short windows, reaching the tail of Tags
            // and the Clear/Apply row can still take a scroll of the sheet
            // itself rather than only Tags scrolling -- an acceptable
            // fallback given OverlaySheet's own scrolling handles it either way.
            Layout.preferredHeight: Math.min(720, applicationWindow().height - Kirigami.Units.gridUnit * 4)
            implicitHeight: Layout.preferredHeight
            height: Layout.preferredHeight
            clip: true

        ColumnLayout {
            id: filterColumn
            anchors.fill: parent
            spacing: Kirigami.Units.largeSpacing

            // Layout.fillHeight on the Tags ScrollView below (letting it take
            // "whatever's left") turned out not to work through this nesting --
            // confirmed live that a *fixed* Layout.preferredHeight number does
            // correctly bound and scroll it, but Layout.fillHeight left it
            // rendering at its full unwrapped size regardless of filterColumn's
            // own (correctly-bounded) height. So instead of relying on
            // fillHeight redistribution, everything except the Tags scroll box
            // and the bottom buttons is grouped here so its combined
            // implicitHeight can be measured directly, and the Tags box is
            // given an explicit computed height: whatever's left over. See the
            // Layout.preferredHeight binding on the ScrollView below.
            ColumnLayout {
                id: nonScrollSection
                Layout.fillWidth: true
                spacing: filterColumn.spacing

                Controls.Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    opacity: 0.7
                    text: "Click once to require a genre/tag, click again to exclude it, click a third time to clear it."
                }

                Kirigami.Heading {
                    level: 3
                    text: "Genres"
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing
                    Repeater {
                        model: genreModel
                        delegate: FilterChip {
                            required property int index
                            required property var model
                            text: model.name
                            state3: model.state
                            onClicked: page.cycleGenre(index)
                        }
                    }
                }

                Kirigami.Heading {
                    level: 3
                    text: "Format"
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing
                    Repeater {
                        model: formatModel
                        delegate: FilterChip {
                            required property int index
                            required property var model
                            text: model.name
                            state3: model.state
                            onClicked: page.cycleFormat(index)
                        }
                    }
                }

                Kirigami.Heading {
                    level: 3
                    text: "My List"
                }
                Controls.Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    opacity: 0.7
                    text: "Include to show only that status, exclude to hide it -- e.g. exclude Completed, or include only Planning."
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing
                    Repeater {
                        model: statusModel
                        delegate: FilterChip {
                            required property int index
                            required property var model
                            text: model.name
                            state3: model.state
                            onClicked: page.cycleStatus(index)
                        }
                    }
                }

                Kirigami.Heading {
                    level: 3
                    text: "Tags"
                }
                Controls.TextField {
                    Layout.fillWidth: true
                    placeholderText: "Filter tags (e.g. \"Time Skip\", \"Isekai\")..."
                    onTextChanged: page.applyTagFilterText(text)
                }
            }

            Controls.ScrollView {
                Layout.fillWidth: true
                // A fixed height, not one computed from sibling implicitHeight:
                // that adaptive version measured nonScrollSection too early/
                // unreliably in practice (confirmed live across several
                // attempts -- the Clear/Apply row kept landing outside the
                // visible area regardless of added safety margins). A modest
                // fixed height is exactly what worked before this section
                // grew a Format/My List group -- still bounded and internally
                // scrollable, just not perfectly adaptive to window size.
                Layout.preferredHeight: 280
                Flow {
                    // width: parent.width was circular here -- ScrollView auto-wraps
                    // a non-Flickable child (this Flow) in its own implicit Flickable,
                    // whose contentWidth is itself derived from the Flow's content.
                    // When a tag-filter keystroke shrank the Flow to 1-2 chips, that
                    // Flickable settled at a small contentWidth and didn't reliably
                    // grow back once the Flow repopulated -- same trap as the
                    // DetailPage page-button Flow fixed earlier. Anchoring to the
                    // outer ColumnLayout (a stable, externally-driven width) instead
                    // of parent breaks the loop.
                    width: filterColumn.width
                    spacing: Kirigami.Units.smallSpacing
                    Repeater {
                        model: tagModel
                        delegate: FilterChip {
                            required property int index
                            required property var model
                            text: model.name
                            state3: model.state
                            onClicked: page.cycleTag(index)
                        }
                    }
                }
            }

            RowLayout {
                id: buttonsRow
                Layout.fillWidth: true
                Controls.Button {
                    text: "Clear all"
                    onClicked: {
                        for (let i = 0; i < genreModel.count; i++) genreModel.setProperty(i, "state", 0)
                        for (let i = 0; i < tagModel.count; i++) tagModel.setProperty(i, "state", 0)
                        for (let i = 0; i < statusModel.count; i++) statusModel.setProperty(i, "state", 0)
                        for (let i = 0; i < formatModel.count; i++) formatModel.setProperty(i, "state", 0)
                        page.tagStates = ({})
                    }
                }
                Item { Layout.fillWidth: true }
                Controls.Button {
                    text: "Apply"
                    icon.name: "dialog-ok-apply-symbolic"
                    onClicked: {
                        filterSheet.close()
                        page.doSearch()
                    }
                }
            }
        }
        }
    }

    // A tri-state chip: neutral (outline) -> include (green, check) -> exclude
    // (red, cross) -> back to neutral. Plain Controls.CheckBox only has two
    // states, so this is a small custom button instead.
    component FilterChip: Controls.Button {
        id: chip
        property int state3: 0 // 0 neutral, 1 include, 2 exclude
        Layout.alignment: Qt.AlignVCenter
        background: Rectangle {
            radius: height / 2
            border.width: 1
            border.color: chip.state3 === 1 ? Kirigami.Theme.positiveTextColor
                : chip.state3 === 2 ? Kirigami.Theme.negativeTextColor
                : Kirigami.Theme.disabledTextColor
            color: chip.state3 === 1 ? Qt.rgba(Kirigami.Theme.positiveTextColor.r, Kirigami.Theme.positiveTextColor.g, Kirigami.Theme.positiveTextColor.b, 0.18)
                : chip.state3 === 2 ? Qt.rgba(Kirigami.Theme.negativeTextColor.r, Kirigami.Theme.negativeTextColor.g, Kirigami.Theme.negativeTextColor.b, 0.18)
                : "transparent"
        }
        contentItem: RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Kirigami.Icon {
                visible: chip.state3 !== 0
                source: chip.state3 === 1 ? "dialog-ok-apply-symbolic" : (chip.state3 === 2 ? "dialog-cancel-symbolic" : "")
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: Kirigami.Units.iconSizes.small
                color: chip.state3 === 1 ? Kirigami.Theme.positiveTextColor : Kirigami.Theme.negativeTextColor
            }
            Controls.Label {
                text: chip.text
                color: chip.state3 === 1 ? Kirigami.Theme.positiveTextColor
                    : chip.state3 === 2 ? Kirigami.Theme.negativeTextColor
                    : Kirigami.Theme.textColor
            }
        }
    }

    // GridView (a real Flickable) instead of GridLayout+Repeater: Kirigami.ScrollablePage
    // only makes its content scrollable when that content IS a Flickable, and only
    // instantiating on-screen delegates matters once result counts grow. cellWidth is
    // computed from the page width rather than fixed, so columns always stretch to
    // fill the row exactly instead of leaving a gap on the right.
    GridView {
        id: grid
        readonly property int idealCellWidth: 200
        readonly property int columns: Math.max(1, Math.floor(width / idealCellWidth))
        model: resultsModel
        cellWidth: width / columns
        cellHeight: 300

        onContentYChanged: {
            if (page.hasMore && !page.loadingMore && !page.searching
                && contentY + height > contentHeight - cellHeight * 2) {
                page.loadMore()
            }
        }

        delegate: Item {
            width: grid.cellWidth
            height: grid.cellHeight

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Kirigami.Units.smallSpacing
                spacing: Kirigami.Units.smallSpacing

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 240
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
                        onClicked: {
                            if (model.source === "anilist") {
                                backend.openAnilistAnime(model.anilist_id, model.title)
                            } else {
                                applicationWindow().pageStack.push(
                                    Qt.resolvedUrl("DetailPage.qml"),
                                    {
                                        anime: {
                                            slug_id: model.slug_id,
                                            numeric_id: model.numeric_id,
                                            title: model.title,
                                            poster_url: model.poster_url,
                                            kind: model.kind,
                                            rating: model.rating
                                        }
                                    }
                                )
                            }
                        }
                    }

                    Rectangle {
                        visible: model.source === "anidb" && model.anilistLabel !== ""
                        anchors.top: parent.top
                        anchors.right: parent.right
                        anchors.margins: Kirigami.Units.smallSpacing
                        radius: 3
                        color: Kirigami.Theme.highlightColor
                        width: badgeLabel.implicitWidth + Kirigami.Units.smallSpacing * 2
                        height: badgeLabel.implicitHeight + Kirigami.Units.smallSpacing

                        Controls.Label {
                            id: badgeLabel
                            anchors.centerIn: parent
                            text: model.anilistLabel + (model.anilistProgress > 0 ? " " + model.anilistProgress : "")
                            color: Kirigami.Theme.highlightedTextColor
                            font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                            font.bold: true
                        }
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
                    text: model.kind + (model.rating ? " · ★" + model.rating : "")
                    opacity: 0.7
                }
            }
        }

        footer: Item {
            width: grid.width
            height: (page.hasMore || page.loadingMore) ? loadMoreRow.implicitHeight + Kirigami.Units.largeSpacing * 2 : 0
            visible: page.hasMore || page.loadingMore

            RowLayout {
                id: loadMoreRow
                anchors.centerIn: parent
                Controls.BusyIndicator {
                    running: page.loadingMore
                    visible: page.loadingMore
                }
                Controls.Button {
                    visible: page.hasMore && !page.loadingMore
                    text: "Load more"
                    onClicked: page.loadMore()
                }
            }
        }

        Controls.BusyIndicator {
            anchors.centerIn: parent
            running: page.searching
            visible: page.searching
        }

        Kirigami.PlaceholderMessage {
            anchors.centerIn: parent
            width: parent.width - Kirigami.Units.gridUnit * 4
            visible: !page.searching && grid.count === 0
            text: page.showingRecommendations ? "No recommendations" : "No results yet"
            explanation: page.recommendationsMessage !== "" ? page.recommendationsMessage
                : "Search for an anime, pick some genres/tags above, or clear the search to see recommendations"
            icon.name: "edit-find-symbolic"
        }
    }
}
