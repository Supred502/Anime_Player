// The week ahead: every episode airing in the next seven days, by day, with
// the shows you're watching or planning marked -- and a switch to see only
// those. Times are the Japanese broadcast (subs usually follow within hours).
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page

    AppTheming {}
    title: "Schedule"

    property var items: []
    property bool loading: true
    property string error: ""
    property bool followedOnly: backend.learnOption("schedule_followed") === "true"
    property bool opening: false
    property real nowSeconds: Date.now() / 1000

    Timer { interval: 60000; running: true; repeat: true; onTriggered: page.nowSeconds = Date.now() / 1000 }

    Component.onCompleted: backend.loadSchedule()

    Connections {
        target: backend
        function onScheduleReady(items) { page.items = items; page.loading = false }
        function onScheduleFailed(message) { page.error = message; page.loading = false }
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

    readonly property var shown: page.followedOnly ? page.items.filter((i) => i.following || i.planning) : page.items

    // [{ label, items }] -- one per day that has anything.
    readonly property var days: {
        let out = []
        let byKey = {}
        let today = new Date()
        today.setHours(0, 0, 0, 0)
        for (let item of page.shown) {
            let d = new Date(item.airing_at * 1000)
            let day = new Date(d)
            day.setHours(0, 0, 0, 0)
            let key = day.getTime()
            if (!byKey[key]) {
                let diff = Math.round((day - today) / 86400000)
                let label = diff === 0 ? "Today" : diff === 1 ? "Tomorrow"
                          : day.toLocaleDateString(Qt.locale(), "dddd")
                byKey[key] = { label: label, date: day.toLocaleDateString(Qt.locale(), "d MMMM"), items: [] }
                out.push(byKey[key])
            }
            byKey[key].items.push(item)
        }
        return out
    }

    function countdown(at) {
        let s = at - page.nowSeconds
        if (s <= 0) return "aired"
        let h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60)
        return h >= 24 ? "in " + Math.floor(h / 24) + "d " + (h % 24) + "h"
             : h > 0 ? "in " + h + "h " + m + "m" : "in " + m + "m"
    }

    actions: [
        Kirigami.Action {
            text: "Only shows I follow"
            icon.name: "view-filter-symbolic"
            checkable: true
            checked: page.followedOnly
            onTriggered: {
                page.followedOnly = !page.followedOnly
                backend.setLearnOption("schedule_followed", page.followedOnly ? "true" : "false")
            }
        }
    ]

    ColumnLayout {
        width: page.availableWidth
        spacing: Kirigami.Units.largeSpacing

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
            visible: !page.loading && page.days.length === 0
            icon.name: "clock-symbolic"
            text: page.error !== "" ? "Couldn't load the schedule"
                : page.followedOnly ? "Nothing you follow airs this week" : "Nothing airing this week"
            explanation: page.error !== "" ? page.error
                : page.followedOnly ? "Shows you're watching or planning on AniList show up here. Turn off \"Only shows I follow\" to see everything." : ""
        }

        Repeater {
            model: page.days

            ColumnLayout {
                id: daySection
                required property var modelData
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                RowLayout {
                    Layout.topMargin: Kirigami.Units.largeSpacing
                    spacing: Kirigami.Units.largeSpacing
                    Rectangle {
                        Layout.preferredWidth: 4
                        Layout.preferredHeight: dayHeading.implicitHeight
                        radius: 2
                        color: Kirigami.Theme.highlightColor
                    }
                    Kirigami.Heading { id: dayHeading; level: 2; text: daySection.modelData.label }
                    Controls.Label { text: daySection.modelData.date; opacity: 0.6 }
                }

                Repeater {
                    model: daySection.modelData.items

                    Rectangle {
                        id: row
                        required property var modelData
                        readonly property bool mine: modelData.following || modelData.planning
                        readonly property bool aired: modelData.airing_at <= page.nowSeconds
                        Layout.fillWidth: true
                        implicitHeight: rowLayout.implicitHeight + Kirigami.Units.smallSpacing * 2
                        radius: Kirigami.Units.smallSpacing
                        color: rowHover.hovered ? Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g,
                                                          Kirigami.Theme.highlightColor.b, 0.15)
                             : row.mine ? Kirigami.Theme.alternateBackgroundColor : "transparent"
                        border.width: row.mine ? 1 : 0
                        border.color: Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g,
                                              Kirigami.Theme.highlightColor.b, 0.5)
                        opacity: row.aired ? 0.55 : 1

                        HoverHandler { id: rowHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler {
                            onTapped: {
                                page.opening = true
                                backend.openAnilistAnime(row.modelData.anilist_id, row.modelData.title)
                            }
                        }

                        RowLayout {
                            id: rowLayout
                            anchors.fill: parent
                            anchors.margins: Kirigami.Units.smallSpacing
                            spacing: Kirigami.Units.largeSpacing

                            Controls.Label {
                                Layout.preferredWidth: Kirigami.Units.gridUnit * 3
                                horizontalAlignment: Text.AlignRight
                                font.bold: true
                                text: new Date(row.modelData.airing_at * 1000).toLocaleTimeString(Qt.locale(), "HH:mm")
                            }
                            Image {
                                Layout.preferredWidth: Kirigami.Units.gridUnit * 1.6
                                Layout.preferredHeight: Kirigami.Units.gridUnit * 2.4
                                source: row.modelData.poster_url
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                            }
                            Controls.Label {
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                text: row.modelData.title
                                font.bold: row.mine
                            }
                            Controls.Label {
                                visible: row.modelData.following || row.modelData.planning
                                text: row.modelData.following ? "Watching" : "Planning"
                                color: Kirigami.Theme.highlightColor
                                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                            }
                            Controls.Label {
                                Layout.preferredWidth: Kirigami.Units.gridUnit * 4
                                text: "Episode " + row.modelData.episode
                            }
                            Controls.Label {
                                Layout.preferredWidth: Kirigami.Units.gridUnit * 4.5
                                horizontalAlignment: Text.AlignRight
                                opacity: 0.7
                                text: page.countdown(row.modelData.airing_at)
                            }
                        }
                    }
                }
            }
        }
    }
}
