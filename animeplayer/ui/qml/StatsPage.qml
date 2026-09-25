// What you've watched, from two places: your AniList list, which has every
// finish date and rewatch going back years, and this computer's own record of
// time actually spent playing. See animeplayer/stats.py for how each number
// is worked out.
//
// Every chart here is a single series, so each is one hue -- the accent --
// with no legend: the heading names what it shows. Values and labels are in
// text colours; the accent is only ever the mark itself.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page

    AppTheming {}
    title: "Stats"

    property var stats: ({})
    readonly property bool empty: !stats.total_hours && !stats.total_episodes
    property var anilist: ({})
    property bool anilistLoading: true
    readonly property bool hasAnilist: page.anilist.days_watched !== undefined

    Component.onCompleted: {
        page.stats = backend.watchStats()
        backend.loadAnilistStats()
    }

    Connections {
        target: backend
        function onAnilistStatsReady(result) {
            page.anilist = result
            page.anilistLoading = false
        }
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

    ColumnLayout {
        width: page.availableWidth
        spacing: Kirigami.Units.gridUnit * 1.5

        // ================= From AniList =================
        Kirigami.Heading {
            level: 2
            text: "Your AniList"
            visible: page.hasAnilist
        }

        Controls.BusyIndicator {
            Kirigami.Theme.inherit: true
            Layout.alignment: Qt.AlignHCenter
            visible: page.anilistLoading
            running: visible
        }

        Flow {
            Layout.fillWidth: true
            spacing: Kirigami.Units.largeSpacing
            visible: page.hasAnilist

            StatTile {
                value: page.anilist.days_watched + " days"
                label: "watched (" + page.anilist.hours_watched + " hours)"
                note: "episodes × episode length, rewatches included"
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
                    if (top.times > 1) return "most: " + top.title + " (" + top.times + "×)"
                    return "across " + page.anilist.rewatched_shows + " shows"
                }
            }
            StatTile {
                value: page.anilist.mean_score ? page.anilist.mean_score : "–"
                label: "mean score"
                note: page.anilist.watching + " watching · " + page.anilist.planning + " planned · "
                    + page.anilist.dropped + " dropped"
            }
        }

        Section {
            title: "Finished per month"
            visible: page.hasAnilist

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
            title: "Recently finished"
            visible: (page.anilist.recently_finished || []).length > 0

            Repeater {
                model: page.anilist.recently_finished || []
                RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.largeSpacing
                    Controls.Label {
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 8
                        text: page.monthDay(modelData.date)
                        opacity: 0.7
                    }
                    Controls.Label {
                        Layout.fillWidth: true
                        text: modelData.title
                        elide: Text.ElideRight
                    }
                    Controls.Label {
                        text: (modelData.repeat > 0 ? "rewatched " + modelData.repeat + "× · " : "")
                            + (modelData.score > 0 ? "★ " + modelData.score : "")
                        opacity: 0.7
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    }
                }
            }
        }

        Section {
            title: "Genres, by time"
            hint: "A show counts toward each of its genres, so these add up to more than 100%."
            visible: (page.anilist.top_genres || []).length > 0

            BarRows {
                Layout.fillWidth: true
                rows: (page.anilist.top_genres || []).map((g) => ({
                    name: g.genre,
                    value: g.share,
                    text: Math.round(g.share * 100) + "% · " + Math.round(g.hours) + "h"
                }))
            }
        }

        Kirigami.PlaceholderMessage {
            Layout.fillWidth: true
            visible: !page.anilistLoading && !page.hasAnilist
            icon.name: "im-user-symbolic"
            text: "Log in to AniList for your full history"
            explanation: "Settings → AniList. Your list has every show you've finished, "
                       + "when, and how many times."
        }

        // ================= On this computer =================
        Kirigami.Heading {
            Layout.topMargin: Kirigami.Units.gridUnit
            level: 2
            text: "On this computer"
        }

        Kirigami.PlaceholderMessage {
            Layout.fillWidth: true
            visible: page.empty
            icon.name: "office-chart-bar-symbolic"
            text: "Nothing recorded yet"
            explanation: "Counting from now: time actually spent playing here, "
                       + "and when you finish episodes."
        }

        // -- The headline numbers -------------------------------------------
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

        // -- Last 14 days ---------------------------------------------------
        Section {
            title: "The last two weeks"
            visible: !page.empty

            BarColumns {
                Layout.fillWidth: true
                Layout.preferredHeight: Kirigami.Units.gridUnit * 8
                values: (page.stats.last_days || []).map((d) => d.minutes)
                labels: (page.stats.last_days || []).map((d) => d.label.charAt(0))
                tips: (page.stats.last_days || []).map((d) =>
                    d.label + " " + d.day + ": " + (d.minutes >= 60
                        ? page.hoursText(d.hours) : d.minutes + " min"))
            }
        }

        // -- Most watched ---------------------------------------------------
        Section {
            title: "Most watched"
            visible: (page.stats.top_shows || []).length > 0

            BarRows {
                Layout.fillWidth: true
                rows: (page.stats.top_shows || []).map((s) => ({
                    name: s.title,
                    value: s.hours,
                    text: page.hoursText(s.hours)
                          + (s.episodes ? " · " + s.episodes + " ep" : "")
                }))
            }
        }

        // -- Genres ---------------------------------------------------------
        Section {
            title: "Genres"
            hint: "A show counts toward each of its genres, so these add up to more than 100%."
            visible: (page.stats.top_genres || []).length > 0

            BarRows {
                Layout.fillWidth: true
                rows: (page.stats.top_genres || []).map((g) => ({
                    name: g.genre,
                    value: g.share,
                    text: Math.round(g.share * 100) + "% · " + page.hoursText(g.hours)
                }))
            }
        }

        // -- Time of day ----------------------------------------------------
        Section {
            title: "When you finish episodes"
            hint: page.stats.busiest_hour >= 0
                ? "Most often around " + page.hourLabel(page.stats.busiest_hour) : ""
            visible: page.stats.busiest_hour >= 0

            BarColumns {
                Layout.fillWidth: true
                Layout.preferredHeight: Kirigami.Units.gridUnit * 6
                values: page.stats.episodes_by_hour || []
                // Every sixth hour labelled; 24 labels would collide.
                labels: (page.stats.episodes_by_hour || []).map((_, h) => h % 6 === 0 ? page.hourLabel(h) : "")
                tips: (page.stats.episodes_by_hour || []).map((n, h) =>
                    page.hourLabel(h) + ": " + n + (n === 1 ? " episode" : " episodes"))
            }
        }
    }

    // A big number with a line saying what it is.
    component StatTile: Rectangle {
        id: tile
        property var value
        property string label: ""
        property string note: ""

        implicitWidth: Kirigami.Units.gridUnit * 13
        // One height for every tile, note or not: a row of boxes that differ
        // by a line reads as misaligned rather than as four equals.
        implicitHeight: Kirigami.Units.gridUnit * 5.5
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
                font.pixelSize: Kirigami.Units.gridUnit * 1.8
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
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 14
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
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 7
                    text: modelData.text
                    opacity: 0.8
                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                }
                HoverHandler { id: rowHover }
            }
        }
    }
}
