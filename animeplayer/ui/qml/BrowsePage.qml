// The one page for finding something to watch: ranked catalogs, a title
// search, filters, and recommendations.
//
// It used to be two pages. Search filtered AniList's catalog (genres, tags,
// include/exclude) and Browse filtered the streaming source's (fast, and
// everything it lists is definitely playable). Keeping both meant the same
// question had two answers depending on which page you were on, so they are
// one page with two engines behind it:
//
//   * no filters  -> the source's own ranked catalogs (Top Airing, Most
//                    Popular, ...), and a keyword search against the source,
//                    where every hit is playable and it is one request.
//   * any filter  -> AniList's catalog, because only it can exclude as well
//                    as include, and only it knows tags, country of origin
//                    and scores. A result is matched to the source on click.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page

    AppTheming {}

    // Set by the caller when arriving from a home row's "See all".
    property string startCategory: "top-airing"
    property string startLabel: ""
    // Set by Home's "Planning to Watch" row.
    property string startListStatus: ""
    // Set by Home's "Recommend Me".
    property bool startWithRecommendations: false
    // Set by Home's genre strip.
    property string startGenre: ""

    // The last preset clicked, purely so the picker can say what it was. The
    // preset itself only *sets* filters -- the controls stay the truth, so a
    // preset and a filter can never disagree about what is being asked for.
    property string presetLabel: startLabel
    property var results: []
    property int resultPage: 1
    property bool hasMore: false
    property bool loading: false
    property bool loadingMore: false
    property string errorMessage: ""
    property bool filtersOpen: false
    property bool showingRecommendations: false

    // Single-choice filters. Season, year and sort are single by nature --
    // there is no "not autumn" worth having, and an order is an order.
    property string filterSeason: ""
    property string filterYear: ""
    property string filterSort: ""
    property int filterMinScore: 0

    // name -> 1 (include) or 2 (exclude). Plain objects, reassigned rather
    // than mutated: QML only notifies on assignment for `var` properties.
    property var genreStates: ({})
    property var tagStates: ({})
    property var listStates: ({})
    // Format, airing status and origin are tri-state too: "any format except
    // Music" and "not Chinese" are the way people actually think about these.
    property var formatStates: ({})
    property var airingStates: ({})
    property var countryStates: ({})
    property var genres: []
    property var allTags: []
    property var shownTags: []

    readonly property int filterCount:
        Object.keys(genreStates).length + Object.keys(tagStates).length
        + Object.keys(listStates).length + Object.keys(formatStates).length
        + Object.keys(airingStates).length + Object.keys(countryStates).length
        + (filterSeason !== "" ? 1 : 0) + (filterYear !== "" ? 1 : 0)
        + (filterSort !== "" ? 1 : 0) + (filterMinScore > 0 ? 1 : 0)

    readonly property bool filtered: filterCount > 0

    title: showingRecommendations ? "Recommended for you"
         : (presetLabel || "Browse")

    actions: [
        Kirigami.Action {
            text: page.filtersOpen ? "Hide filters"
                                   : (page.filterCount > 0 ? "Filters (" + page.filterCount + ")"
                                                           : "Filters")
            icon.name: "view-filter-symbolic"
            onTriggered: page.filtersOpen = !page.filtersOpen
        },
        Kirigami.Action {
            text: "Recommend"
            icon.name: "games-highscores-symbolic"
            tooltip: "Shows picked from what you've already watched"
            onTriggered: page.loadRecommendations()
        },
        Kirigami.Action {
            text: "Clear"
            icon.name: "edit-clear-all-symbolic"
            enabled: page.filtered || page.showingRecommendations
                     || queryField.text.trim() !== ""
            onTriggered: page.clearFilters()
        }
    ]

    Component.onCompleted: {
        backend.fetchAnilistGenres()
        backend.fetchAnilistTags()
        if (page.startWithRecommendations) {
            page.loadRecommendations()
        } else {
            if (page.startGenre !== "") {
                page.genreStates = { [page.startGenre]: 1 }
                page.filtersOpen = true
            }
            if (page.startListStatus !== "") {
                page.listStates = { [page.startListStatus]: 1 }
                page.filtersOpen = true
            }
            page.applyPreset(page.startCategory)
        }
    }

    Connections {
        target: backend
        function onAnilistGenresLoaded(list) { page.genres = list }
        function onAnilistTagsLoaded(list) {
            page.allTags = list
            page.applyTagFilterText(tagField.text)
        }
        function onBrowseFinished(payload) {
            page.loading = false
            page.loadingMore = false
            page.errorMessage = ""
            page.resultPage = payload.page
            page.hasMore = payload.hasMore
            page.showingRecommendations = payload.key === "recommendations"
            // Concatenated rather than appended into a model: these are plain
            // arrays, for the same reason the home rows are (see HomePage).
            page.results = payload.page <= 1 ? payload.results
                                             : page.results.concat(payload.results)
        }
        function onBrowseFailed(message) {
            page.loading = false
            page.loadingMore = false
            page.errorMessage = message
        }
        function onRecommendationsFailed(message) {
            page.loading = false
            page.results = []
            page.errorMessage = message
        }
        function onSearchFinished(list) {
            page.loading = false
            page.errorMessage = ""
            page.hasMore = false
            page.results = list
        }
        function onSearchFailed(message) {
            page.loading = false
            page.errorMessage = message
        }
        function onAnilistAnimeResolved(result) { page.openEntry(result) }
        function onAnilistAnimeResolveFailed(title) {
            showPassiveNotification("Couldn't find a stream for \"" + title + "\"")
        }
        function onAnilistAnimeResolveErrored(message) {
            showPassiveNotification("Couldn't reach the streaming source: " + message)
        }
    }

    function tristate(states, name) {
        let next = ((states[name] || 0) + 1) % 3
        let updated = Object.assign({}, states)
        if (next === 0) delete updated[name]
        else updated[name] = next
        return updated
    }

    function pick(states, wanted) {
        return Object.keys(states).filter((name) => states[name] === wanted)
    }

    function filterSpec() {
        return {
            keyword: queryField.text.trim(),
            genres: page.pick(page.genreStates, 1),
            excludeGenres: page.pick(page.genreStates, 2),
            tags: page.pick(page.tagStates, 1),
            excludeTags: page.pick(page.tagStates, 2),
            statusInclude: page.pick(page.listStates, 1),
            statusExclude: page.pick(page.listStates, 2),
            formats: page.pick(page.formatStates, 1),
            excludeFormats: page.pick(page.formatStates, 2),
            airingStatus: page.pick(page.airingStates, 1),
            excludeAiringStatus: page.pick(page.airingStates, 2),
            // AniList takes one country at a time, so only the first included
            // one is sent; exclusions are applied to the results (see the
            // backend). Two required countries at once is not a real request.
            country: page.pick(page.countryStates, 1)[0] || "",
            excludeCountries: page.pick(page.countryStates, 2),
            minScore: page.filterMinScore,
            season: page.filterSeason,
            seasonYear: page.filterYear === "" ? 0 : parseInt(page.filterYear),
            sort: page.filterSort
        }
    }

    function load(pageNumber) {
        if (pageNumber <= 1) {
            page.loading = true
            page.results = []
            page.showingRecommendations = false
        } else {
            page.loadingMore = true
        }
        // A bare title search goes to the source: every hit is playable, and
        // it is one request rather than a search plus a match. Anything with a
        // filter on it goes to AniList, which is the only side that can
        // exclude, and knows tags, origin and scores.
        if (!page.filtered && queryField.text.trim() !== "") {
            backend.search(queryField.text.trim())
        } else {
            backend.searchByFilters(page.filterSpec(), pageNumber)
        }
    }

    // Every filter control calls this rather than load(1) directly. Changing
    // three filters in a row is three clicks in about as many hundred
    // milliseconds, and firing a request per click means three page loads of
    // which only the last matters.
    function reload() { reloadDebounce.restart() }

    Timer {
        id: reloadDebounce
        interval: 250
        onTriggered: page.load(1)
    }

    function loadMore() {
        if (!page.hasMore || page.loading || page.loadingMore) return
        page.load(page.resultPage + 1)
    }

    function loadRecommendations() {
        page.loading = true
        page.results = []
        page.errorMessage = ""
        page.hasMore = false
        page.showingRecommendations = true
        backend.loadRecommendations()
    }

    // A preset is a shortcut that fills the controls in, not a separate mode.
    // Selecting one used to switch the page onto the source's own catalog,
    // which silently ignored every other filter -- so "Top Airing" plus
    // "Movies" plus "China" quietly answered only the first of the three.
    function applyPreset(key) {
        let all = backend.catalogs()
        let preset = null
        for (let i = 0; i < all.length; i++) if (all[i].key === key) preset = all[i]
        if (preset === null) { page.load(1); return }

        page.presetLabel = preset.label
        page.filterSort = preset.sort || ""
        if (preset.airing) page.airingStates = { [preset.airing]: 1 }
        if (preset.format) page.formatStates = { [preset.format]: 1 }
        page.load(1)
    }

    function clearFilters() {
        page.filterSeason = ""
        page.filterYear = ""
        page.filterSort = ""
        page.filterMinScore = 0
        page.genreStates = ({})
        page.tagStates = ({})
        page.listStates = ({})
        page.formatStates = ({})
        page.airingStates = ({})
        page.countryStates = ({})
        page.presetLabel = ""
        page.showingRecommendations = false
        queryField.text = ""
        page.load(1)
    }

    function applyTagFilterText(text) {
        let needle = (text || "").toLowerCase()
        let shown = []
        for (let i = 0; i < page.allTags.length && shown.length < 60; i++) {
            if (needle === "" || page.allTags[i].toLowerCase().includes(needle)) {
                shown.push(page.allTags[i])
            }
        }
        // Selected tags stay visible even when they fall outside the list --
        // otherwise retyping the search silently hides a filter still applied.
        for (let name in page.tagStates) {
            if (shown.indexOf(name) < 0) shown.push(name)
        }
        page.shownTags = shown
    }

    function openEntry(entry) {
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

    // The query lives in the header's text field; this keeps that an
    // implementation detail of the page rather than something callers reach
    // into (the live E2E driver types through it).
    function setQuery(text) { queryField.text = text }

    function openResult(index) {
        let entry = page.results[index]
        // An AniList-sourced result carries no source slug, so it has to be
        // matched to the source first; a source result opens straight away.
        if (!entry.slug_id) backend.openAnilistAnime(entry.anilist_id, entry.title)
        else page.openEntry(entry)
    }

    readonly property var yearOptions: {
        let years = [["", "Any year"]]
        let newest = new Date().getFullYear() + 1
        for (let y = newest; y >= 1960; y--) years.push([String(y), String(y)])
        return years
    }

    header: ColumnLayout {
        width: page.width
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.smallSpacing

            Controls.TextField {
                id: queryField
                Layout.fillWidth: true
                placeholderText: "Search anime..."
                onAccepted: page.load(1)
            }

            // The rankings, as a menu rather than a row of chips: there are
            // fourteen of them and they are mutually exclusive.
            AppButton {
                text: page.presetLabel || "Quick picks"
                icon.name: "view-sort-symbolic"
                onClicked: catalogMenu.popup()

                Controls.Menu {
                    id: catalogMenu
                    Instantiator {
                        model: backend.catalogs()
                        onObjectAdded: (index, object) => catalogMenu.insertItem(index, object)
                        onObjectRemoved: (index, object) => catalogMenu.removeItem(object)
                        delegate: Controls.MenuItem {
                            required property var modelData
                            text: modelData.label
                            onTriggered: page.applyPreset(modelData.key)
                        }
                    }
                }
            }
        }

        // The filter drawer. Collapsed by default: the point of this page is
        // the grid, and the whole panel would otherwise push it below the fold.
        ColumnLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.smallSpacing
            Layout.rightMargin: Kirigami.Units.smallSpacing
            Layout.bottomMargin: Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.smallSpacing
            visible: page.filtersOpen

            Controls.Label {
                Layout.fillWidth: true
                text: "Click a chip once to require it, twice to exclude it, three times to clear it."
                opacity: 0.7
                wrapMode: Text.WordWrap
                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
            }

            Flow {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                FilterCombo {
                    options: [["", "Any season"], ["WINTER", "Winter"], ["SPRING", "Spring"],
                              ["SUMMER", "Summer"], ["FALL", "Fall"]]
                    value: page.filterSeason
                    onPicked: (v) => { page.filterSeason = v; page.reload() }
                }
                FilterCombo {
                    options: page.yearOptions
                    value: page.filterYear
                    onPicked: (v) => { page.filterYear = v; page.reload() }
                }
                FilterCombo {
                    options: [["", "Any order"], ["POPULARITY_DESC", "Most popular"],
                              ["SCORE_DESC", "Highest scored"], ["TRENDING_DESC", "Trending"],
                              ["FAVOURITES_DESC", "Most favourited"],
                              ["START_DATE_DESC", "Newest"], ["END_DATE_DESC", "Recently ended"],
                              ["UPDATED_AT_DESC", "Recently updated"], ["TITLE_ROMAJI", "Name A-Z"]]
                    value: page.filterSort
                    onPicked: (v) => { page.filterSort = v; page.reload() }
                }
            }

            // The star rating, as stars rather than a dropdown of numbers --
            // it is the one filter people think of in stars.
            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Controls.Label {
                    text: "Minimum rating"
                    opacity: 0.7
                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                }

                Repeater {
                    model: 10
                    Kirigami.Icon {
                        required property int index
                        readonly property int score: (index + 1) * 10
                        readonly property bool lit: page.filterMinScore >= score
                        source: lit ? "star-shape-symbolic" : "star-shape-outline-symbolic"
                        isMask: true
                        color: lit ? Kirigami.Theme.neutralTextColor
                                   : Kirigami.Theme.disabledTextColor
                        implicitWidth: Kirigami.Units.iconSizes.small
                        implicitHeight: implicitWidth

                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        TapHandler {
                            // Clicking the star already set clears the filter,
                            // so there is a way back to "any rating" without a
                            // separate reset control.
                            onTapped: {
                                page.filterMinScore = page.filterMinScore === score ? 0 : score
                                page.reload()
                            }
                        }
                    }
                }

                Controls.Label {
                    text: page.filterMinScore > 0 ? page.filterMinScore + "%+" : "any"
                    opacity: 0.7
                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                }

                Item { Layout.fillWidth: true }
            }

            ChipSection {
                label: "Format"
                names: ["TV", "TV Short", "Movie", "Special", "OVA", "ONA", "Music"]
                keys: ["TV", "TV_SHORT", "MOVIE", "SPECIAL", "OVA", "ONA", "MUSIC"]
                states: page.formatStates
                onToggled: (key) => { page.formatStates = page.tristate(page.formatStates, key); page.reload() }
            }

            ChipSection {
                label: "Airing"
                names: ["Airing", "Finished", "Upcoming"]
                keys: ["RELEASING", "FINISHED", "NOT_YET_RELEASED"]
                states: page.airingStates
                onToggled: (key) => { page.airingStates = page.tristate(page.airingStates, key); page.reload() }
            }

            ChipSection {
                label: "Origin"
                names: ["Japan", "China", "Korea", "Taiwan"]
                keys: ["JP", "CN", "KR", "TW"]
                states: page.countryStates
                onToggled: (key) => { page.countryStates = page.tristate(page.countryStates, key); page.reload() }
            }

            ChipSection {
                label: "My list"
                names: ["Watching", "Planning", "Completed", "Dropped", "Paused",
                        "Rewatching", "Not in my list"]
                keys: ["CURRENT", "PLANNING", "COMPLETED", "DROPPED", "PAUSED",
                       "REPEATING", "NOT_IN_LIST"]
                states: page.listStates
                onToggled: (key) => { page.listStates = page.tristate(page.listStates, key); page.reload() }
            }

            ChipSection {
                label: "Genres"
                names: page.genres
                keys: page.genres
                states: page.genreStates
                onToggled: (key) => { page.genreStates = page.tristate(page.genreStates, key); page.reload() }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing
                Controls.Label {
                    text: "Tags"
                    opacity: 0.7
                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                }
                Controls.TextField {
                    id: tagField
                    Layout.fillWidth: true
                    placeholderText: "Find a tag, e.g. \"Time Skip\" or \"Isekai\"..."
                    onTextChanged: page.applyTagFilterText(text)
                }
            }

            ChipSection {
                names: page.shownTags
                keys: page.shownTags
                states: page.tagStates
                collapsible: true
                onToggled: (key) => { page.tagStates = page.tristate(page.tagStates, key); page.reload() }
            }
        }

        Kirigami.Separator { Layout.fillWidth: true }
    }

    GridView {
        id: grid
        // Same measure the home shelves use, so a card is the same size
        // whichever page you're looking at.
        readonly property int idealCellWidth: Kirigami.Units.gridUnit * 11
        readonly property int columns: Math.max(1, Math.floor(width / idealCellWidth))
        model: page.results
        cellWidth: width / columns
        cellHeight: Math.round((cellWidth - Kirigami.Units.smallSpacing * 2) * 1.5)
                    + Kirigami.Units.gridUnit * 4
        clip: true
        reuseItems: true

        onContentYChanged: {
            if (contentY + height > contentHeight - cellHeight * 2) page.loadMore()
        }

        delegate: Item {
            required property var modelData
            required property int index

            width: grid.cellWidth
            height: grid.cellHeight

            AnimeCard {
                anchors.fill: parent
                anchors.margins: Kirigami.Units.smallSpacing
                posterUrl: modelData.poster_url
                title: modelData.title
                // A recommendation says why it's here; anything else describes
                // itself.
                subtitle: modelData.reason !== "" ? modelData.reason
                    : [modelData.kind, modelData.duration].filter((part) => !!part).join(" · ")
                scoreText: modelData.rating
                cornerText: modelData.dub_count > 0 ? "SUB · DUB"
                          : (modelData.sub_count > 0 ? "SUB" : "")
                onClicked: page.openResult(index)
            }
        }

        // Fixed height, with only the indicator appearing and disappearing.
        // A footer whose *height* tracked loadingMore made Qt report a
        // binding loop on height (confirmed live), and it doubles as the
        // bottom margin the grid would otherwise want anyway.
        footer: Item {
            width: grid.width
            height: Kirigami.Units.gridUnit * 4
            Controls.BusyIndicator {
                anchors.centerIn: parent
                running: page.loadingMore
                visible: page.loadingMore
            }
        }

        Controls.BusyIndicator {
            anchors.centerIn: parent
            running: page.loading
            visible: page.loading
        }

        Kirigami.PlaceholderMessage {
            anchors.centerIn: parent
            width: parent.width - Kirigami.Units.gridUnit * 4
            visible: !page.loading && grid.count === 0
            text: page.errorMessage !== "" ? "Nothing to show" : "Nothing matches"
            explanation: page.errorMessage !== "" ? page.errorMessage
                : "Try clearing a filter or two."
            icon.name: page.errorMessage !== "" ? "network-disconnect-symbolic"
                                                : "view-filter-symbolic"
        }
    }

    // A dropdown that shows its own name while unset ("Any format") and the
    // chosen value once set, so a collapsed filter bar still says what is
    // being filtered on.
    component FilterCombo: Controls.ComboBox {
        id: combo
        property var options: []
        property string value: ""
        signal picked(string value)

        textRole: "text"
        valueRole: "key"
        model: options.map((pair) => ({ key: pair[0], text: pair[1] }))
        currentIndex: Math.max(0, options.findIndex((pair) => pair[0] === combo.value))
        // The signal, not onCurrentIndexChanged: the index also changes when
        // the page assigns `value` back, and handling that fires a reload for
        // a filter nobody touched.
        onActivated: (index) => combo.picked(combo.options[index][0])
    }

    // A labelled run of tri-state chips, optionally capped until expanded.
    // AniList's nineteen genres all fit; its tags run to several hundred.
    component ChipSection: ColumnLayout {
        id: section
        property string label: ""
        property var names: []
        property var keys: []
        property var states: ({})
        property bool collapsible: false
        property int limit: 20
        signal toggled(string key)

        readonly property bool expanded: !collapsible || limit >= names.length
        // A selected chip stays visible past the cap: collapsing the list must
        // not hide a filter that is still being applied.
        readonly property var visibleIndexes: {
            let out = []
            for (let i = 0; i < names.length; i++) {
                if (i < limit || states[keys[i]] !== undefined) out.push(i)
            }
            return out
        }

        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing
        visible: names.length > 0

        Controls.Label {
            text: section.label
            visible: section.label !== ""
            opacity: 0.7
            font.pixelSize: Kirigami.Theme.smallFont.pixelSize
        }

        Flow {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            Repeater {
                model: section.visibleIndexes
                TriStateChip {
                    required property var modelData
                    text: section.names[modelData]
                    state3: section.states[section.keys[modelData]] || 0
                    onClicked: section.toggled(section.keys[modelData])
                }
            }

            Controls.ToolButton {
                visible: section.collapsible && section.names.length > 20
                text: section.expanded ? "Show fewer"
                                       : "+" + (section.names.length - section.limit) + " more"
                icon.name: section.expanded ? "go-up-symbolic" : "go-down-symbolic"
                onClicked: section.limit = section.expanded ? 20 : section.names.length
            }
        }
    }

    // Neutral -> include (green, tick) -> exclude (red, cross) -> neutral.
    // A plain CheckBox only has two states, so this is a small custom button.
    component TriStateChip: Controls.Button {
        id: chip
        property int state3: 0

        readonly property color tint: state3 === 1 ? Kirigami.Theme.positiveTextColor
                                    : state3 === 2 ? Kirigami.Theme.negativeTextColor
                                    : Kirigami.Theme.textColor

        hoverEnabled: true
        leftPadding: Kirigami.Units.smallSpacing * 2
        rightPadding: Kirigami.Units.smallSpacing * 2

        background: Rectangle {
            radius: height / 2
            border.width: 1
            border.color: chip.state3 === 0
                ? (chip.hovered ? Kirigami.Theme.highlightColor : Kirigami.Theme.disabledTextColor)
                : chip.tint
            color: chip.state3 === 0
                ? (chip.hovered
                   ? Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g,
                             Kirigami.Theme.highlightColor.b, 0.12)
                   : "transparent")
                : Qt.rgba(chip.tint.r, chip.tint.g, chip.tint.b, 0.18)
        }

        contentItem: Row {
            spacing: Kirigami.Units.smallSpacing
            Kirigami.Icon {
                anchors.verticalCenter: parent.verticalCenter
                visible: chip.state3 !== 0
                source: chip.state3 === 1 ? "dialog-ok-apply-symbolic" : "dialog-cancel-symbolic"
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: Kirigami.Units.iconSizes.small
                isMask: true
                color: chip.tint
            }
            Controls.Label {
                anchors.verticalCenter: parent.verticalCenter
                text: chip.text
                color: chip.tint
            }
        }
    }
}
