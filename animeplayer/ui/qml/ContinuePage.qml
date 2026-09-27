// Everything you're partway through, and nothing else: no search box, no
// filters, no presets. It used to be the Browse page opened on a "Continue
// Watching" preset, which meant Browse's controls were all there to poke at
// -- and poking at them changed the listing, or left Browse opening on
// Continue afterwards.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page

    AppTheming {}
    title: "Continue Watching"

    property var entries: []
    property bool opening: false
    property var menuEntry: null

    // Where you left off on this PC, then what AniList says you're watching.
    readonly property var here: page.entries.filter((e) => e.slug_id !== "")
    readonly property var fromAnilist: page.entries.filter((e) => e.slug_id === "")
    readonly property int columns: Math.max(1, Math.floor(page.availableWidth / (Kirigami.Units.gridUnit * 20)))
    readonly property real cellWidth: (page.availableWidth - (page.columns - 1) * Kirigami.Units.largeSpacing) / page.columns

    Component.onCompleted: page.entries = backend.continueWatchingAll()

    Connections {
        target: backend
        function onContinueWatchingChanged() { page.entries = backend.continueWatchingAll() }
        function onAnilistAnimeResolved(result) {
            if (!page.opening) return
            page.opening = false
            page.openSlug(result)
        }
        function onAnilistAnimeResolveFailed(title) {
            if (!page.opening) return
            page.opening = false
            showPassiveNotification("Couldn't find a stream for \"" + title + "\"")
        }
    }

    function openSlug(entry) {
        applicationWindow().pageStack.push(Qt.resolvedUrl("DetailPage.qml"), {
            anime: { slug_id: entry.slug_id, numeric_id: entry.numeric_id || entry.slug_id.split("-").pop(),
                     title: entry.title, poster_url: entry.poster_url || "", kind: entry.kind || "", rating: "" }
        })
    }
    function open(entry) {
        if (entry.slug_id) { page.openSlug(entry); return }
        page.opening = true
        backend.openAnilistAnime(entry.anilist_id, entry.title)
    }
    function timeLeft(entry) {
        if (!(entry.duration_seconds > 0)) return ""
        let left = Math.max(0, Math.round((entry.duration_seconds - entry.position_seconds) / 60))
        return left <= 1 ? " · almost done" : " · " + left + " min left"
    }

    Controls.Menu {
        id: entryMenu
        Kirigami.Theme.inherit: true
        Controls.MenuItem {
            text: "Remove from Continue Watching"
            icon.name: "edit-delete-symbolic"
            onTriggered: backend.removeFromContinueWatching(page.menuEntry.slug_id)
        }
        Controls.MenuItem {
            text: "Copy title"
            icon.name: "edit-copy-symbolic"
            onTriggered: applicationWindow().copyText(page.menuEntry.title)
        }
    }

    component Shelf: ColumnLayout {
        id: shelf
        property string heading
        property string note
        property var items: []
        property bool removable: false
        Layout.fillWidth: true
        visible: items.length > 0
        spacing: Kirigami.Units.largeSpacing

        RowLayout {
            spacing: Kirigami.Units.largeSpacing
            Rectangle {
                Layout.preferredWidth: 4
                Layout.preferredHeight: shelfHeading.implicitHeight
                radius: 2
                color: Kirigami.Theme.highlightColor
            }
            Kirigami.Heading { id: shelfHeading; level: 2; text: shelf.heading }
            Controls.Label { text: shelf.note; opacity: 0.6 }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: page.columns
            columnSpacing: Kirigami.Units.largeSpacing
            rowSpacing: Kirigami.Units.largeSpacing
            Repeater {
                model: shelf.items
                ResumeCard {
                    required property var modelData
                    // A share of the row, not fillWidth: a shelf with one show
                    // drew it the width of the page.
                    Layout.preferredWidth: page.cellWidth
                    Layout.maximumWidth: page.cellWidth
                    Layout.preferredHeight: Kirigami.Units.gridUnit * 8
                    posterUrl: modelData.poster_url || ""
                    title: modelData.title
                    subtitle: modelData.episode_number > 0
                              ? "Episode " + modelData.episode_number + page.timeLeft(modelData)
                              : "Not started yet"
                    watchedFraction: modelData.duration_seconds > 0
                        ? modelData.position_seconds / modelData.duration_seconds : 0
                    onClicked: page.open(modelData)
                    customMenu: shelf.removable
                    onContextMenuRequested: { page.menuEntry = modelData; entryMenu.popup() }
                }
            }
        }
    }

    ColumnLayout {
        width: page.availableWidth
        spacing: Kirigami.Units.gridUnit

        Kirigami.PlaceholderMessage {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.gridUnit * 3
            visible: page.entries.length === 0
            icon.name: "media-playback-start-symbolic"
            text: "Nothing in progress"
            explanation: "Shows you start watching show up here, ready to pick up where you left off."
        }

        Shelf {
            heading: "Where you left off"
            note: page.here.length + (page.here.length === 1 ? " show" : " shows") + " · right-click to remove"
            items: page.here
            removable: true
        }
        Shelf {
            heading: "Watching on AniList"
            note: "not started on this PC yet"
            items: page.fromAnilist
        }
    }
}
