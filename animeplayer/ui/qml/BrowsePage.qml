// Browse the streaming source's catalog: pick a ranking (Top Airing, Latest
// Completed, ...) or build a filter, and scroll.
//
// Filters here hit the source's own /filter endpoint rather than AniList's
// catalog, unlike SearchPage's genre/tag filters. The difference matters:
// everything this page lists is by definition present on the source, so a
// click always opens something playable, where an AniList-filtered result
// still has to be matched to the source and can come back "couldn't find a
// stream". AniList-side filtering stays on SearchPage for the things this
// endpoint knows nothing about -- tags, and the user's own list status.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page

    // Set by the caller when arriving from a home row's "See all".
    property string startCategory: "top-airing"
    property string startLabel: ""

    property string category: startCategory   // "" once any filter is set
    property string categoryLabel: startLabel
    property var results: []
    property int resultPage: 1
    property bool hasMore: false
    property bool loading: false
    property bool loadingMore: false
    property string errorMessage: ""
    property bool filtersOpen: false

    // Filter state. Names match the source's own query parameters, so
    // filterSpec() is a straight copy rather than a translation table.
    property string filterType: ""
    property string filterStatus: ""
    property string filterSeason: ""
    property string filterLanguage: ""
    property string filterSort: ""
    property var filterGenres: []
    property var genres: []

    readonly property bool filtered:
        filterType !== "" || filterStatus !== "" || filterSeason !== ""
        || filterLanguage !== "" || filterSort !== "" || filterGenres.length > 0
        || queryField.text.trim() !== ""

    title: filtered ? "Browse" : (categoryLabel || "Browse")

    actions: [
        Kirigami.Action {
            text: page.filtersOpen ? "Hide filters" : "Filters"
            icon.name: "view-filter-symbolic"
            checkable: true
            checked: page.filtersOpen
            onTriggered: page.filtersOpen = !page.filtersOpen
        },
        Kirigami.Action {
            text: "Clear"
            icon.name: "edit-clear-all-symbolic"
            enabled: page.filtered
            onTriggered: page.clearFilters()
        }
    ]

    Component.onCompleted: {
        backend.fetchSourceGenres()
        if (categoryLabel === "") {
            // Arrived without a label (e.g. from the drawer); find the
            // catalog's own name rather than showing its url slug.
            let all = backend.catalogs()
            for (let i = 0; i < all.length; i++) {
                if (all[i].key === page.category) page.categoryLabel = all[i].label
            }
        }
        page.reload()
    }

    Connections {
        target: backend
        function onSourceGenresLoaded(list) { page.genres = list }
        function onBrowseFinished(payload) {
            page.loading = false
            page.loadingMore = false
            page.errorMessage = ""
            page.resultPage = payload.page
            page.hasMore = payload.hasMore
            // Concatenate rather than append into a model: these are plain
            // arrays, for the same reason the home rows are (see HomePage).
            page.results = payload.page <= 1 ? payload.results
                                             : page.results.concat(payload.results)
        }
        function onBrowseFailed(message) {
            page.loading = false
            page.loadingMore = false
            page.errorMessage = message
        }
    }

    function filterSpec() {
        return {
            keyword: queryField.text.trim(),
            type: page.filterType,
            status: page.filterStatus,
            season: page.filterSeason,
            language: page.filterLanguage,
            sort: page.filterSort,
            genres: page.filterGenres
        }
    }

    function load(pageNumber) {
        if (pageNumber <= 1) {
            page.loading = true
            page.results = []
        } else {
            page.loadingMore = true
        }
        // A filter and a ranking are two different endpoints, and the moment
        // any filter is set the ranking stops applying -- so setting one
        // switches the page over rather than trying to combine them.
        if (page.filtered) backend.browseWithFilters(page.filterSpec(), pageNumber)
        else backend.browseCatalog(page.category, pageNumber)
    }

    function reload() { page.load(1) }

    function loadMore() {
        if (!page.hasMore || page.loading || page.loadingMore) return
        page.load(page.resultPage + 1)
    }

    function clearFilters() {
        page.filterType = ""
        page.filterStatus = ""
        page.filterSeason = ""
        page.filterLanguage = ""
        page.filterSort = ""
        page.filterGenres = []
        queryField.text = ""
        page.reload()
    }

    function toggleGenre(slug) {
        // Reassigned, not spliced in place -- see HomePage's note on `var`
        // property notification.
        let next = page.filterGenres.filter((g) => g !== slug)
        if (next.length === page.filterGenres.length) next.push(slug)
        page.filterGenres = next
        page.reload()
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
                placeholderText: "Filter by title..."
                onAccepted: page.reload()
            }

            // The rankings, as a menu rather than a row of chips: there are
            // fourteen of them and they are mutually exclusive.
            Controls.ToolButton {
                text: page.filtered ? "Filtered" : (page.categoryLabel || "Category")
                icon.name: "view-sort-symbolic"
                enabled: !page.filtered
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
                            onTriggered: {
                                page.category = modelData.key
                                page.categoryLabel = modelData.label
                                page.reload()
                            }
                        }
                    }
                }
            }
        }

        // The filter drawer. Collapsed by default: the point of this page is
        // the grid, and six always-visible dropdowns push it below the fold.
        ColumnLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.smallSpacing
            Layout.rightMargin: Kirigami.Units.smallSpacing
            Layout.bottomMargin: Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.smallSpacing
            visible: page.filtersOpen

            Flow {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                FilterCombo {
                    label: "Type"
                    options: [["", "Any type"], ["tv", "TV"], ["movie", "Movie"], ["ova", "OVA"],
                              ["ona", "ONA"], ["special", "Special"], ["music", "Music"]]
                    value: page.filterType
                    onPicked: (v) => { page.filterType = v; page.reload() }
                }
                FilterCombo {
                    label: "Status"
                    options: [["", "Any status"], ["releasing", "Airing"],
                              ["completed", "Finished"], ["not_yet_aired", "Upcoming"]]
                    value: page.filterStatus
                    onPicked: (v) => { page.filterStatus = v; page.reload() }
                }
                FilterCombo {
                    label: "Season"
                    options: [["", "Any season"], ["winter", "Winter"], ["spring", "Spring"],
                              ["summer", "Summer"], ["fall", "Fall"]]
                    value: page.filterSeason
                    onPicked: (v) => { page.filterSeason = v; page.reload() }
                }
                FilterCombo {
                    label: "Audio"
                    options: [["", "Sub or dub"], ["sub", "Subbed"], ["dub", "Dubbed"]]
                    value: page.filterLanguage
                    onPicked: (v) => { page.filterLanguage = v; page.reload() }
                }
                FilterCombo {
                    label: "Sort"
                    options: [["", "Default order"], ["most_viewed", "Most watched"],
                              ["most_followed", "Most followed"], ["trending", "Trending"],
                              ["avg_score", "Score"], ["release_date", "Newest"],
                              ["updated_date", "Recently updated"], ["title_az", "Name A-Z"]]
                    value: page.filterSort
                    onPicked: (v) => { page.filterSort = v; page.reload() }
                }
            }

            // Genres are a long tail: a handful get used constantly and the
            // other eighty are noise until searched for, so the list is capped
            // and grows on demand.
            Flow {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Repeater {
                    model: page.genresShown
                    GenreChip {
                        required property var modelData
                        text: modelData.name
                        selected: page.filterGenres.indexOf(modelData.slug) >= 0
                        onClicked: page.toggleGenre(modelData.slug)
                    }
                }

                Controls.ToolButton {
                    visible: page.genres.length > page.genreLimit
                    text: "+" + (page.genres.length - page.genreLimit) + " more"
                    onClicked: page.genreLimit = page.genres.length
                }
            }
        }

        Kirigami.Separator { Layout.fillWidth: true }
    }

    property int genreLimit: 18
    // Selected genres stay visible even when they fall outside the cap --
    // otherwise collapsing the list silently hides a filter that is still
    // being applied.
    readonly property var genresShown: genres.filter(
        (g, i) => i < genreLimit || filterGenres.indexOf(g.slug) >= 0)

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
                subtitle: [modelData.kind, modelData.duration]
                    .filter((part) => !!part).join(" · ")
                cornerText: modelData.dub_count > 0 ? "SUB · DUB"
                          : (modelData.sub_count > 0 ? "SUB" : "")
                onClicked: applicationWindow().pageStack.push(
                    Qt.resolvedUrl("DetailPage.qml"),
                    {
                        anime: {
                            slug_id: modelData.slug_id,
                            numeric_id: modelData.numeric_id,
                            title: modelData.title,
                            poster_url: modelData.poster_url,
                            kind: modelData.kind,
                            rating: modelData.rating
                        }
                    }
                )
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
            text: page.errorMessage !== "" ? "Couldn't load this" : "Nothing matches"
            explanation: page.errorMessage !== "" ? page.errorMessage
                : "Try clearing a filter or two."
            icon.name: page.errorMessage !== "" ? "network-disconnect-symbolic" : "view-filter-symbolic"
        }
    }

    // A dropdown that shows its own name while unset ("Any type") and the
    // chosen value once set, so a collapsed filter bar still says what is
    // being filtered on.
    component FilterCombo: Controls.ComboBox {
        id: combo
        property string label: ""
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

    component GenreChip: Controls.Button {
        id: chip
        property bool selected: false
        background: Rectangle {
            radius: height / 2
            border.width: 1
            border.color: chip.selected ? Kirigami.Theme.highlightColor
                                        : Kirigami.Theme.disabledTextColor
            color: chip.selected
                ? Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g,
                          Kirigami.Theme.highlightColor.b, 0.2)
                : "transparent"
        }
        contentItem: Controls.Label {
            text: chip.text
            color: chip.selected ? Kirigami.Theme.highlightColor : Kirigami.Theme.textColor
            horizontalAlignment: Text.AlignHCenter
        }
    }
}
