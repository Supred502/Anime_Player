// Your shows, in tabs. Two are built in: Downloads (the download queue, and
// everything saved for offline watching) and Planning (the AniList list,
// when logged in). The rest are the user's own -- "Next 30 days", "With
// friends" -- made here or from a show's "+ Library" button.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page

    AppTheming {}
    title: "Library"

    // "downloads", "planning", or a user tab's id as a string.
    property string tab: "downloads"
    property var lists: []
    property var cards: []
    property var queue: []
    property var progress: ({})   // "episodeId:dub" -> fraction
    property bool loggedIn: false
    property bool opening: false

    readonly property var currentList: page.lists.find((l) => String(l.id) === page.tab) || null
    readonly property int columns: Math.max(2, Math.floor(page.availableWidth / (Kirigami.Units.gridUnit * 10)))
    readonly property real cellWidth: (page.availableWidth - (page.columns - 1) * Kirigami.Units.largeSpacing) / page.columns

    Component.onCompleted: {
        page.loggedIn = backend.isAnilistLoggedIn()
        let saved = backend.learnOption("library_tab")
        if (saved) page.tab = saved
        page.reload()
    }

    function reload() {
        page.lists = backend.libraryLists()
        if (page.tab !== "downloads" && page.tab !== "planning" && !page.currentList) page.tab = "downloads"
        if (page.tab === "downloads") {
            page.queue = backend.downloadQueue().concat(
                backend.allDownloads().filter((d) => d.status === "failed"))
            page.cards = backend.downloadedShows()
        } else if (page.tab === "planning") {
            page.queue = []
            page.cards = page.loggedIn ? backend.planningShows() : []
        } else {
            page.queue = []
            page.cards = backend.libraryItems(parseInt(page.tab))
        }
    }

    function showTab(tab) {
        page.tab = tab
        backend.setLearnOption("library_tab", tab)
        page.reload()
    }

    function formatSize(bytes) {
        if (bytes >= 1e9) return (bytes / 1e9).toFixed(1) + " GB"
        return Math.round(bytes / 1e6) + " MB"
    }

    function openShow(card) {
        if (card.slug_id) {
            applicationWindow().pageStack.push(Qt.resolvedUrl("DetailPage.qml"), {
                anime: {
                    slug_id: card.slug_id, numeric_id: card.numeric_id || card.slug_id.split("-").pop(),
                    title: card.title, poster_url: card.poster_url || "", kind: "", rating: ""
                }
            })
        } else if (card.anilist_id) {
            // An AniList entry: matched to the streaming source first.
            page.opening = true
            backend.openAnilistAnime(card.anilist_id, card.title)
        }
    }

    Connections {
        target: backend
        function onLibraryChanged() { page.reload() }
        function onDownloadsChanged() { if (page.tab === "downloads") page.reload() }
        function onDownloadProgress(episodeId, dub, fraction, bytes) {
            let next = Object.assign({}, page.progress)
            next[episodeId + ":" + dub] = fraction
            page.progress = next
        }
        function onAnilistPlanningChanged() { if (page.tab === "planning") page.reload() }
        function onAnilistAnimeResolved(result) {
            if (!page.opening) return
            page.opening = false
            page.openShow(result)
        }
        function onAnilistAnimeResolveFailed(title) {
            if (!page.opening) return
            page.opening = false
            showPassiveNotification("Couldn't find a stream for \"" + title + "\"")
        }
    }

    // New tab / rename, one dialog for both.
    property int renamingId: 0
    Controls.Dialog {
        id: nameDialog
        Kirigami.Theme.inherit: true
        parent: Controls.Overlay.overlay
        anchors.centerIn: parent
        modal: true
        title: page.renamingId ? "Rename tab" : "New library tab"
        standardButtons: Controls.Dialog.Ok | Controls.Dialog.Cancel
        onOpened: { nameField.forceActiveFocus(); nameField.selectAll() }
        onAccepted: {
            if (page.renamingId) {
                backend.renameLibraryList(page.renamingId, nameField.text)
            } else {
                let id = backend.createLibraryList(nameField.text)
                if (id) page.showTab(String(id))
            }
        }
        Controls.TextField {
            id: nameField
            implicitWidth: Kirigami.Units.gridUnit * 18
            placeholderText: "e.g. Next 30 days"
            onAccepted: nameDialog.accept()
        }
    }
    function newTab() { page.renamingId = 0; nameField.text = ""; nameDialog.open() }

    property var menuList: null
    Controls.Menu {
        id: tabMenu
        Kirigami.Theme.inherit: true
        Controls.MenuItem {
            text: "Rename"
            icon.name: "edit-rename-symbolic"
            onTriggered: {
                page.renamingId = page.menuList.id
                nameField.text = page.menuList.name
                nameDialog.open()
            }
        }
        Controls.MenuItem {
            text: "Delete tab"
            icon.name: "edit-delete-symbolic"
            onTriggered: deletePrompt.open()
        }
    }
    Kirigami.PromptDialog {
        id: deletePrompt
        title: "Delete \"" + (page.menuList ? page.menuList.name : "") + "\"?"
        subtitle: "The shows in it stay where they are everywhere else -- only this tab goes."
        standardButtons: Kirigami.Dialog.NoButton
        customFooterActions: [
            Kirigami.Action {
                text: "Delete"
                icon.name: "edit-delete-symbolic"
                onTriggered: {
                    backend.deleteLibraryList(page.menuList.id)
                    deletePrompt.close()
                }
            },
            Kirigami.Action {
                text: "Keep it"
                icon.name: "dialog-cancel-symbolic"
                onTriggered: deletePrompt.close()
            }
        ]
    }

    ColumnLayout {
        width: page.availableWidth
        spacing: Kirigami.Units.largeSpacing

        // ---- The tab strip -------------------------------------------------
        Flow {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            AppButton {
                text: "Downloads"
                icon.name: "folder-download-symbolic"
                checkable: true
                checked: page.tab === "downloads"
                onClicked: page.showTab("downloads")
            }
            AppButton {
                text: "Planning"
                icon.name: "view-list-details-symbolic"
                checkable: true
                checked: page.tab === "planning"
                onClicked: page.showTab("planning")
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Your AniList Planning list"
            }
            Repeater {
                model: page.lists
                AppButton {
                    required property var modelData
                    text: modelData.name + "  " + modelData.count
                    checkable: true
                    checked: page.tab === String(modelData.id)
                    onClicked: page.showTab(String(modelData.id))
                    TapHandler {
                        acceptedButtons: Qt.RightButton
                        onTapped: { page.menuList = modelData; tabMenu.popup() }
                    }
                    Controls.ToolTip.visible: hovered
                    Controls.ToolTip.text: "Right-click to rename or delete"
                    Controls.ToolTip.delay: 800
                }
            }
            AppButton {
                text: "New tab"
                icon.name: "list-add-symbolic"
                onClicked: page.newTab()
            }
        }

        // ---- Downloads: the queue -------------------------------------------
        Kirigami.Heading {
            level: 3
            visible: page.tab === "downloads" && page.queue.length > 0
            text: "Download queue"
        }
        Repeater {
            model: page.tab === "downloads" ? page.queue : []

            Rectangle {
                id: row
                required property var modelData
                required property int index
                readonly property bool active: modelData.status === "downloading"
                readonly property bool failed: modelData.status === "failed"
                // Position among the ones still waiting (the running one is first).
                readonly property int waitingIndex: page.queue.length && page.queue[0].status === "downloading"
                                                    ? index - 1 : index
                Layout.fillWidth: true
                implicitHeight: rowLayout.implicitHeight + Kirigami.Units.largeSpacing * 2
                radius: Kirigami.Units.smallSpacing * 2
                color: Kirigami.Theme.alternateBackgroundColor

                RowLayout {
                    id: rowLayout
                    anchors.fill: parent
                    anchors.margins: Kirigami.Units.largeSpacing
                    spacing: Kirigami.Units.largeSpacing

                    Image {
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 2
                        Layout.preferredHeight: Kirigami.Units.gridUnit * 3
                        source: row.modelData.poster_url
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing
                        Controls.Label {
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                            font.bold: true
                            text: row.modelData.title + " · Episode " + row.modelData.episode_number
                                  + (row.modelData.dub ? " (dub)" : "")
                        }
                        Controls.Label {
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                            opacity: 0.7
                            color: row.failed ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
                            text: row.active
                                  ? "Downloading " + Math.round((page.progress[row.modelData.episode_id + ":" + row.modelData.dub] || 0) * 100) + "%"
                                  : row.failed ? "Failed: " + row.modelData.message
                                  : row.waitingIndex === 0 ? "Next up" : "Waiting (" + (row.waitingIndex + 1) + " in line)"
                        }
                        // Drawn rather than a Controls.ProgressBar: the Breeze
                        // one throws on every update inside a Repeater that
                        // is rebuilt as the queue changes.
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 4
                            visible: row.active
                            radius: 2
                            color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                                           Kirigami.Theme.textColor.b, 0.15)
                            Rectangle {
                                height: parent.height
                                radius: parent.radius
                                width: parent.width * (page.progress[row.modelData.episode_id + ":" + row.modelData.dub] || 0)
                                color: Kirigami.Theme.highlightColor
                            }
                        }
                    }
                    Controls.ToolButton {
                        Kirigami.Theme.inherit: true
                        visible: !row.active && !row.failed && row.waitingIndex > 0
                        icon.name: "go-top-symbolic"
                        onClicked: backend.moveDownload(row.modelData.episode_id, row.modelData.dub, 0)
                        Controls.ToolTip.visible: hovered
                        Controls.ToolTip.text: "Download this next"
                    }
                    Controls.ToolButton {
                        Kirigami.Theme.inherit: true
                        visible: !row.active && !row.failed && row.waitingIndex > 0
                        icon.name: "go-up-symbolic"
                        onClicked: backend.moveDownload(row.modelData.episode_id, row.modelData.dub, row.waitingIndex - 1)
                        Controls.ToolTip.visible: hovered
                        Controls.ToolTip.text: "Move up"
                    }
                    Controls.ToolButton {
                        Kirigami.Theme.inherit: true
                        visible: !row.active && !row.failed
                                 && row.index < page.queue.filter((d) => d.status !== "failed").length - 1
                        icon.name: "go-down-symbolic"
                        onClicked: backend.moveDownload(row.modelData.episode_id, row.modelData.dub, row.waitingIndex + 1)
                        Controls.ToolTip.visible: hovered
                        Controls.ToolTip.text: "Move down"
                    }
                    Controls.ToolButton {
                        Kirigami.Theme.inherit: true
                        visible: row.failed
                        text: "Retry"
                        icon.name: "view-refresh-symbolic"
                        display: Controls.AbstractButton.TextBesideIcon
                        onClicked: backend.retryDownload(row.modelData.episode_id, row.modelData.dub)
                    }
                    Controls.ToolButton {
                        Kirigami.Theme.inherit: true
                        icon.name: "dialog-cancel-symbolic"
                        onClicked: backend.cancelDownload(row.modelData.episode_id, row.modelData.dub)
                        Controls.ToolTip.visible: hovered
                        Controls.ToolTip.text: row.failed ? "Remove" : "Cancel"
                    }
                }
            }
        }

        Kirigami.Heading {
            level: 3
            Layout.topMargin: page.queue.length > 0 ? Kirigami.Units.largeSpacing : 0
            visible: page.tab === "downloads" && page.cards.length > 0
            text: "Saved for offline watching"
        }

        // ---- Placeholders ---------------------------------------------------
        Kirigami.PlaceholderMessage {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.gridUnit * 3
            visible: page.cards.length === 0 && page.queue.length === 0
            icon.name: page.tab === "downloads" ? "folder-download-symbolic"
                     : page.tab === "planning" ? "view-list-details-symbolic" : "view-media-playlist-symbolic"
            text: page.tab === "downloads" ? "Nothing downloaded"
                : page.tab === "planning" ? (page.loggedIn ? "Your Planning list is empty" : "Log in to AniList to see your Planning list")
                : "This tab is empty"
            explanation: page.tab === "downloads"
                ? "On a show's page, press Save season, or the download button on an episode."
                : page.tab === "planning"
                  ? (page.loggedIn ? "Press Plan to Watch on any show to add it." : "Settings → AniList.")
                  : "Open a show and press + Library to add it here."
        }

        // ---- The cards --------------------------------------------------------
        GridLayout {
            Layout.fillWidth: true
            columns: page.columns
            columnSpacing: Kirigami.Units.largeSpacing
            rowSpacing: Kirigami.Units.largeSpacing

            Repeater {
                model: page.cards
                Item {
                    id: cell
                    required property var modelData
                    // A fixed share of the row, not fillWidth: a tab with one
                    // show in it drew that one card the width of the page.
                    Layout.preferredWidth: page.cellWidth
                    Layout.maximumWidth: page.cellWidth
                    Layout.preferredHeight: card.heightForWidth(page.cellWidth)

                    AnimeCard {
                        id: card
                        width: parent.width
                        height: parent.height
                        posterUrl: cell.modelData.poster_url || ""
                        title: cell.modelData.title
                        subtitle: page.tab === "downloads"
                                  ? cell.modelData.count + (cell.modelData.count === 1 ? " episode · " : " episodes · ")
                                    + page.formatSize(cell.modelData.bytes)
                                  : ""
                        onClicked: page.openShow(cell.modelData)
                    }
                    // Taking a show out of one of your own tabs.
                    Controls.ToolButton {
                        Kirigami.Theme.inherit: true
                        anchors.top: parent.top
                        anchors.right: parent.right
                        anchors.margins: Kirigami.Units.smallSpacing
                        visible: page.currentList !== null && card.hovered
                        icon.name: "dialog-cancel-symbolic"
                        background: Rectangle { radius: height / 2; color: Qt.rgba(0, 0, 0, 0.65) }
                        onClicked: backend.removeFromLibrary(page.currentList.id, cell.modelData.slug_id)
                        Controls.ToolTip.visible: hovered
                        Controls.ToolTip.text: "Remove from " + (page.currentList ? page.currentList.name : "")
                    }
                }
            }
        }
    }
}
