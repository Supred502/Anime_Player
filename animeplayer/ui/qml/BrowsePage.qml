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
    // Filled in once on load -- see the Instantiator below for why this is
    // not a binding.
    property var catalogPresets: []
    // The user's own saved filter sets: [{name, state}].
    property var userPresets: []
    // Listings built from this machine (Continue Watching, Downloaded) rather
    // than from a catalog. Non-empty means one of them is showing, and the
    // filter controls are put away while it is: "what I have on disk" is not
    // something AniList can be asked to narrow.
    property string localKey: ""
    property var localCatalogs: []
    property var genres: []
    property var allTags: []
    property var shownTags: []
    // What the tag search box holds, and which first letter is open when it
    // is empty ("" none, "*" every tag).
    property string tagQuery: ""
    property string tagLetter: ""
    // AniList's own one-line explanation of each tag, for hover text: many
    // of them (Iyashikei, Inseki, Henshin) mean nothing to most people.
    property var tagDescriptions: ({})

    // How many tags are required / excluded, for the strip's two views that
    // list just those.
    readonly property int includedTagCount: Object.keys(tagStates).filter((k) => tagStates[k] === 1).length
    readonly property int excludedTagCount: Object.keys(tagStates).filter((k) => tagStates[k] === 2).length
    // A new list (another letter, another search) starts capped again.
    // A tag chosen, or cleared, from outside the letter or search on show
    // must still join the list -- it's what the section's count reads.
    onTagStatesChanged: {
        // Cleared the last one while looking at just those: back to nothing
        // open, not an empty view with its button gone.
        if ((page.tagLetter === "+" && page.includedTagCount === 0)
                || (page.tagLetter === "-" && page.excludedTagCount === 0)) {
            page.tagLetter = ""
        }
        page.refreshShownTags()
    }
    onTagLetterChanged: { tagSection.limit = tagSection.baseLimit; page.refreshShownTags() }

    // "A" -> 24 and so on, for the alphabet strip. Digits share one "#".
    readonly property var tagLetters: {
        let counts = {}
        for (let i = 0; i < allTags.length; i++) {
            let letter = page.tagBucket(allTags[i])
            counts[letter] = (counts[letter] || 0) + 1
        }
        return Object.keys(counts).sort().map((letter) => ({ letter: letter, count: counts[letter] }))
    }

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
            visible: page.localKey === ""
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

    // Everything worth putting back when this page is opened again. Saved on
    // every change and restored on open, so Browse comes back where it was
    // left rather than resetting to Top Airing each time.
    function browseState() {
        return {
            localKey: page.localKey,
            presetLabel: page.presetLabel,
            keyword: queryField.text,
            season: page.filterSeason,
            year: page.filterYear,
            sort: page.filterSort,
            minScore: page.filterMinScore,
            genreStates: page.genreStates,
            tagStates: page.tagStates,
            listStates: page.listStates,
            formatStates: page.formatStates,
            airingStates: page.airingStates,
            countryStates: page.countryStates,
            filtersOpen: page.filtersOpen
        }
    }

    function restoreBrowseState(saved) {
        // A state saved on Continue Watching or Downloaded (see the preset
        // menu) is from before those moved out of Browse: start fresh.
        if (saved.localKey) { page.applyPreset("top-airing"); return }
        page.localKey = ""
        page.presetLabel = saved.presetLabel || ""
        queryField.text = saved.keyword || ""
        page.filterSeason = saved.season || ""
        page.filterYear = saved.year || ""
        page.filterSort = saved.sort || ""
        page.filterMinScore = saved.minScore || 0
        page.genreStates = saved.genreStates || ({})
        page.tagStates = saved.tagStates || ({})
        page.listStates = saved.listStates || ({})
        page.formatStates = saved.formatStates || ({})
        page.airingStates = saved.airingStates || ({})
        page.countryStates = saved.countryStates || ({})
        page.filtersOpen = !!saved.filtersOpen
        page.load(1)
    }

    // Saved from load() rather than from each control, so there is one place
    // that knows the page's state has settled -- and it is debounced there
    // already, so this is not a database write per keystroke.
    function rememberState() {
        // A page opened *at* something specific (a genre from Home, a
        // "See all") is a one-off destination, not the user's own working
        // set, so it doesn't overwrite what they had.
        if (page.openedAtTarget || page.showingRecommendations) return
        backend.saveBrowseState(page.browseState())
    }

    // True when this page was opened pointing at something particular.
    // Not "transient": that is a reserved QML keyword, and using it makes the
    // whole page fail to load with "Reserved keyword cannot be used as a QML
    // identifier".
    // The Continue nav entry opens this page at a category with no label,
    // which this used to miss -- so visiting Continue saved "Continue
    // Watching" as the Browse state, and Browse opened on it afterwards.
    readonly property bool openedAtTarget: page.startGenre !== ""
        || page.startListStatus !== "" || page.startWithRecommendations
        || page.startLabel !== "" || page.startCategory !== "top-airing"

    Component.onCompleted: {
        page.catalogPresets = backend.catalogs()
        page.userPresets = backend.filterPresets()
        page.localCatalogs = backend.localCatalogs()
        backend.fetchAnilistGenres()
        backend.fetchAnilistTags()
        backend.fetchTagDescriptions()
        if (page.startWithRecommendations) {
            page.loadRecommendations()
        } else if (page.startGenre !== "") {
            page.genreStates = { [page.startGenre]: 1 }
            page.filtersOpen = true
            page.applyPreset(page.startCategory)
        } else if (page.startListStatus !== "") {
            page.listStates = { [page.startListStatus]: 1 }
            page.filtersOpen = true
            page.applyPreset(page.startCategory)
        } else if (page.startLabel !== "" || page.startCategory !== "top-airing") {
            // Arrived from a "See all" or the Continue nav entry: that names
            // the listing to show, so it wins over what was saved.
            page.applyPreset(page.startCategory)
        } else {
            let saved = backend.browseState()
            if (saved && Object.keys(saved).length > 0) page.restoreBrowseState(saved)
            else page.applyPreset(page.startCategory)
        }
    }

    Connections {
        target: backend
        // Every query asks AniList for isAdult: false, and the streaming
        // source carries no adult titles either -- so the Hentai genre can
        // only ever come back empty. Offering it just looks broken.
        function onAnilistGenresLoaded(list) { page.genres = list.filter((name) => name !== "Hentai") }
        function onTagDescriptionsLoaded(map) { page.tagDescriptions = map }
        function onAnilistTagsLoaded(list) {
            page.allTags = list
            page.refreshShownTags()
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
        if (page.localKey !== "") {
            backend.browseLocal(page.localKey)
        } else if (!page.filtered && queryField.text.trim() !== "") {
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
        onTriggered: { page.load(1); page.rememberState() }
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
        // A local listing replaces the filters rather than composing with
        // them, so switching to one clears whatever was set.
        for (let i = 0; i < page.localCatalogs.length; i++) {
            if (page.localCatalogs[i].key === key) {
                page.clearFilters(true)
                page.localKey = key
                page.presetLabel = page.localCatalogs[i].label
                page.load(1)
                page.rememberState()
                return
            }
        }

        let all = page.catalogPresets
        let preset = null
        for (let i = 0; i < all.length; i++) if (all[i].key === key) preset = all[i]
        if (preset === null) { page.load(1); return }

        page.localKey = ""
        page.presetLabel = preset.label
        page.filterSort = preset.sort || ""
        if (preset.airing) page.airingStates = { [preset.airing]: 1 }
        if (preset.format) page.formatStates = { [preset.format]: 1 }
        page.load(1)
        page.rememberState()
    }

    function applyUserPreset(preset) {
        let state = Object.assign({}, preset.state)
        state.presetLabel = preset.name
        state.filtersOpen = page.filtersOpen
        page.restoreBrowseState(state)
        page.rememberState()
    }

    function saveUserPreset(name) {
        let state = page.browseState()
        // What the preset is called goes on the button once it's applied;
        // the label that happened to be showing when it was saved does not.
        delete state.presetLabel
        delete state.filtersOpen
        backend.saveFilterPreset(name, state)
        page.userPresets = backend.filterPresets()
        page.presetLabel = name.trim()
        page.rememberState()
    }

    function clearFilters(skipReload) {
        page.localKey = ""
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
        // skipReload is for callers that are about to load something else
        // themselves -- without it, switching to a local listing fires a
        // catalog request first and the two race.
        if (skipReload !== true) {
            page.load(1)
            backend.clearBrowseState()
        }
    }

    // Edits between two words, counting two swapped neighbours ("isekia")
    // as one slip rather than two.
    function editDistance(a, b) {
        if (Math.abs(a.length - b.length) > 2) return 99
        let before = []
        let prev = []
        for (let j = 0; j <= b.length; j++) prev.push(j)
        for (let i = 1; i <= a.length; i++) {
            let row = [i]
            for (let j = 1; j <= b.length; j++) {
                let cost = a[i - 1] === b[j - 1] ? 0 : 1
                let best = Math.min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + cost)
                if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
                    best = Math.min(best, before[j - 2] + 1)
                }
                row.push(best)
            }
            before = prev
            prev = row
        }
        return prev[b.length]
    }

    function tagBucket(name) {
        let first = name.charAt(0).toUpperCase()
        return first >= "A" && first <= "Z" ? first : "#"
    }

    function applyTagFilterText(text) {
        page.tagQuery = text || ""
        tagSection.limit = tagSection.baseLimit
        page.refreshShownTags()
    }

    // How far a tag is from what was typed, or -1 if too far to offer.
    // Each word is compared whole and by its opening letters, so a search
    // still being typed ("here", on the way to "harem") already finds it.
    // `strict` (real matches were found) allows one slip rather than two, so
    // typo guesses don't bury them.
    function tagTypoRank(tag, needle, strict) {
        let allowed = needle.length >= 5 && !strict ? 2 : 1
        let name = tag.toLowerCase()
        let best = 99
        let whole = (text) => {
            let d = page.editDistance(text, needle)
            if (d <= allowed) best = Math.min(best, d * 10 + Math.abs(text.length - needle.length))
        }
        whole(name)
        for (let word of name.split(/[\s-]+/)) {
            whole(word)
            // Half a word can't be judged as loosely as a whole one.
            if (word.length > needle.length
                    && page.editDistance(word.substring(0, needle.length), needle) <= 1) {
                best = Math.min(best, 11)
            }
        }
        return best < 99 ? best : -1
    }

    function refreshShownTags() {
        let needle = page.tagQuery.trim().toLowerCase()
        let shown = []
        if (needle === "") {
            shown = page.tagLetter === "*" ? page.allTags.slice()
                  : page.tagLetter === "+" ? Object.keys(page.tagStates).filter((k) => page.tagStates[k] === 1).sort()
                  : page.tagLetter === "-" ? Object.keys(page.tagStates).filter((k) => page.tagStates[k] === 2).sort()
                  : page.allTags.filter((tag) => page.tagBucket(tag) === page.tagLetter)
        } else {
            // Anywhere in the name counts ("matic" finds Achromatic), but a
            // tag with a word starting that way is the likelier target.
            let starts = [], inside = []
            for (let tag of page.allTags) {
                let name = tag.toLowerCase()
                if (!name.includes(needle)) continue
                let atWord = name.startsWith(needle) || name.split(/[\s-]+/).some((w) => w.startsWith(needle))
                ;(atWord ? starts : inside).push(tag)
            }
            shown = starts.concat(inside)
            // Then near-misses for typos ("heram"), after the real matches.
            if (needle.length >= 4) {
                let exact = shown.length
                let near = []
                for (let tag of page.allTags) {
                    if (shown.indexOf(tag) >= 0) continue
                    let rank = page.tagTypoRank(tag, needle, exact > 0)
                    if (rank >= 0) near.push({ tag: tag, rank: rank })
                }
                near.sort((a, b) => a.rank - b.rank || a.tag.localeCompare(b.tag))
                shown = shown.concat(near.map((entry) => entry.tag))
            }
        }
        // Selected tags stay visible even when they fall outside the list --
        // otherwise retyping the search silently hides a filter still applied.
        // Not in the required/excluded views, whose whole point is showing
        // one of the two.
        let splitView = needle === "" && (page.tagLetter === "+" || page.tagLetter === "-")
        for (let name in page.tagStates) {
            if (!splitView && shown.indexOf(name) < 0) shown.push(name)
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
                    rating: entry.rating || "",
                    // Carried through so the detail page can say how far the
                    // dub is behind the sub. The source publishes both counts
                    // on the card and nothing else knows them -- AniList has
                    // no dub data at all.
                    sub_count: entry.sub_count || 0,
                    dub_count: entry.dub_count || 0
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
                // The QQC2 desktop style sets Kirigami.Theme.inherit = false on its
                // controls, which stops the app's accent reaching them -- measured
                // live: a page themed red still drew Breeze-blue Sub/Dub buttons.
                // Turning inheritance back on is what makes one accent value reach
                // every control in the app. See AppTheming.qml.
                Kirigami.Theme.inherit: true
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
                    Kirigami.Theme.inherit: true
                    id: catalogMenu

                    // The two listings built from this machine, above the
                    // ranked catalogs: they answer "where was I" and "what do
                    // I already have", which is what someone opening this
                    // picker most often wants.
                    // Continue Watching and Downloaded used to be listed here
                    // too. They have their own places now (the Continue page,
                    // Library > Downloads), and being presets here is what
                    // let Browse get stuck opening on Continue.
                    Instantiator {
                        model: []
                        onObjectAdded: (index, object) => catalogMenu.insertItem(index, object)
                        onObjectRemoved: (index, object) => catalogMenu.removeItem(object)
                        delegate: Controls.MenuItem {
                            required property var modelData
                            text: modelData.label
                            icon.name: modelData.key === "downloaded"
                                ? "folder-download-symbolic" : "media-playback-start-symbolic"
                            onTriggered: page.applyPreset(modelData.key)
                        }
                    }
                    Instantiator {
                        // Assigned once, not left as a live binding on
                        // backend.catalogs(): the preset list never changes,
                        // and a binding that reads `backend` is re-evaluated
                        // during teardown after the context property is gone
                        // ("Cannot call method 'catalogs' of null" on quit).
                        model: page.catalogPresets
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

            // Filter sets the user named and saved. Its own menu rather than
            // more rows in Quick picks: those are the source's rankings, and
            // these are yours.
            AppButton {
                text: "Presets"
                icon.name: "bookmarks-symbolic"
                onClicked: userPresetMenu.popup()

                Controls.Menu {
                    Kirigami.Theme.inherit: true
                    id: userPresetMenu

                    Instantiator {
                        model: page.userPresets
                        onObjectAdded: (index, object) => userPresetMenu.insertItem(index, object)
                        onObjectRemoved: (index, object) => userPresetMenu.removeItem(object)
                        delegate: Controls.MenuItem {
                            id: presetItem
                            required property var modelData
                            text: modelData.name
                            onTriggered: page.applyUserPreset(modelData)
                            contentItem: RowLayout {
                                spacing: Kirigami.Units.smallSpacing
                                Controls.Label {
                                    Layout.fillWidth: true
                                    text: presetItem.text
                                    elide: Text.ElideRight
                                }
                                Controls.ToolButton {
                                    Kirigami.Theme.inherit: true
                                    icon.name: "edit-delete-symbolic"
                                    implicitWidth: implicitHeight
                                    onClicked: {
                                        backend.deleteFilterPreset(presetItem.modelData.name)
                                        page.userPresets = backend.filterPresets()
                                    }
                                    Controls.ToolTip.visible: hovered
                                    Controls.ToolTip.text: "Delete this preset"
                                }
                            }
                        }
                    }
                    Controls.MenuItem {
                        enabled: false
                        visible: page.userPresets.length === 0
                        height: visible ? implicitHeight : 0
                        text: "No saved presets yet"
                    }
                    Controls.MenuSeparator {}
                    Controls.MenuItem {
                        text: "Save current filters\u2026"
                        icon.name: "document-save-symbolic"
                        enabled: page.localKey === ""
                        onTriggered: {
                            presetNameField.text = page.userPresets.some((p) => p.name === page.presetLabel)
                                ? page.presetLabel : ""
                            savePresetDialog.open()
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
            // Hidden outright rather than merely ignored while a local
            // listing is showing: a panel of controls that silently do
            // nothing is worse than no panel.
            visible: page.filtersOpen && page.localKey === ""

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

            ChipSection {
                id: tagSection
                label: "Tags"
                names: page.shownTags
                keys: page.shownTags
                states: page.tagStates
                hints: page.tagDescriptions
                collapsible: true
                baseLimit: 40
                // Shown even with no chips: until a letter is picked or
                // something typed, the section is just its search and letters.
                showEmpty: page.allTags.length > 0
                onToggled: (key) => { page.tagStates = page.tristate(page.tagStates, key); page.reload() }

                // Several hundred tags: search them, or open them a letter at
                // a time. The letters only show while the search is empty.
                tools: ColumnLayout {
                    spacing: Kirigami.Units.smallSpacing

                    Controls.TextField {
                        Kirigami.Theme.inherit: true
                        Layout.fillWidth: true
                        text: page.tagQuery
                        placeholderText: "Find a tag, e.g. \"Time Skip\" or \"Isekai\"..."
                        onTextChanged: if (text !== page.tagQuery) page.applyTagFilterText(text)
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 2
                        visible: page.tagQuery.trim() === ""

                        // Just what's set: everything required, everything
                        // excluded. Only offered once there's something.
                        Controls.ToolButton {
                            Kirigami.Theme.inherit: true
                            visible: page.includedTagCount > 0
                            text: "\u2713 " + page.includedTagCount
                            checkable: true
                            checked: page.tagLetter === "+"
                            onClicked: page.tagLetter = checked ? "+" : ""
                            Controls.ToolTip.visible: hovered
                            Controls.ToolTip.text: "Required tags"
                        }
                        Controls.ToolButton {
                            Kirigami.Theme.inherit: true
                            visible: page.excludedTagCount > 0
                            text: "\u2717 " + page.excludedTagCount
                            checkable: true
                            checked: page.tagLetter === "-"
                            onClicked: page.tagLetter = checked ? "-" : ""
                            Controls.ToolTip.visible: hovered
                            Controls.ToolTip.text: "Excluded tags"
                        }
                        Controls.ToolButton {
                            Kirigami.Theme.inherit: true
                            text: "All"
                            checkable: true
                            checked: page.tagLetter === "*"
                            onClicked: page.tagLetter = checked ? "*" : ""
                            Controls.ToolTip.visible: hovered
                            Controls.ToolTip.text: page.allTags.length + " tags"
                        }
                        Repeater {
                            model: page.tagLetters
                            Controls.ToolButton {
                                required property var modelData
                                Kirigami.Theme.inherit: true
                                text: modelData.letter
                                checkable: true
                                checked: page.tagLetter === modelData.letter
                                implicitWidth: Math.max(implicitHeight, implicitContentWidth + leftPadding + rightPadding)
                                onClicked: page.tagLetter = checked ? modelData.letter : ""
                                Controls.ToolTip.visible: hovered
                                Controls.ToolTip.text: modelData.count + (modelData.count === 1 ? " tag" : " tags")
                            }
                        }
                    }

                    Controls.Label {
                        visible: page.tagQuery.trim() !== "" && page.shownTags.length === Object.keys(page.tagStates).length
                        text: "No tag matches \"" + page.tagQuery.trim() + "\""
                        opacity: 0.7
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    }
                }
            }
        }

        Kirigami.Separator { Layout.fillWidth: true }
    }

    Controls.Dialog {
        id: savePresetDialog
        Kirigami.Theme.inherit: true
        parent: Controls.Overlay.overlay
        anchors.centerIn: parent
        modal: true
        title: "Save filters as a preset"
        standardButtons: Controls.Dialog.Save | Controls.Dialog.Cancel
        onOpened: presetNameField.forceActiveFocus()
        onAccepted: if (presetNameField.text.trim() !== "") page.saveUserPreset(presetNameField.text)

        ColumnLayout {
            spacing: Kirigami.Units.smallSpacing
            Controls.Label {
                text: "Saves the search, every filter and the sort order."
                opacity: 0.7
            }
            Controls.TextField {
                id: presetNameField
                Kirigami.Theme.inherit: true
                Layout.preferredWidth: Kirigami.Units.gridUnit * 20
                placeholderText: "Name, e.g. \"Short romcoms\""
                onAccepted: savePresetDialog.accept()
            }
            Controls.Label {
                visible: page.userPresets.some((p) => p.name.toLowerCase() === presetNameField.text.trim().toLowerCase())
                text: "Replaces the preset with this name."
                color: Kirigami.Theme.neutralTextColor
                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
            }
        }
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
                Kirigami.Theme.inherit: true
                anchors.centerIn: parent
                running: page.loadingMore
                visible: page.loadingMore
            }
        }

        Controls.BusyIndicator {
            Kirigami.Theme.inherit: true
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
    // One collapsible group of chips.
    //
    // Collapsed by default, and that is the whole point: six sections opened
    // at once put well over a hundred identically-weighted chips on screen,
    // which is a wall to read rather than a set of choices. Closed, each
    // section is one line saying what it filters and how many are set -- and
    // a section with something set opens itself, so a filter can never be
    // applied out of sight.
    component ChipSection: ColumnLayout {
        id: section
        property string label: ""
        property var names: []
        property var keys: []
        property var states: ({})
        // key -> hover text; optional.
        property var hints: ({})
        property bool collapsible: false
        property int baseLimit: 20
        property int limit: baseLimit
        property bool showEmpty: false
        // Optional controls between the header and the chips.
        property Component tools: null
        // Tracked separately from `open` so that a section the user closed by
        // hand stays closed even though it has an active filter.
        property bool touched: false
        property bool open: false
        signal toggled(string key)

        readonly property int activeCount: {
            let n = 0
            for (let i = 0; i < keys.length; i++) if (states[keys[i]] !== undefined) n++
            return n
        }
        onActiveCountChanged: if (!touched && activeCount > 0) open = true

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
        visible: names.length > 0 || showEmpty

        // The header is the whole clickable row, not just the arrow -- a
        // disclosure triangle is a small target for something used this often.
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: headerRow.implicitHeight + Kirigami.Units.smallSpacing
            radius: Kirigami.Units.smallSpacing
            color: headerHover.hovered
                ? Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g,
                          Kirigami.Theme.highlightColor.b, 0.08)
                : "transparent"

            RowLayout {
                id: headerRow
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Kirigami.Units.smallSpacing
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Icon {
                    source: section.open ? "go-down-symbolic" : "go-next-symbolic"
                    isMask: true
                    color: Kirigami.Theme.textColor
                    implicitWidth: Kirigami.Units.iconSizes.small
                    implicitHeight: Kirigami.Units.iconSizes.small
                }
                Controls.Label {
                    text: section.label
                    font.bold: true
                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                }
                Rectangle {
                    visible: section.activeCount > 0
                    implicitWidth: countLabel.implicitWidth + Kirigami.Units.smallSpacing * 2
                    implicitHeight: countLabel.implicitHeight + 2
                    radius: height / 2
                    color: Kirigami.Theme.highlightColor
                    Controls.Label {
                        id: countLabel
                        anchors.centerIn: parent
                        text: section.activeCount
                        color: Kirigami.Theme.highlightedTextColor
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                        font.bold: true
                    }
                }
                Item { Layout.fillWidth: true }
            }

            HoverHandler { id: headerHover; cursorShape: Qt.PointingHandCursor }
            TapHandler {
                onTapped: { section.touched = true; section.open = !section.open }
            }
        }

        Loader {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.gridUnit
            active: section.tools !== null && section.open
            visible: active
            sourceComponent: section.tools
        }

        Flow {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.gridUnit
            Layout.bottomMargin: Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.smallSpacing
            visible: section.open && section.names.length > 0

            Repeater {
                model: section.visibleIndexes
                TriStateChip {
                    required property var modelData
                    text: section.names[modelData]
                    state3: section.states[section.keys[modelData]] || 0
                    hint: section.hints[section.keys[modelData]] || ""
                    onClicked: section.toggled(section.keys[modelData])
                }
            }

            Controls.ToolButton {
                Kirigami.Theme.inherit: true
                visible: section.collapsible && section.names.length > section.baseLimit
                text: section.expanded ? "Show fewer"
                                       : "+" + (section.names.length - section.limit) + " more"
                icon.name: section.expanded ? "go-up-symbolic" : "go-down-symbolic"
                onClicked: section.limit = section.expanded ? section.baseLimit : section.names.length
            }
        }
    }

    // Neutral -> include (green, tick) -> exclude (red, cross) -> neutral.
    // A plain CheckBox only has two states, so this is a small custom button.
    component TriStateChip: Controls.Button {
        id: chip
        property int state3: 0
        property string hint: ""

        Controls.ToolTip.visible: hovered && hint !== ""
        Controls.ToolTip.text: hint
        Controls.ToolTip.delay: 600

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
