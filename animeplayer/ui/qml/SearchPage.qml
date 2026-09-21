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

    // Exposed as aliases (not just bare ids) since FilterPage.qml -- a
    // separate file, pushed with owner: page -- reads these directly as
    // page.genreModel etc. A plain id declared here is only visible to code
    // inside *this* file; without the alias, FilterPage's Repeaters silently
    // bound to undefined and rendered no chips at all (confirmed live: the
    // header Filters(N) count updated correctly since cycleGenre() etc. are
    // real functions on this page and update the ids just fine internally,
    // but the Repeater delegates FilterPage tried to read them through never
    // showed anything).
    property alias genreModel: genreModel
    property alias tagModel: tagModel
    property alias statusModel: statusModel
    property alias formatModel: formatModel

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
            for (let i = 0; i < results.length; i++) page.appendResult(results[i], "stream")
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
            for (let i = 0; i < payload.results.length; i++) page.appendResult(payload.results[i], "anilist")
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
        function onAnilistAnimeResolveErrored(message) {
            showPassiveNotification("Couldn't reach the streaming source: " + message)
        }
        function onDiscoverFailed(message) {
            showPassiveNotification(message)
        }
    }

    // Every row goes in through here, with every role spelled out, because a
    // QML ListModel fixes its role set from the first row it is given: a later
    // row missing one of those roles leaves it *present but unset*, which
    // reads back as `undefined` and renders as the literal text "undefined".
    // The two producers (the streaming source's search and AniList's catalog)
    // describe an anime differently, so results from whichever one appended
    // second showed an "undefined" badge on every single card.
    function appendResult(r, sourceKind) {
        resultsModel.append({
            slug_id: r.slug_id || "",
            numeric_id: r.numeric_id || "",
            anilist_id: r.anilist_id || 0,
            title: r.title || "",
            poster_url: r.poster_url || "",
            kind: r.kind || "",
            rating: r.rating || "",
            duration: r.duration || "",
            sub_count: r.sub_count || 0,
            dub_count: r.dub_count || 0,
            // Why a recommendation was suggested ("Next season of X"). Empty
            // for anything that isn't a recommendation.
            reason: r.reason || "",
            source: sourceKind,
            // Filled in later by onAnilistStatusesResolved, once that
            // background match finishes.
            anilistLabel: "",
            anilistProgress: 0
        })
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

    // Single place a result row gets opened, so the grid delegate and any
    // other caller (e.g. the phone remote, the live E2E driver) take exactly
    // the same path.
    function openResult(index) {
        let model = resultsModel.get(index)
        if (model.source === "anilist") {
            backend.openAnilistAnime(model.anilist_id, model.title)
            return
        }
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

    // The query lives in the header's text field; this keeps that an
    // implementation detail of the page rather than something callers reach into.
    function setQuery(text) { queryField.text = text }

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
            onClicked: applicationWindow().pageStack.push(Qt.resolvedUrl("FilterPage.qml"), { owner: page })
        }
        Controls.Button {
            text: "Search"
            onClicked: page.doSearch()
        }
        Controls.Button {
            text: "Recommend"
            icon.name: "games-highscores-symbolic"
            // Used to be reachable only by clearing the box and pressing
            // Search, which nothing on screen said.
            onClicked: page.loadRecommendations()
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

    // GridView (a real Flickable) instead of GridLayout+Repeater: Kirigami.ScrollablePage
    // only makes its content scrollable when that content IS a Flickable, and only
    // instantiating on-screen delegates matters once result counts grow. cellWidth is
    // computed from the page width rather than fixed, so columns always stretch to
    // fill the row exactly instead of leaving a gap on the right.
    GridView {
        id: grid
        // Same measure Home's rows use, so a card is the same size whichever
        // page you're looking at.
        readonly property int idealCellWidth: Kirigami.Units.gridUnit * 11
        readonly property int columns: Math.max(1, Math.floor(width / idealCellWidth))
        model: resultsModel
        cellWidth: width / columns
        // Derived from the card's own geometry (2:3 poster + a two-line title
        // block) rather than a fixed number, which clipped the subtitle at
        // some window widths and left a gap at others.
        cellHeight: Math.round((cellWidth - Kirigami.Units.smallSpacing * 2) * 1.5)
                    + Kirigami.Units.gridUnit * 4

        onContentYChanged: {
            if (page.hasMore && !page.loadingMore && !page.searching
                && contentY + height > contentHeight - cellHeight * 2) {
                page.loadMore()
            }
        }

        delegate: Item {
            width: grid.cellWidth
            height: grid.cellHeight

            AnimeCard {
                anchors.fill: parent
                anchors.margins: Kirigami.Units.smallSpacing
                posterUrl: model.poster_url
                title: model.title
                // A recommendation says why it's being recommended; anything
                // else falls back to describing itself. (The source's own
                // cards carry no score, so that line is the format plus its
                // runtime rather than an always-empty "· ★".)
                subtitle: model.reason !== ""
                    ? model.reason
                    : [model.kind, model.duration, model.rating ? "\u2605 " + model.rating : ""]
                        .filter((part) => !!part).join(" · ")
                badgeText: model.anilistLabel !== ""
                    ? model.anilistLabel + (model.anilistProgress > 0 ? " " + model.anilistProgress : "")
                    : ""
                cornerText: model.dub_count > 0 ? "SUB · DUB" : (model.sub_count > 0 ? "SUB" : "")
                onClicked: page.openResult(index)
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
                : "Search for an anime, pick some genres/tags above, or hit Recommend for something new"
            icon.name: "edit-find-symbolic"
        }
    }
}
