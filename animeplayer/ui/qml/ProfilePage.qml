// Your profile: who you are on AniList, what you've watched, and what the
// people you follow are into. Three tabs rather than one long column:
//
//   Overview       your AniList stats (every finish date and rewatch AniList
//                  has, going back years)
//   Friends        the people you follow: what they watched lately and how
//                  they rated it, and AniList's "Following" activity feed
//   This computer  time actually spent playing here (see animeplayer/stats.py)
//
// Charts sit two to a row on a wide window, so a bar chart is never the full
// width of the screen. Every chart is a single series, so each is one hue --
// the accent -- with no legend: the heading names what it shows.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page

    AppTheming {}
    title: "Profile"

    property var stats: ({})
    readonly property bool empty: !stats.total_hours && !stats.total_episodes
    property var anilist: ({})
    property bool anilistLoading: true
    readonly property bool hasAnilist: page.anilist.days_watched !== undefined
    property var profile: ({})
    property var friends: []
    property var activity: []
    property int myId: 0
    property bool friendsLoading: true
    property string friendsError: ""
    property bool activityAnimeOnly: backend.learnOption("activity_anime_only") === "true"
    property string tab: backend.learnOption("profile_tab") || "overview"
    onTabChanged: backend.setLearnOption("profile_tab", page.tab)
    readonly property bool loggedIn: backend.isAnilistLoggedIn()
    // Two charts to a row once there's room for both to be readable.
    readonly property int columns: page.availableWidth > Kirigami.Units.gridUnit * 48 ? 2 : 1
    property bool opening: false

    Component.onCompleted: {
        page.stats = backend.watchStats()
        backend.loadAnilistStats()
        backend.loadProfile()
        backend.loadFriends()
    }

    Connections {
        target: backend
        function onAnilistStatsReady(result) {
            page.anilist = result
            page.anilistLoading = false
        }
        function onProfileReady(result) {
            page.profile = result
            if (result.avatar) backend.rememberProfileAvatar(result.avatar)
        }
        function onFriendsReady(result) {
            page.friends = result.friends || []
            page.activity = result.activity || []
            page.myId = result.me || 0
            page.friendsLoading = false
        }
        function onFriendsFailed(message) {
            page.friendsError = message
            page.friendsLoading = false
        }
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

    function openAnime(anilistId, title) {
        page.opening = true
        backend.openAnilistAnime(anilistId, title)
    }

    function monthDay(date) {
        // AniList dates can be partial: "2024", "2024-03" or "2024-03-09".
        if (date.length < 7) return date
        let d = new Date(Number(date.slice(0, 4)), Number(date.slice(5, 7)) - 1,
                         date.length >= 10 ? Number(date.slice(8, 10)) : 1)
        return Qt.formatDate(d, date.length >= 10 ? "d MMM yyyy" : "MMM yyyy")
    }

    function hoursText(hours) {
        if (!hours) return "0m"
        if (hours < 1) return Math.round(hours * 60) + "m"
        return (hours % 1 === 0 ? hours.toFixed(0) : hours.toFixed(1)) + "h"
    }

    function hourLabel(hour) {
        if (hour === 0) return "12am"
        if (hour === 12) return "12pm"
        return hour < 12 ? hour + "am" : (hour - 12) + "pm"
    }

    function ago(seconds) {
        let s = Math.max(0, Date.now() / 1000 - seconds)
        if (s < 3600) return Math.max(1, Math.round(s / 60)) + " min ago"
        if (s < 86400) return Math.round(s / 3600) + (Math.round(s / 3600) === 1 ? " hour ago" : " hours ago")
        let d = Math.round(s / 86400)
        return d === 1 ? "yesterday" : d < 30 ? d + " days ago" : Qt.formatDate(new Date(seconds * 1000), "d MMM yyyy")
    }

    // "watched episode 7 - 10 of", "completed", "plans to watch" -- as AniList says it.
    function activityText(a) {
        let progress = a.progress ? " " + a.progress : ""
        if (a.status === "watched episode" || a.status === "read chapter" || a.status === "rewatched episode"
                || a.status === "reread chapter")
            return a.status + progress + " of"
        return a.status
    }

    function friendLine(r) {
        let parts = []
        if (r.score > 0) parts.push("\u2605 " + r.score)
        let status = { COMPLETED: "Finished", CURRENT: "Watching ep " + r.progress, PLANNING: "Planning",
                       DROPPED: "Dropped", PAUSED: "Paused", REPEATING: "Rewatching" }[r.status] || ""
        if (status) parts.push(status)
        return parts.join(" \u00b7 ")
    }

    ColumnLayout {
        width: page.availableWidth
        spacing: Kirigami.Units.gridUnit

        // ================= Who you are =================
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Kirigami.Units.gridUnit * 7
            radius: Kirigami.Units.smallSpacing * 2
            color: Kirigami.Theme.alternateBackgroundColor
            clip: true
            visible: page.loggedIn

            Image {
                anchors.fill: parent
                source: page.profile.banner || ""
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                opacity: 0.45
            }
            Rectangle {
                anchors.fill: parent
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: Qt.rgba(0, 0, 0, 0.75) }
                    GradientStop { position: 0.7; color: Qt.rgba(0, 0, 0, 0.15) }
                }
            }
            RowLayout {
                anchors.fill: parent
                anchors.margins: Kirigami.Units.largeSpacing * 2
                spacing: Kirigami.Units.largeSpacing * 2
                Avatar {
                    source: page.profile.avatar || backend.profileAvatar()
                    size: Kirigami.Units.gridUnit * 4.5
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Kirigami.Heading {
                        level: 1
                        color: "white"
                        text: page.profile.name || backend.anilistViewerName()
                    }
                    Controls.Label {
                        color: "white"
                        opacity: 0.85
                        visible: page.hasAnilist
                        text: page.hasAnilist
                            ? page.anilist.completed + " shows finished \u00b7 " + page.anilist.days_watched
                              + " days of anime \u00b7 mean score " + (page.anilist.mean_score || "\u2013")
                            : ""
                    }
                }
                AppButton {
                    visible: !!page.profile.site_url
                    text: "AniList profile"
                    icon.name: "internet-services-symbolic"
                    onClicked: Qt.openUrlExternally(page.profile.site_url)
                }
            }
        }

        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Repeater {
                model: [["overview", "Overview", "view-statistics-symbolic"],
                        ["friends", "Friends", "system-users-symbolic"],
                        ["computer", "This computer", "computer-symbolic"]]
                AppButton {
                    required property var modelData
                    text: modelData[1]
                    icon.name: modelData[2]
                    checkable: true
                    checked: page.tab === modelData[0]
                    onClicked: page.tab = modelData[0]
                }
            }
        }

        // ================= Overview: AniList =================
        ColumnLayout {
            Layout.fillWidth: true
            visible: page.tab === "overview"
            spacing: Kirigami.Units.gridUnit

            Controls.BusyIndicator {
                Kirigami.Theme.inherit: true
                Layout.alignment: Qt.AlignHCenter
                visible: page.anilistLoading && page.loggedIn
                running: visible
            }

            Flow {
                Layout.fillWidth: true
                spacing: Kirigami.Units.largeSpacing
                visible: page.hasAnilist

                StatTile {
                    value: page.anilist.days_watched + " days"
                    label: "watched (" + page.anilist.hours_watched + " hours)"
                    note: "rewatches included"
                }
                StatTile {
                    value: page.anilist.episodes_watched
                    label: "episodes watched"
                }
                StatTile {
                    value: page.anilist.completed
                    label: "shows completed"
                    note: page.anilist.finished_this_year + " so far this year"
                }
                StatTile {
                    value: page.anilist.rewatch_count
                    label: page.anilist.rewatch_count === 1 ? "rewatch" : "rewatches"
                    // Naming a favourite only means something when one show was
                    // rewatched more than the others.
                    note: {
                        let top = (page.anilist.most_rewatched || [])[0]
                        if (!top) return ""
                        if (top.times > 1) return "most: " + top.title + " (" + top.times + "\u00d7)"
                        return "across " + page.anilist.rewatched_shows + " shows"
                    }
                }
                StatTile {
                    value: page.anilist.mean_score ? page.anilist.mean_score : "\u2013"
                    label: "mean score"
                    note: page.anilist.watching + " watching \u00b7 " + page.anilist.planning + " planned \u00b7 "
                        + page.anilist.dropped + " dropped"
                }
            }

            GridLayout {
                Layout.fillWidth: true
                visible: page.hasAnilist
                columns: page.columns
                columnSpacing: Kirigami.Units.gridUnit * 2
                rowSpacing: Kirigami.Units.gridUnit

                Section {
                    title: "Finished per month"
                    BarColumns {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Kirigami.Units.gridUnit * 7
                        values: (page.anilist.finished_per_month || []).map((m) => m.count)
                        labels: (page.anilist.finished_per_month || []).map((m) => m.label)
                        tips: (page.anilist.finished_per_month || []).map((m) =>
                            page.monthDay(m.month) + ": " + m.count + (m.count === 1 ? " show" : " shows"))
                    }
                }
                Section {
                    title: "Genres, by time"
                    hint: "A show counts toward each of its genres."
                    BarRows {
                        Layout.fillWidth: true
                        rows: (page.anilist.top_genres || []).slice(0, 7).map((g) => ({
                            name: g.genre,
                            value: g.share,
                            text: Math.round(g.share * 100) + "% \u00b7 " + Math.round(g.hours) + "h"
                        }))
                    }
                }
                Section {
                    Layout.columnSpan: page.columns
                    title: "Recently finished"
                    visible: (page.anilist.recently_finished || []).length > 0
                    GridLayout {
                        Layout.fillWidth: true
                        columns: page.columns
                        columnSpacing: Kirigami.Units.gridUnit * 2
                        rowSpacing: 2
                        Repeater {
                            model: page.anilist.recently_finished || []
                            RowLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.preferredWidth: 1
                                spacing: Kirigami.Units.largeSpacing
                                Controls.Label {
                                    Layout.preferredWidth: Kirigami.Units.gridUnit * 6
                                    text: page.monthDay(modelData.date)
                                    opacity: 0.6
                                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                                }
                                Controls.Label {
                                    Layout.fillWidth: true
                                    text: modelData.title
                                    elide: Text.ElideRight
                                }
                                Controls.Label {
                                    text: (modelData.repeat > 0 ? "rewatched " + modelData.repeat + "\u00d7 \u00b7 " : "")
                                        + (modelData.score > 0 ? "\u2605 " + modelData.score : "")
                                    opacity: 0.7
                                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                                }
                            }
                        }
                    }
                }
            }

            Kirigami.PlaceholderMessage {
                Layout.fillWidth: true
                visible: !page.loggedIn || (!page.anilistLoading && !page.hasAnilist)
                icon.name: "im-user-symbolic"
                text: "Log in to AniList for your profile"
                explanation: "Settings \u2192 AniList. Your list has every show you've finished, "
                           + "when, and how many times -- and who you follow."
            }
        }

        // ================= Friends =================
        ColumnLayout {
            Layout.fillWidth: true
            visible: page.tab === "friends"
            spacing: Kirigami.Units.gridUnit

            Controls.BusyIndicator {
                Kirigami.Theme.inherit: true
                Layout.alignment: Qt.AlignHCenter
                visible: page.friendsLoading && page.loggedIn
                running: visible
            }
            Kirigami.PlaceholderMessage {
                Layout.fillWidth: true
                visible: !page.friendsLoading && page.loggedIn && page.friends.length === 0
                         && page.friendsError === ""
                icon.name: "system-users-symbolic"
                text: "You don't follow anyone on AniList yet"
                explanation: "Follow your friends on anilist.co and what they're watching shows up here."
            }
            Kirigami.PlaceholderMessage {
                Layout.fillWidth: true
                visible: page.friendsError !== ""
                icon.name: "network-disconnect-symbolic"
                text: "Couldn't load your friends"
                explanation: page.friendsError
            }

            // What each of them has been watching, newest first.
            Repeater {
                model: page.friends.filter((f) => f.recent.length > 0)
                Section {
                    id: friendSection
                    required property var modelData
                    title: modelData.name
                    hint: "Last active " + page.ago(modelData.recent[0].updated_at)
                    Flickable {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Kirigami.Units.gridUnit * 15
                        contentWidth: friendRow.width
                        clip: true
                        flickableDirection: Flickable.HorizontalFlick
                        Controls.ScrollBar.horizontal: Controls.ScrollBar { policy: Controls.ScrollBar.AsNeeded }
                        Row {
                            id: friendRow
                            spacing: Kirigami.Units.largeSpacing
                            Repeater {
                                model: friendSection.modelData.recent
                                AnimeCard {
                                    required property var modelData
                                    width: Kirigami.Units.gridUnit * 8
                                    height: Kirigami.Units.gridUnit * 14.5
                                    posterUrl: modelData.poster_url
                                    anilistId: modelData.anilist_id
                                    title: modelData.title
                                    subtitle: page.friendLine(modelData)
                                    scoreText: modelData.score > 0 ? String(modelData.score) : ""
                                    onClicked: page.openAnime(modelData.anilist_id, modelData.title)
                                }
                            }
                        }
                    }
                }
            }

            Section {
                title: "Activity"
                visible: page.activity.length > 0
                AppCheckBox {
                    text: "Anime only"
                    checked: page.activityAnimeOnly
                    onToggled: {
                        page.activityAnimeOnly = checked
                        backend.setLearnOption("activity_anime_only", checked ? "true" : "false")
                    }
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: page.columns
                    columnSpacing: Kirigami.Units.largeSpacing
                    rowSpacing: Kirigami.Units.smallSpacing
                    Repeater {
                        model: page.activity.filter((a) => !page.activityAnimeOnly || a.kind === "anime")
                        Rectangle {
                            id: activityRow
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            implicitHeight: Kirigami.Units.gridUnit * 4.2
                            radius: Kirigami.Units.smallSpacing * 2
                            color: activityHover.hovered
                                   ? Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g,
                                             Kirigami.Theme.highlightColor.b, 0.15)
                                   : Kirigami.Theme.alternateBackgroundColor
                            clip: true
                            HoverHandler { id: activityHover; cursorShape: Qt.PointingHandCursor }
                            // Anime opens here; manga, which this app doesn't play, on AniList.
                            TapHandler {
                                onTapped: activityRow.modelData.kind === "anime"
                                    ? page.openAnime(activityRow.modelData.anilist_id, activityRow.modelData.title)
                                    : Qt.openUrlExternally(activityRow.modelData.media_url)
                            }
                            RowLayout {
                                anchors.fill: parent
                                spacing: Kirigami.Units.largeSpacing
                                Image {
                                    Layout.fillHeight: true
                                    Layout.preferredWidth: height * 0.7
                                    source: activityRow.modelData.poster_url
                                    fillMode: Image.PreserveAspectCrop
                                    asynchronous: true
                                }
                                Avatar {
                                    source: activityRow.modelData.avatar
                                    size: Kirigami.Units.gridUnit * 2
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 0
                                    Controls.Label {
                                        Layout.fillWidth: true
                                        elide: Text.ElideRight
                                        textFormat: Text.StyledText
                                        text: "<b>" + (activityRow.modelData.user_id === page.myId ? "You" : activityRow.modelData.user)
                                              + "</b> " + page.activityText(activityRow.modelData)
                                    }
                                    Controls.Label {
                                        Layout.fillWidth: true
                                        elide: Text.ElideRight
                                        color: Kirigami.Theme.highlightColor
                                        text: activityRow.modelData.title
                                              + (activityRow.modelData.kind === "manga" ? "  (manga)" : "")
                                    }
                                }
                                Controls.Label {
                                    Layout.rightMargin: Kirigami.Units.largeSpacing
                                    text: page.ago(activityRow.modelData.created_at)
                                    opacity: 0.6
                                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                                }
                            }
                        }
                    }
                }
            }
        }

        // ================= This computer =================
        ColumnLayout {
            Layout.fillWidth: true
            visible: page.tab === "computer"
            spacing: Kirigami.Units.gridUnit

            Kirigami.PlaceholderMessage {
                Layout.fillWidth: true
                visible: page.empty
                icon.name: "office-chart-bar-symbolic"
                text: "Nothing recorded yet"
                explanation: "Counting from now: time actually spent playing here, "
                           + "and when you finish episodes."
            }

            Flow {
                Layout.fillWidth: true
                spacing: Kirigami.Units.largeSpacing
                visible: !page.empty

                StatTile {
                    value: page.hoursText(page.stats.total_hours)
                    label: "watched in total"
                }
                StatTile {
                    value: page.stats.total_episodes || 0
                    label: (page.stats.total_episodes === 1 ? "episode" : "episodes")
                         + " finished, across " + (page.stats.show_count || 0)
                         + (page.stats.show_count === 1 ? " show" : " shows")
                }
                StatTile {
                    value: page.hoursText(page.stats.this_week_hours)
                    label: "in the last 7 days"
                    note: {
                        let now = page.stats.this_week_hours || 0
                        let before = page.stats.last_week_hours || 0
                        if (before === 0) return ""
                        let change = Math.round((now - before) / before * 100)
                        return change === 0 ? "same as the week before"
                             : (change > 0 ? "up " : "down ") + Math.abs(change) + "% on the week before"
                    }
                }
                StatTile {
                    value: (page.stats.streak_days || 0) + (page.stats.streak_days === 1 ? " day" : " days")
                    label: "streak"
                    note: "days in a row with 5+ minutes"
                }
            }

            GridLayout {
                Layout.fillWidth: true
                visible: !page.empty
                columns: page.columns
                columnSpacing: Kirigami.Units.gridUnit * 2
                rowSpacing: Kirigami.Units.gridUnit

                Section {
                    title: "The last two weeks"
                    BarColumns {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Kirigami.Units.gridUnit * 7
                        values: (page.stats.last_days || []).map((d) => d.minutes)
                        labels: (page.stats.last_days || []).map((d) => d.label.charAt(0))
                        tips: (page.stats.last_days || []).map((d) =>
                            d.label + " " + d.day + ": " + (d.minutes >= 60
                                ? page.hoursText(d.hours) : d.minutes + " min"))
                    }
                }
                Section {
                    title: "When you finish episodes"
                    hint: page.stats.busiest_hour >= 0
                        ? "Most often around " + page.hourLabel(page.stats.busiest_hour) : ""
                    BarColumns {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Kirigami.Units.gridUnit * 7
                        values: page.stats.episodes_by_hour || []
                        // Every sixth hour labelled; 24 labels would collide.
                        labels: (page.stats.episodes_by_hour || []).map((_, h) => h % 6 === 0 ? page.hourLabel(h) : "")
                        tips: (page.stats.episodes_by_hour || []).map((n, h) =>
                            page.hourLabel(h) + ": " + n + (n === 1 ? " episode" : " episodes"))
                    }
                }
                Section {
                    title: "Most watched"
                    visible: (page.stats.top_shows || []).length > 0
                    BarRows {
                        Layout.fillWidth: true
                        rows: (page.stats.top_shows || []).map((s) => ({
                            name: s.title,
                            value: s.hours,
                            text: page.hoursText(s.hours) + (s.episodes ? " \u00b7 " + s.episodes + " ep" : "")
                        }))
                    }
                }
                Section {
                    title: "Genres"
                    hint: "A show counts toward each of its genres."
                    visible: (page.stats.top_genres || []).length > 0
                    BarRows {
                        Layout.fillWidth: true
                        rows: (page.stats.top_genres || []).map((g) => ({
                            name: g.genre,
                            value: g.share,
                            text: Math.round(g.share * 100) + "% \u00b7 " + page.hoursText(g.hours)
                        }))
                    }
                }
            }
        }
    }

    // A big number with a line saying what it is.
    component StatTile: Rectangle {
        id: tile
        property var value
        property string label: ""
        property string note: ""

        implicitWidth: Kirigami.Units.gridUnit * 10.5
        // One height for every tile, note or not: a row of boxes that differ
        // by a line reads as misaligned rather than as four equals.
        implicitHeight: Kirigami.Units.gridUnit * 4.6
        radius: Kirigami.Units.smallSpacing * 2
        color: Kirigami.Theme.alternateBackgroundColor

        ColumnLayout {
            id: tileColumn
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: 2
            Controls.Label {
                text: String(tile.value)
                font.pixelSize: Kirigami.Units.gridUnit * 1.5
                font.bold: true
            }
            Controls.Label {
                Layout.fillWidth: true
                text: tile.label
                wrapMode: Text.WordWrap
                opacity: 0.8
            }
            Controls.Label {
                Layout.fillWidth: true
                visible: text !== ""
                text: tile.note
                wrapMode: Text.WordWrap
                opacity: 0.6
                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
            }
        }
    }

    component Section: ColumnLayout {
        id: section
        property string title: ""
        property string hint: ""
        default property alias content: body.data

        Layout.fillWidth: true
        // Equal shares of a grid row, whatever their contents' own widths.
        Layout.preferredWidth: 1
        Layout.alignment: Qt.AlignTop
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Rectangle {
                Layout.preferredWidth: 4
                Layout.preferredHeight: sectionHeading.implicitHeight * 0.8
                radius: 2
                color: Kirigami.Theme.highlightColor
            }
            Kirigami.Heading {
                id: sectionHeading
                level: 3
                text: section.title
            }
        }
        Controls.Label {
            visible: text !== ""
            text: section.hint
            opacity: 0.6
            font.pixelSize: Kirigami.Theme.smallFont.pixelSize
        }
        ColumnLayout {
            id: body
            Layout.fillWidth: true
        }
    }

    // Vertical bars along a baseline, one per value, each with a hover
    // tooltip. The hover target is the whole column, not just the bar, so a
    // zero day can still be pointed at.
    component BarColumns: Item {
        id: columns
        property var values: []
        property var labels: []
        property var tips: []
        readonly property real maxValue: Math.max(1, ...columns.values)
        readonly property int labelHeight: Kirigami.Units.gridUnit

        // Recessive baseline.
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            y: columns.height - columns.labelHeight
            height: 1
            color: Kirigami.Theme.disabledTextColor
            opacity: 0.4
        }

        Row {
            anchors.fill: parent
            // A 2px gap between neighbouring bars, per the mark spec.
            spacing: 2

            Repeater {
                model: columns.values.length

                Item {
                    required property int index
                    width: (columns.width - 2 * (columns.values.length - 1)) / columns.values.length
                    height: columns.height

                    Rectangle {
                        readonly property real plotHeight: columns.height - columns.labelHeight - 2
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: Math.min(parent.width, Kirigami.Units.gridUnit * 1.6)
                        height: Math.max(columns.values[index] > 0 ? 3 : 0,
                                         plotHeight * columns.values[index] / columns.maxValue)
                        y: columns.height - columns.labelHeight - height
                        // Rounded at the data end only: the top corners are
                        // round, the bottom sits square on the baseline.
                        radius: 4
                        color: Kirigami.Theme.highlightColor
                        opacity: barHover.hovered ? 1 : 0.85
                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: Math.min(parent.height, 4)
                            color: parent.color
                        }
                    }
                    Controls.Label {
                        anchors.bottom: parent.bottom
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: columns.labels[index] || ""
                        opacity: 0.6
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    }
                    HoverHandler { id: barHover }
                    Controls.ToolTip.visible: barHover.hovered
                    Controls.ToolTip.text: columns.tips[index] || ""
                    Controls.ToolTip.delay: 0
                }
            }
        }
    }

    // Horizontal bars with the name on the left and the value at the end:
    // for ranked lists, where the names are long and the order is the point.
    component BarRows: ColumnLayout {
        id: barRows
        property var rows: []
        readonly property real maxValue: Math.max(0.0001, ...barRows.rows.map((r) => r.value))
        spacing: 2

        Repeater {
            model: barRows.rows

            RowLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: Kirigami.Units.largeSpacing

                Controls.Label {
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 9
                    text: modelData.name
                    elide: Text.ElideRight
                }
                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Kirigami.Units.gridUnit * 1.2
                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        height: Kirigami.Units.gridUnit * 0.8
                        width: Math.max(4, parent.width * modelData.value / barRows.maxValue)
                        radius: 4
                        color: Kirigami.Theme.highlightColor
                        opacity: rowHover.hovered ? 1 : 0.85
                        Rectangle {
                            anchors.left: parent.left
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            width: Math.min(parent.width, 4)
                            color: parent.color
                        }
                    }
                }
                Controls.Label {
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 6
                    text: modelData.text
                    opacity: 0.8
                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                }
                HoverHandler { id: rowHover }
            }
        }
    }
}
