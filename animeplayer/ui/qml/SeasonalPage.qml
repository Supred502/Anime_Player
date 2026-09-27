// One anime season at a time: everything airing in it, most popular first,
// grouped into TV, movies and the rest. The arrows step a season back or
// forward; it opens on the current one.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page

    AppTheming {}
    title: page.label(page.season, page.year)

    property string season: ""
    property int year: 0
    property var cards: []
    property bool loading: true
    property string error: ""
    property bool opening: false
    property bool hideSeen: false
    property real nowSeconds: Date.now() / 1000

    readonly property var seasons: ["WINTER", "SPRING", "SUMMER", "FALL"]
    readonly property int columns: Math.max(2, Math.floor(page.availableWidth / (Kirigami.Units.gridUnit * 10)))
    readonly property real cellWidth: (page.availableWidth - (page.columns - 1) * Kirigami.Units.largeSpacing) / page.columns

    // Which formats go under which heading, in this order.
    readonly property var groups: [
        { title: "TV", formats: ["TV"] },
        { title: "Movies", formats: ["MOVIE"] },
        { title: "Online and OVA", formats: ["ONA", "OVA"] },
        { title: "Shorts and specials", formats: ["TV_SHORT", "SPECIAL", "MUSIC"] }
    ]

    function label(season, year) {
        return season ? season.charAt(0) + season.slice(1).toLowerCase() + " " + year : "Seasonal"
    }
    function step(delta) {
        let i = page.seasons.indexOf(page.season) + delta
        let y = page.year
        if (i < 0) { i = 3; y-- }
        if (i > 3) { i = 0; y++ }
        page.show(page.seasons[i], y)
    }
    function show(season, year) {
        page.season = season
        page.year = year
        page.loading = true
        page.error = ""
        page.cards = []
        backend.loadSeason(season, year)
    }
    function shown(group) {
        return page.cards.filter((c) => group.formats.indexOf(c.format) >= 0
                                 && !(page.hideSeen && (c.list_status === "COMPLETED" || c.list_status === "DROPPED")))
    }
    function airingText(card) {
        if (card.next_airing_at > 0) {
            let s = card.next_airing_at - page.nowSeconds
            let d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600)
            let when = d > 0 ? d + "d " + h + "h" : h > 0 ? h + "h" : "soon"
            return (card.status === "NOT_YET_RELEASED" && card.next_episode === 1 ? "Starts in " : "Ep " + card.next_episode + " in ") + when
        }
        if (card.status === "FINISHED") return card.episodes > 0 ? card.episodes + " episodes" : "Finished"
        if (card.status === "NOT_YET_RELEASED") return "Not out yet"
        return card.genres.join(" · ")
    }
    readonly property var listLabels: ({ CURRENT: "Watching", PLANNING: "Planning", COMPLETED: "Completed",
                                         PAUSED: "Paused", DROPPED: "Dropped" })

    Component.onCompleted: {
        let now = backend.currentSeason()
        page.show(now.season, now.year)
    }
    Timer { interval: 60000; running: true; repeat: true; onTriggered: page.nowSeconds = Date.now() / 1000 }

    Connections {
        target: backend
        function onSeasonReady(season, year, cards) {
            if (season !== page.season || year !== page.year) return
            page.cards = cards
            page.loading = false
        }
        function onSeasonFailed(message) { page.error = message; page.loading = false }
        function onAnilistAnimeResolved(result) {
            if (!page.opening) return
            page.opening = false
            applicationWindow().pageStack.push(Qt.resolvedUrl("DetailPage.qml"), {
                anime: { slug_id: result.slug_id, numeric_id: result.numeric_id, title: result.title,
                         poster_url: result.poster_url || "", kind: result.kind || "", rating: "" }
            })
        }
        function onAnilistAnimeResolveFailed(title) {
            if (!page.opening) return
            page.opening = false
            showPassiveNotification("\"" + title + "\" isn't on the streaming source yet")
        }
    }

    actions: [
        Kirigami.Action {
            icon.name: "go-previous-symbolic"
            text: page.label(page.season === "WINTER" ? "FALL" : page.seasons[page.seasons.indexOf(page.season) - 1] || "",
                             page.season === "WINTER" ? page.year - 1 : page.year)
            onTriggered: page.step(-1)
        },
        Kirigami.Action {
            icon.name: "go-next-symbolic"
            text: page.label(page.season === "FALL" ? "WINTER" : page.seasons[page.seasons.indexOf(page.season) + 1] || "",
                             page.season === "FALL" ? page.year + 1 : page.year)
            onTriggered: page.step(1)
        },
        Kirigami.Action {
            text: "Hide finished and dropped"
            icon.name: "view-filter-symbolic"
            checkable: true
            checked: page.hideSeen
            onTriggered: page.hideSeen = !page.hideSeen
        }
    ]

    ColumnLayout {
        width: page.availableWidth
        spacing: Kirigami.Units.gridUnit

        Controls.BusyIndicator {
            Kirigami.Theme.inherit: true
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: Kirigami.Units.gridUnit * 3
            visible: page.loading
            running: visible
        }
        Kirigami.PlaceholderMessage {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.gridUnit * 3
            visible: !page.loading && (page.error !== "" || page.cards.length === 0)
            icon.name: "view-calendar-symbolic"
            text: page.error !== "" ? "Couldn't load this season" : "Nothing announced for this season yet"
            explanation: page.error
        }

        Repeater {
            model: page.loading ? [] : page.groups
            ColumnLayout {
                id: group
                required property var modelData
                readonly property var items: page.shown(modelData)
                Layout.fillWidth: true
                visible: items.length > 0
                spacing: Kirigami.Units.largeSpacing

                RowLayout {
                    spacing: Kirigami.Units.largeSpacing
                    Rectangle {
                        Layout.preferredWidth: 4
                        Layout.preferredHeight: groupHeading.implicitHeight
                        radius: 2
                        color: Kirigami.Theme.highlightColor
                    }
                    Kirigami.Heading { id: groupHeading; level: 2; text: group.modelData.title }
                    Controls.Label { text: group.items.length; opacity: 0.6 }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: page.columns
                    columnSpacing: Kirigami.Units.largeSpacing
                    rowSpacing: Kirigami.Units.largeSpacing
                    Repeater {
                        model: group.items
                        AnimeCard {
                            required property var modelData
                            Layout.preferredWidth: page.cellWidth
                            Layout.maximumWidth: page.cellWidth
                            // See AnimeCard: its height comes from its width,
                            // asked for explicitly.
                            Layout.preferredHeight: heightForWidth(page.cellWidth)
                            posterUrl: modelData.poster_url
                            title: modelData.title
                            subtitle: page.airingText(modelData)
                            scoreText: modelData.score > 0 ? (modelData.score / 10).toFixed(1) : ""
                            badgeText: page.listLabels[modelData.list_status] || ""
                            onClicked: {
                                page.opening = true
                                backend.openAnilistAnime(modelData.anilist_id, modelData.title)
                            }
                        }
                    }
                }
            }
        }
    }
}
