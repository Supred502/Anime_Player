// The application window: its own titlebar, and its own navigation.
//
// Frameless, with the window buttons drawn into the same bar as the nav --
// the way Brave and friends do it. A separate system titlebar above a nav bar
// is two rows of chrome doing one row's work.
//
// Dragging and resizing are handed to the compositor through WindowChrome
// (see ui/window_chrome.py). A client cannot position itself on Wayland, so
// moving the window by assigning x/y from a MouseArea does nothing at all
// there; startSystemMove is the only thing that works, and it also keeps
// snapping and tiling behaving like every other window.
//
// This is a component rather than part of Main.qml because the live E2E
// drivers (_Test*Real.qml) each open their own window, and chrome only
// Main.qml had would mean every screenshot showed a different app.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root
    title: "Anime Player"
    width: 1280
    height: 800
    flags: Qt.Window | Qt.FramelessWindowHint

    // Which nav entry is lit. Set by the go* functions rather than derived
    // from the page stack, because pushing a detail page on top of Browse
    // should not un-light Browse.
    property string section: "home"

    readonly property bool maximised: root.visibility === Window.Maximized
                                      || root.visibility === Window.FullScreen

    // Set to false by the player when it goes fullscreen. The nav bar is the
    // window's own header, not part of any page, so a page hiding its own
    // toolbar left this one sitting across the top of the video.
    property bool chromeVisible: true

    // Every clickable thing in the nav bar is this tall -- the logo, the nav
    // entries and the window buttons. They were three different heights
    // before, which read as a row that had been assembled rather than
    // designed.
    readonly property int navItemHeight: Math.round(Kirigami.Units.gridUnit * 1.9)

    // The accent has to be painted onto the window's own root item: the
    // header is a sibling of the whole page stack, so nothing a page sets can
    // reach it. Pages paint themselves (see AppTheming.qml).
    // item -> its surface colours before "Pure black" (see AppTheming.applyTo).
    property var themeSurfaces: new WeakMap()
    AppTheming { id: windowTheming; targets: [root.windowRoot] }
    // Again when the page changes: each page brings its own title bar,
    // built after the last pass (it stayed grey with black surfaces on).
    Connections {
        target: root.pageStack
        function onCurrentItemChanged() { Qt.callLater(windowTheming.apply) }
    }

    // The top of the item chain -- the ancestor the header, the page stack
    // and the popup overlay all share. Walked rather than reached through
    // contentItem.parent.parent, which is the same thing spelled fragilely.
    readonly property Item windowRoot: {
        let node = root.contentItem
        while (node && node.parent) node = node.parent
        return node
    }

    // This app is a linear Home -> Detail -> Player stack, not a
    // master-detail browser, so force single-column navigation. Without this,
    // Kirigami's PageRow keeps previous pages visible side-by-side as
    // "columns" once the window is wide enough (its default adaptive
    // behavior), which reads as a stray sidebar here.
    pageStack.columnView.columnResizeMode: Kirigami.ColumnView.SingleColumn

    // No global drawer: the nav bar below replaces it.
    globalDrawer: null

    function goTo(name, file, properties) {
        root.section = name
        // clear() then push(), not replace(): replace() only swaps the top of
        // the stack, so going Home from a detail page three deep would leave
        // the pages underneath it in the back history.
        root.pageStack.clear()
        return root.pageStack.push(Qt.resolvedUrl(file), properties || ({}))
    }

    function goHome() { return root.goTo("home", "HomePage.qml") }
    // Seasonal's two tabs (see SeasonTabs.qml); no tab given, the last one.
    function goSeasonal(tab) {
        if (tab) backend.setLearnOption("seasonal_tab", tab)
        else tab = backend.learnOption("seasonal_tab") || "season"
        return root.goTo("seasonal", tab === "week" ? "SchedulePage.qml" : "SeasonalPage.qml")
    }
    function goBrowse(properties) { return root.goTo("browse", "BrowsePage.qml", properties) }
    function goSettings() { return root.goTo("settings", "SettingsPage.qml") }
    // Its own section rather than a Browse preset arrived at sideways, so the
    // nav entry stays lit while you are looking at it.
    function goContinue() {
        return root.goTo("continue", "ContinuePage.qml")
    }

    // Copying text, for anything in the app. A hidden TextEdit is the one
    // route to the clipboard QML has without a helper object.
    TextEdit { id: clipboardHelper; visible: false }
    function copyText(text) {
        clipboardHelper.text = text
        clipboardHelper.selectAll()
        clipboardHelper.copy()
        root.showPassiveNotification(text.length > 60 || text.indexOf("\n") >= 0
                                     ? "Copied" : "Copied \"" + text + "\"")
    }

    // Right-click on any anime card. One menu for the whole app rather than
    // one per card: a shelf page has hundreds of cards.
    property string cardMenuTitle: ""
    // info (optional): { anilist_id, slug_id, numeric_id, poster_url } --
    // whatever the card knows; the rest is looked up (see quickAddToLibrary).
    // source (optional): the card, so the menu closes if it scrolls away.
    property var cardMenuInfo: ({})
    property Item cardMenuSource: null
    property point cardMenuSourceAt: Qt.point(0, 0)
    property var libraryTabs: []
    function showCardMenu(title, info, source) {
        root.cardMenuTitle = title
        root.cardMenuInfo = Object.assign({ title: title }, info || {})
        root.cardMenuSource = source || null
        if (source) root.cardMenuSourceAt = source.mapToItem(null, 0, 0)
        root.libraryTabs = backend.libraryLists()
        root.hidePreview()
        cardMenu.popup()
    }
    // A menu open over a card stays with the card: scrolling the card away
    // closes it, rather than leaving it floating over something else until
    // the next click.
    Timer {
        interval: 80
        repeat: true
        running: cardMenu.opened && root.cardMenuSource !== null
        onTriggered: {
            let card = root.cardMenuSource
            let at = card && card.visible ? card.mapToItem(null, 0, 0) : null
            if (!at || Math.abs(at.x - root.cardMenuSourceAt.x) > 2 || Math.abs(at.y - root.cardMenuSourceAt.y) > 2)
                cardMenu.close()
        }
    }
    Connections {
        target: backend
        function onQuickActionDone(message) { root.showPassiveNotification(message) }
    }
    Controls.Menu {
        id: cardMenu
        Kirigami.Theme.inherit: true
        Controls.MenuItem {
            text: "Add to Planning"
            icon.name: "list-add-symbolic"
            onTriggered: backend.quickAddToPlanning(root.cardMenuInfo.anilist_id || 0, root.cardMenuTitle)
        }
        Controls.Menu {
            id: libraryMenu
            title: "Add to Library"
            Kirigami.Theme.inherit: true
            Instantiator {
                model: root.libraryTabs
                delegate: Controls.MenuItem {
                    required property var modelData
                    text: modelData.name
                    onTriggered: backend.quickAddToLibrary(modelData.id, root.cardMenuInfo)
                }
                onObjectAdded: (index, object) => libraryMenu.insertItem(index, object)
                onObjectRemoved: (index, object) => libraryMenu.removeItem(object)
            }
            Controls.MenuSeparator { visible: root.libraryTabs.length > 0 }
            Controls.MenuItem {
                text: "New tab..."
                icon.name: "list-add-symbolic"
                onTriggered: { newTabField.text = ""; newTabDialog.open() }
            }
        }
        Controls.MenuSeparator {}
        Controls.MenuItem {
            text: "Copy title"
            icon.name: "edit-copy-symbolic"
            onTriggered: root.copyText(root.cardMenuTitle)
        }
    }
    // The same tabs on their own, under a button (the spotlight's Library).
    function showLibraryMenu(title, info, button) {
        root.cardMenuTitle = title
        root.cardMenuInfo = Object.assign({ title: title }, info || {})
        root.libraryTabs = backend.libraryLists()
        root.hidePreview()
        libraryOnlyMenu.popup(button, 0, button.height)
    }
    Controls.Menu {
        id: libraryOnlyMenu
        Kirigami.Theme.inherit: true
        Instantiator {
            model: root.libraryTabs
            delegate: Controls.MenuItem {
                required property var modelData
                text: modelData.name
                onTriggered: backend.quickAddToLibrary(modelData.id, root.cardMenuInfo)
            }
            onObjectAdded: (index, object) => libraryOnlyMenu.insertItem(index, object)
            onObjectRemoved: (index, object) => libraryOnlyMenu.removeItem(object)
        }
        Controls.MenuSeparator { visible: root.libraryTabs.length > 0 }
        Controls.MenuItem {
            text: "New tab..."
            icon.name: "list-add-symbolic"
            onTriggered: { newTabField.text = ""; newTabDialog.open() }
        }
    }
    Controls.Dialog {
        id: newTabDialog
        Kirigami.Theme.inherit: true
        parent: Controls.Overlay.overlay
        anchors.centerIn: parent
        modal: true
        title: "New library tab"
        standardButtons: Controls.Dialog.Ok | Controls.Dialog.Cancel
        onOpened: newTabField.forceActiveFocus()
        onAccepted: {
            let id = backend.createLibraryList(newTabField.text)
            if (id) backend.quickAddToLibrary(id, root.cardMenuInfo)
        }
        Controls.TextField {
            id: newTabField
            implicitWidth: Kirigami.Units.gridUnit * 18
            placeholderText: "e.g. Next 30 days"
            onAccepted: newTabDialog.accept()
        }
    }

    // An episode picked on the phone: open the show, then play it -- the
    // same two pages a click on the PC goes through, so Back behaves the
    // same afterwards.
    Connections {
        target: backend
        function onRemoteCommand(cmd, args) {
            if (cmd !== "play_episode" || !args) return
            let anime = {
                slug_id: args.slug_id, numeric_id: args.numeric_id, title: args.title,
                poster_url: args.poster_url || "", kind: "", rating: ""
            }
            root.goTo("browse", "DetailPage.qml", { anime: anime })
            root.pageStack.push(Qt.resolvedUrl("PlayerPage.qml"), {
                anime: anime, episodeId: args.episode_id,
                episodeNumber: args.number, dub: !!args.dub
            })
        }
    }

    // Opens a show at an episode and a second -- the Words page's "Watch
    // the line". The episode's id comes from the show's episode list, so
    // the detail page opens first and plays it once the list arrives.
    //
    // Deferred: it's called from the Words page, and goTo() clears the page
    // stack -- which destroys that page while its own click handler is still
    // running ("attempted to evaluate a function in an invalid context").
    function openAt(anime, episodeNumber, seconds, section, dub) {
        Qt.callLater(root.openAtNow, anime, episodeNumber, seconds, section || "words", dub)
    }
    function openAtNow(anime, episodeNumber, seconds, section, dub) {
        let detail = root.goTo(section, "DetailPage.qml", { anime: anime })
        detail.playWhenLoaded = dub === undefined ? { number: episodeNumber, at: seconds }
                                                  : { number: episodeNumber, at: seconds, dub: dub }
    }

    // The mini player (see MiniPlayer.qml): one at a time, over every page,
    // gone the moment a full player opens.
    property var miniShow: null
    readonly property Item miniPlayer: miniLoader.item
        || (miniWindowLoader.item ? miniWindowLoader.item.player : null)
    function startMiniPlayer(show) {
        root.miniShow = null
        root.miniShow = show
    }
    Connections {
        target: root.pageStack
        function onCurrentItemChanged() {
            let page = root.pageStack.currentItem
            if (root.miniShow && page && typeof page.toMiniPlayer === "function") root.miniShow = null
        }
    }
    // In its own window over other apps where that works (not in the
    // Deck's Gaming Mode, which shows one window at a time).
    readonly property bool miniFloats: windowChrome.separateWindowsWork() && testMode !== "mini-inside"
    function miniExpand(position) {
        let s = root.miniShow
        root.miniShow = null
        // Through the show's page, as "Watch the line" does: the player
        // needs the episode list behind it for next/previous.
        root.openAt(s.anime, s.episodeNumber, position, "browse", s.dub)
        // From another app, the full player comes to the front.
        if (root.visibility === Window.Minimized) root.showNormal()
        root.raise()
        root.requestActivate()
    }
    // The main window closing ends the app, the floating one included:
    // otherwise Qt keeps running for as long as any window is open.
    onClosing: if (root.miniShow !== null) root.miniShow = null
    // The media widget's "raise" (clicking it in KDE's panel).
    Connections {
        target: mediaSession
        function onRaiseRequested() {
            if (root.visibility === Window.Minimized) root.showNormal()
            root.raise()
            root.requestActivate()
        }
    }
    Loader {
        id: miniWindowLoader
        active: root.miniShow !== null && root.miniFloats
        sourceComponent: Window {
            id: miniWindow
            title: "Anime Player \u2013 mini player"
            flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            // A window of its own, not the main window's child: as a child
            // (Qt makes one declared inside another so), clicking it --
            // to move it, say -- brought the whole app to the front.
            transientParent: null
            color: "black"
            minimumWidth: 240
            minimumHeight: 135
            // Its last size (and, where an app may place its windows, its
            // last spot), else a corner of the screen.
            readonly property var saved: {
                try { return JSON.parse(backend.learnOption("mini_geometry") || "{}") } catch (e) { return {} }
            }
            width: saved.w || Kirigami.Units.gridUnit * 24
            height: saved.h || Math.round((saved.w || Kirigami.Units.gridUnit * 24) * 9 / 16)
            x: saved.x !== undefined ? saved.x : Screen.desktopAvailableWidth - width - Kirigami.Units.gridUnit * 2
            y: saved.y !== undefined ? saved.y : Screen.desktopAvailableHeight - height - Kirigami.Units.gridUnit * 2
            visible: true
            onClosing: root.miniShow = null
            Component.onCompleted: keepAboveTimer.start()
            // Once it's on screen (KWin can only find a window that's there).
            Timer {
                id: keepAboveTimer
                interval: 250
                onTriggered: windowChrome.keepAbove(miniWindow, miniWindow.width, miniWindow.height)
            }
            onWidthChanged: { geometrySave.restart(); aspectFix.restart(); keepOnScreen.restart() }
            onHeightChanged: { geometrySave.restart(); aspectFix.restart(); keepOnScreen.restart() }
            // Back to 16:9 once a resize has settled: the compositor resizes
            // freely, the picture doesn't.
            Timer {
                id: aspectFix
                interval: 300
                onTriggered: {
                    let h = Math.round(miniWindow.width * 9 / 16)
                    if (Math.abs(miniWindow.height - h) > 1) miniWindow.height = h
                }
            }
            onXChanged: { geometrySave.restart(); keepOnScreen.restart() }
            onYChanged: { geometrySave.restart(); keepOnScreen.restart() }
            Component.onDestruction: windowChrome.releaseKeepAbove()
            // Where the app places its own windows (Windows, X11): moved or
            // resized partly off the screen, it's pulled back against the
            // edge once it has stayed put a moment. (On KDE's Wayland, KWin
            // does this -- see window_chrome.keepAbove.)
            Timer {
                id: keepOnScreen
                interval: 600
                onTriggered: {
                    if (Qt.platform.pluginName === "wayland") return
                    let left = miniWindow.screen.virtualX, top = miniWindow.screen.virtualY
                    let right = left + miniWindow.screen.width, bottom = top + miniWindow.screen.height
                    let x = Math.min(Math.max(miniWindow.x, left), right - miniWindow.width)
                    let y = Math.min(Math.max(miniWindow.y, top), bottom - miniWindow.height)
                    if (x !== miniWindow.x) miniWindow.x = x
                    if (y !== miniWindow.y) miniWindow.y = y
                }
            }
            Timer {
                id: geometrySave
                interval: 800
                onTriggered: {
                    let g = { w: miniWindow.width, h: miniWindow.height }
                    // Wayland never says where a window is (x and y stay 0).
                    if (Qt.platform.pluginName !== "wayland") { g.x = miniWindow.x; g.y = miniWindow.y }
                    backend.setLearnOption("mini_geometry", JSON.stringify(g))
                }
            }
            property Item player: floatingMini
            MiniPlayer {
                id: floatingMini
                anchors.fill: parent
                floating: true
                show: root.miniShow
                onClosed: root.miniShow = null
                onExpand: (position) => root.miniExpand(position)
                onMoveRequested: windowChrome.startMove(miniWindow)
                onResizeRequested: windowChrome.startResize(miniWindow, "topleft")
            }
        }
    }
    Loader {
        id: miniLoader
        active: root.miniShow !== null && !root.miniFloats
        parent: root.contentItem
        z: 900
        anchors.right: parent ? parent.right : undefined
        anchors.bottom: parent ? parent.bottom : undefined
        anchors.margins: Kirigami.Units.gridUnit
        sourceComponent: MiniPlayer {
            show: root.miniShow
            onClosed: root.miniShow = null
            onExpand: (position) => root.miniExpand(position)
        }
    }

    // Asked once, right after the last episode of a finished show (see
    // backend._maybe_ask_for_rating). On the window, not the player page: the
    // player may be on its way out by the time the answer comes.
    property int ratingAnilistId: 0
    property string ratingTitle: ""
    property real ratingScore: 0
    Connections {
        target: backend
        function onAskForRating(anilistId, title, score) {
            root.ratingAnilistId = anilistId
            root.ratingTitle = title
            root.ratingScore = score
            ratingDialog.open()
        }
    }
    Controls.Dialog {
        id: ratingDialog
        Kirigami.Theme.inherit: true
        parent: Controls.Overlay.overlay
        anchors.centerIn: parent
        modal: true
        title: "You finished " + root.ratingTitle
        standardButtons: Controls.Dialog.Close
        ColumnLayout {
            spacing: Kirigami.Units.largeSpacing
            Controls.Label { text: "How would you rate it? It goes straight to your AniList." }
            RatingStars {
                Layout.alignment: Qt.AlignHCenter
                score: root.ratingScore
                starSize: Kirigami.Units.iconSizes.medium
                onPicked: (score) => {
                    root.ratingScore = score
                    backend.setListScore(root.ratingAnilistId, score)
                    ratingCloser.restart()
                }
            }
        }
        // A moment to see the stars land before it goes.
        Timer { id: ratingCloser; interval: 700; onTriggered: ratingDialog.close() }
    }

    // A new version on GitHub (see updates.py). A card in the corner rather
    // than a dialog: it can wait until the episode is over, and it stays out
    // of the way of the video (hidden while the player is fullscreen).
    property string updateVersion: ""
    property string updateNotes: ""
    property string updateHow: ""
    property real updateFraction: -1   // -1: not downloading
    property string updateError: ""
    Connections {
        target: backend
        function onUpdateAvailable(version, notes, how) {
            root.updateVersion = version
            root.updateNotes = notes
            root.updateHow = how
            root.updateError = ""
            root.updateFraction = -1
            updateCard.open()
        }
        function onUpdateProgress(fraction) { root.updateFraction = fraction }
        function onUpdateFailed(message) {
            root.updateFraction = -1
            root.updateError = message
            updateCard.open()
        }
    }
    Controls.Popup {
        id: updateCard
        Kirigami.Theme.inherit: true
        parent: Controls.Overlay.overlay
        x: parent ? parent.width - width - Kirigami.Units.gridUnit : 0
        y: parent ? parent.height - height - Kirigami.Units.gridUnit : 0
        width: Kirigami.Units.gridUnit * 22
        modal: false
        focus: false
        closePolicy: Controls.Popup.NoAutoClose
        visible: opened && root.chromeVisible
        padding: Kirigami.Units.largeSpacing

        background: Rectangle {
            radius: Kirigami.Units.smallSpacing * 2
            color: Kirigami.Theme.alternateBackgroundColor
            border.color: Kirigami.Theme.highlightColor
            border.width: 1
        }

        contentItem: ColumnLayout {
            // GamepadNav leaves it out of the popups that take the controller.
            objectName: "updateCard"
            spacing: Kirigami.Units.smallSpacing
            RowLayout {
                Layout.fillWidth: true
                Kirigami.Icon {
                    source: "update-none-symbolic"
                    color: Kirigami.Theme.highlightColor
                    Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                    Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                }
                Kirigami.Heading {
                    Layout.fillWidth: true
                    level: 4
                    text: "Anime Player " + root.updateVersion + " is out"
                    wrapMode: Text.WordWrap
                }
            }
            Controls.Label {
                Layout.fillWidth: true
                visible: root.updateError === ""
                wrapMode: Text.WordWrap
                opacity: 0.8
                text: root.updateHow === "installer" || root.updateHow === "flatpak"
                      ? "It downloads in the background, then the app restarts on the new version."
                      : root.updateHow === "git"
                        ? "Pulls the new code with git, then restarts."
                        : "Get it from the release page."
            }
            Controls.Label {
                Layout.fillWidth: true
                visible: root.updateError !== ""
                wrapMode: Text.WordWrap
                color: Kirigami.Theme.negativeTextColor
                text: "Update failed: " + root.updateError
            }
            Controls.ScrollView {
                id: notesView
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(notesText.implicitHeight, Kirigami.Units.gridUnit * 10)
                visible: notesShown && root.updateNotes !== ""
                property bool notesShown: false
                Controls.Label {
                    id: notesText
                    width: notesView.availableWidth
                    wrapMode: Text.WordWrap
                    textFormat: Text.MarkdownText
                    text: root.updateNotes
                }
            }
            Controls.ProgressBar {
                Layout.fillWidth: true
                visible: root.updateFraction >= 0
                value: Math.max(0, root.updateFraction)
            }
            RowLayout {
                Layout.fillWidth: true
                visible: root.updateFraction < 0
                Controls.ToolButton {
                    Kirigami.Theme.inherit: true
                    visible: root.updateNotes !== ""
                    text: notesView.notesShown ? "Hide what's new" : "What's new"
                    onClicked: notesView.notesShown = !notesView.notesShown
                }
                Item { Layout.fillWidth: true }
                Controls.ToolButton {
                    Kirigami.Theme.inherit: true
                    text: "Later"
                    onClicked: { backend.dismissUpdate(); updateCard.close() }
                }
                AppButton {
                    text: root.updateError !== "" ? "Try again" : (root.updateHow === "page" ? "Open page" : "Update now")
                    accented: true
                    onClicked: {
                        root.updateError = ""
                        if (root.updateHow === "page") updateCard.close()
                        else root.updateFraction = 0
                        backend.installUpdate()
                    }
                }
            }
        }
    }

    // F11: the whole app fullscreen with no nav bar, as browsers do. On the
    // player it is the player's own fullscreen, which already hides the bar.
    property bool appFullscreen: false
    property bool wasMaximisedBeforeFullscreen: false
    function toggleAppFullscreen() {
        let page = root.pageStack.currentItem
        if (page && typeof page.toggleFullscreen === "function") { page.toggleFullscreen(); return }
        root.appFullscreen = !root.appFullscreen
        if (root.appFullscreen) {
            root.wasMaximisedBeforeFullscreen = root.visibility === Window.Maximized
            root.showFullScreen()
            root.showPassiveNotification("Press F11 to leave full screen")
        } else if (root.wasMaximisedBeforeFullscreen) {
            root.showMaximized()
        } else {
            root.showNormal()
        }
        root.chromeVisible = !root.appFullscreen
    }
    Shortcut {
        sequence: "F11"
        context: Qt.ApplicationShortcut
        onActivated: root.toggleAppFullscreen()
    }

    // ---- Hover previews (see AnimeCard) -------------------------------------
    // One small card beside the poster the pointer rests on. Never covers
    // the poster, never takes clicks, and goes the moment the pointer leaves.
    property var previewCard: null
    property var previewInfo: ({})
    property string previewKey: ""
    property bool previewsOn: true
    function showPreview(card, poster) {
        // Not over an open menu.
        if (!root.previewsOn || !card.title || cardMenu.opened || libraryOnlyMenu.opened) return
        root.previewCard = card
        root.previewKey = card.anilistId > 0 ? "id:" + card.anilistId : "title:" + card.title
        root.previewInfo = { title: card.title }
        backend.requestPreview(root.previewKey, card.anilistId, card.title)
        let overlay = preview.parent
        let p = poster.mapToItem(overlay, 0, 0)
        let gap = Kirigami.Units.largeSpacing
        preview.x = p.x + poster.width + gap + preview.width < overlay.width
                    ? p.x + poster.width + gap : Math.max(gap, p.x - preview.width - gap)
        preview.y = Math.max(gap, Math.min(p.y, overlay.height - preview.height - gap))
        preview.shown = true
    }
    function hidePreview(card) {
        if (card === undefined || card === root.previewCard) {
            preview.shown = false
            root.previewCard = null
        }
    }
    Connections {
        target: backend
        function onPreviewReady(key, info) { if (key === root.previewKey && info.title) root.previewInfo = info }
    }
    Connections {
        target: root.pageStack
        function onCurrentItemChanged() { root.hidePreview() }
    }
    Rectangle {
        id: preview
        property bool shown: false
        parent: Controls.Overlay.overlay
        z: 950
        width: Kirigami.Units.gridUnit * 16
        height: previewColumn.implicitHeight + Kirigami.Units.largeSpacing * 2
        radius: Kirigami.Units.smallSpacing * 2
        color: Kirigami.Theme.alternateBackgroundColor
        border.width: 1
        border.color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.12)
        visible: opacity > 0
        opacity: shown ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 90 } }
        // Nothing in here takes the pointer, so the poster underneath stays
        // hovered and the preview never gets in the way.

        ColumnLayout {
            id: previewColumn
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.smallSpacing
            Controls.Label {
                Layout.fillWidth: true
                text: root.previewInfo.title || ""
                font.bold: true
                wrapMode: Text.WordWrap
            }
            Controls.Label {
                Layout.fillWidth: true
                visible: text !== ""
                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                text: {
                    let i = root.previewInfo, parts = []
                    if (i.score > 0) parts.push("\u2605 " + (i.score / 10).toFixed(1))
                    if (i.format) parts.push(i.format)
                    if (i.episodes > 0) parts.push(i.episodes + (i.episodes === 1 ? " episode" : " episodes"))
                    let lists = { CURRENT: "Watching", PLANNING: "Planning", COMPLETED: "Completed",
                                  PAUSED: "Paused", DROPPED: "Dropped", REPEATING: "Rewatching" }
                    if (i.list_status && lists[i.list_status]) parts.push(lists[i.list_status])
                    return parts.join("  ·  ")
                }
            }
            Controls.Label {
                Layout.fillWidth: true
                visible: text !== ""
                text: (root.previewInfo.genres || []).join(", ")
                color: Kirigami.Theme.highlightColor
                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                wrapMode: Text.WordWrap
            }
            Controls.Label {
                Layout.fillWidth: true
                visible: text !== ""
                text: root.previewInfo.description || ""
                wrapMode: Text.WordWrap
                maximumLineCount: 6
                elide: Text.ElideRight
                opacity: 0.8
                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
            }
        }
    }

    // First launch after an update: what changed (see backend's
    // _maybe_show_whats_new).
    Connections {
        target: backend
        function onWhatsNew(version, notes) {
            whatsNewDialog.title = "What's new in Anime Player " + version
            whatsNewText.text = notes
            whatsNewDialog.open()
        }
    }
    Controls.Dialog {
        id: whatsNewDialog
        Kirigami.Theme.inherit: true
        parent: Controls.Overlay.overlay
        anchors.centerIn: parent
        modal: true
        width: Math.min(parent ? parent.width - Kirigami.Units.gridUnit * 2 : 600, Kirigami.Units.gridUnit * 30)
        standardButtons: Controls.Dialog.Ok
        Controls.ScrollView {
            width: parent.width
            implicitHeight: Math.min(whatsNewText.implicitHeight, Kirigami.Units.gridUnit * 22)
            Controls.Label {
                id: whatsNewText
                width: whatsNewDialog.availableWidth
                wrapMode: Text.WordWrap
                textFormat: Text.MarkdownText
                onLinkActivated: (link) => Qt.openUrlExternally(link)
            }
        }
    }

    // Game controllers: see GamepadNav.qml and gamepad.py.
    GamepadNav { id: gamepadNav; window: root }
    readonly property alias gamepadNav: gamepadNav

    // Going back really closes the page. Kirigami's "back" (Alt+Left, the
    // mouse's back button, its toolbar arrow -- and our own Back buttons,
    // which call it) only scrolls the page row one step left: the player
    // stayed loaded out of sight -- measured: depth 2 after going back --
    // still holding its stream, still saving progress and showing on
    // Discord. Whenever the current page moves left, whatever is to the
    // right of it is removed (and destroyed).
    Connections {
        target: root.pageStack
        function onCurrentIndexChanged() { Qt.callLater(root.trimForwardPages) }
    }
    function trimForwardPages() {
        let stack = root.pageStack
        if (stack.currentIndex === undefined) return
        while (stack.depth - 1 > stack.currentIndex) stack.pop()
    }

    function toggleMaximised() {
        if (root.maximised) root.showNormal()
        else root.showMaximized()
    }

    // Size and maximised state are remembered between launches. Not position:
    // a Wayland client cannot place itself, so a saved x/y could be written
    // but never honoured (see backend.windowGeometry).
    Component.onCompleted: {
        root.previewsOn = backend.getHoverPreviewEnabled()
        let saved = backend.windowGeometry()
        if (saved.width) { root.width = saved.width; root.height = saved.height }
        if (saved.maximised) root.showMaximized()
        // Only after the restore, or the restore itself would be saved back
        // one resize event at a time as the window settles.
        geometrySaver.armed = true
    }

    onWidthChanged: geometrySaver.restart()
    onHeightChanged: geometrySaver.restart()
    onVisibilityChanged: geometrySaver.restart()

    Timer {
        id: geometrySaver
        // Debounced: dragging a window edge emits a resize per frame, and
        // each one would otherwise be a database write.
        property bool armed: false
        interval: 500
        onTriggered: {
            if (!armed || root.visibility === Window.Minimized) return
            backend.saveWindowGeometry(root.width, root.height, root.maximised)
        }
    }

    header: Rectangle {
        id: navBar
        visible: root.chromeVisible
        implicitHeight: root.chromeVisible
            ? root.navItemHeight + Kirigami.Units.smallSpacing * 2 : 0
        color: Kirigami.Theme.alternateBackgroundColor

        // The whole bar is the drag handle, except where a control sits on
        // top of it -- the buttons take their own presses first.
        TapHandler {
            onDoubleTapped: root.toggleMaximised()
            gesturePolicy: TapHandler.DragThreshold
        }
        DragHandler {
            target: null
            onActiveChanged: if (active) windowChrome.startMove(root)
        }

        // A hairline rather than a Kirigami.Separator: this sits directly
        // above the page's own header, and two full-strength rules stacked
        // read as a box drawn around nothing.
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: Kirigami.Theme.disabledTextColor
            opacity: 0.3
        }

        RowLayout {
            id: navRow
            anchors.fill: parent
            // The same inset on both ends as above and below the buttons, so
            // the logo and the close button sit the same distance from both
            // edges of their corner.
            anchors.leftMargin: Kirigami.Units.smallSpacing
            anchors.rightMargin: Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.smallSpacing

            // The logo is the Home button. A separate "Home" entry beside a
            // logo that does nothing is one more thing to aim at for the same
            // destination.
            Controls.AbstractButton {
                id: logoButton
                // Wider than tall, and the artwork is inset rather than
                // filling the button: a square tint box drawn tight around a
                // wordmark reads as a stray border around the logo rather
                // than as a button.
                Layout.preferredWidth: Math.round(root.navItemHeight * 1.5)
                Layout.preferredHeight: root.navItemHeight
                padding: Kirigami.Units.smallSpacing
                hoverEnabled: true
                onClicked: root.goHome()

                Controls.ToolTip.visible: hovered || homeZone.hovered
                Controls.ToolTip.text: "Home"
                Controls.ToolTip.delay: 500

                // Hover only, with no "you are here" tint. On Home -- where
                // the app opens -- a permanent tint box drawn around a
                // wordmark just reads as a border someone forgot to remove,
                // and the page's own title already says Home.
                background: NavBackground { lit: logoButton.hovered || homeZone.hovered }

                contentItem: Image {
                    source: Qt.resolvedUrl("../assets/images/AP.svg")
                    sourceSize.width: root.navItemHeight * 3
                    fillMode: Image.PreserveAspectFit
                }

                HoverHandler { cursorShape: Qt.PointingHandCursor }
            }

            // The logo is a wordmark, not an icon in a row of icons -- butted
            // straight up against the first nav entry it read as one control.
            Item { Layout.preferredWidth: Kirigami.Units.largeSpacing }

            NavButton {
                text: "Browse"
                iconName: "view-list-details-symbolic"
                current: root.section === "browse"
                onClicked: root.goBrowse()
            }

            NavButton {
                text: "Seasonal"
                iconName: "view-calendar-month-symbolic"
                current: root.section === "seasonal"
                onClicked: root.goSeasonal()
            }

            NavButton {
                text: "Continue"
                iconName: "media-playback-start-symbolic"
                current: root.section === "continue"
                onClicked: root.goContinue()
            }

            NavButton {
                text: "Library"
                iconName: "view-media-playlist-symbolic"
                current: root.section === "library"
                onClicked: root.goTo("library", "LibraryPage.qml")
            }

            // Only with Learn Japanese switched on (Settings).
            NavButton {
                visible: backend.learnFeatures
                text: "Words"
                iconName: "bookmarks-symbolic"
                current: root.section === "words"
                onClicked: root.goTo("words", "WordsPage.qml")
            }

            Item { Layout.fillWidth: true }

            // Your profile (ProfilePage): stats, and what friends are into.
            // Shows your AniList picture once there's one to show.
            NavButton {
                id: profileNav
                text: backend.anilistViewerName() || "Profile"
                iconName: "im-user-symbolic"
                current: root.section === "profile"
                onClicked: root.goTo("profile", "ProfilePage.qml")
                avatarUrl: backend.profileAvatar()
                Connections {
                    target: backend
                    function onAnilistLoggedIn(name) { profileNav.text = name; profileNav.avatarUrl = backend.profileAvatar() }
                    function onAnilistLoggedOut() { profileNav.text = "Profile"; profileNav.avatarUrl = "" }
                    function onProfileReady(result) { if (result.avatar) profileNav.avatarUrl = result.avatar }
                }
            }

            NavButton {
                text: "Settings"
                iconName: "configure-symbolic"
                current: root.section === "settings"
                onClicked: root.goSettings()
            }

            // Window buttons. Sized and tinted like the nav entries beside
            // them rather than like a system titlebar's -- they share a row,
            // so they should share a shape. Close is the only one that gets a
            // colour, so a mis-aimed click on the row is a minimise rather
            // than a quit.
            Item { Layout.preferredWidth: Kirigami.Units.smallSpacing }

            WindowButton {
                iconName: "window-minimize-symbolic"
                hint: "Minimise"
                onClicked: root.showMinimized()
            }
            WindowButton {
                iconName: root.maximised ? "window-restore-symbolic" : "window-maximize-symbolic"
                hint: root.maximised ? "Restore" : "Maximise"
                onClicked: root.toggleMaximised()
            }
            WindowButton {
                id: closeButton
                iconName: "window-close-symbolic"
                hint: "Close"
                danger: true
                lit: closeZone.hovered
                onClicked: root.close()
            }
        }

        // Everything from the close button to the window's top and right
        // edges counts as the close button, and the same for the logo in the
        // top-left. The bar keeps a margin around its buttons, so without
        // this the very corners -- where a pointer thrown at the corner of
        // the screen lands -- hit nothing.
        Item {
            id: homeZone
            readonly property bool hovered: homeZoneHover.hovered
            width: logoButton.x + logoButton.width
            height: logoButton.y + logoButton.height
            HoverHandler { id: homeZoneHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: root.goHome() }
        }
        Item {
            id: closeZone
            readonly property bool hovered: closeZoneHover.hovered
            x: closeButton.x
            width: navBar.width - closeButton.x
            height: closeButton.y + closeButton.height
            HoverHandler { id: closeZoneHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: root.close() }
        }
    }

    // Resize grips. A frameless window has no frame to grab, so these are
    // thin strips along the edges that ask the compositor to resize.
    Repeater {
        model: [
            { edge: "left",        cursor: Qt.SizeHorCursor },
            { edge: "right",       cursor: Qt.SizeHorCursor },
            { edge: "top",         cursor: Qt.SizeVerCursor },
            { edge: "bottom",      cursor: Qt.SizeVerCursor },
            { edge: "topleft",     cursor: Qt.SizeFDiagCursor },
            { edge: "topright",    cursor: Qt.SizeBDiagCursor },
            { edge: "bottomleft",  cursor: Qt.SizeBDiagCursor },
            { edge: "bottomright", cursor: Qt.SizeFDiagCursor }
        ]

        Item {
            required property var modelData
            readonly property int thickness: Kirigami.Units.smallSpacing
            readonly property bool corner: modelData.edge.length > 6

            parent: root.contentItem
            z: 9999
            // A maximised window cannot be resized by its edges, and leaving
            // live grips there steals clicks from whatever is underneath.
            visible: !root.maximised

            width: corner ? thickness * 2
                 : (modelData.edge === "left" || modelData.edge === "right"
                    ? thickness : root.contentItem.width)
            height: corner ? thickness * 2
                  : (modelData.edge === "top" || modelData.edge === "bottom"
                     ? thickness : root.contentItem.height)

            x: modelData.edge.indexOf("left") >= 0 ? 0
             : modelData.edge.indexOf("right") >= 0 ? root.contentItem.width - width : 0
            y: modelData.edge.indexOf("top") >= 0 ? 0
             : modelData.edge.indexOf("bottom") >= 0 ? root.contentItem.height - height : 0

            HoverHandler { cursorShape: modelData.cursor }
            DragHandler {
                target: null
                onActiveChanged: if (active) windowChrome.startResize(root, modelData.edge)
            }
        }
    }

    // The one tint every control in the nav bar shares. Flat until it is the
    // current section or hovered, so the bar reads as navigation rather than
    // as a row of buttons competing with the page.
    component NavBackground: Rectangle {
        property bool on: false
        property bool lit: false

        radius: Kirigami.Units.smallSpacing
        color: on
            ? Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g,
                      Kirigami.Theme.highlightColor.b, 0.2)
            : (lit
               ? Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g,
                         Kirigami.Theme.highlightColor.b, 0.1)
               : "transparent")
        Behavior on color { ColorAnimation { duration: 100 } }
    }

    component NavButton: Controls.AbstractButton {
        id: nav
        property bool current: false
        // Its own property rather than the inherited icon.name: an
        // AbstractButton with a custom contentItem does not draw icon.name
        // itself, and reading back a grouped property nothing renders is a
        // trap for whoever edits this next.
        property string iconName: ""
        // A round picture instead of the icon (the profile entry's avatar).
        property string avatarUrl: ""

        hoverEnabled: true
        // Padding on both sides rather than just extra width: the content is
        // laid out from the left, so width alone left the icon flush against
        // the tint's left edge with all the slack on the right.
        leftPadding: Kirigami.Units.largeSpacing
        rightPadding: Kirigami.Units.largeSpacing
        Layout.preferredWidth: navContent.implicitWidth + leftPadding + rightPadding
        Layout.preferredHeight: root.navItemHeight

        background: NavBackground { on: nav.current; lit: nav.hovered }

        contentItem: RowLayout {
            id: navContent
            spacing: Kirigami.Units.smallSpacing

            Avatar {
                visible: nav.avatarUrl !== ""
                source: nav.avatarUrl
                size: Kirigami.Units.iconSizes.small + 4
            }
            Kirigami.Icon {
                visible: nav.avatarUrl === ""
                source: nav.iconName
                isMask: true
                color: nav.current ? Kirigami.Theme.highlightColor : Kirigami.Theme.textColor
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: Kirigami.Units.iconSizes.small
            }
            Controls.Label {
                text: nav.text
                font.bold: nav.current
                color: nav.current ? Kirigami.Theme.highlightColor : Kirigami.Theme.textColor
            }
        }

        HoverHandler { cursorShape: Qt.PointingHandCursor }
    }

    component WindowButton: Controls.AbstractButton {
        id: winButton
        property string iconName: ""
        property bool danger: false
        // Shown on hover. "Restore" and "Maximise" are the same button, so
        // the caller passes the label rather than it being derived here.
        property string hint: ""
        // Hover coming from somewhere other than the button itself -- see
        // the close zone in the nav bar.
        property bool lit: false
        readonly property bool shownHovered: hovered || lit

        hoverEnabled: true
        Layout.preferredWidth: root.navItemHeight
        Layout.preferredHeight: root.navItemHeight

        Controls.ToolTip.visible: shownHovered && winButton.hint !== ""
        Controls.ToolTip.text: winButton.hint
        Controls.ToolTip.delay: 400

        background: Rectangle {
            radius: Kirigami.Units.smallSpacing
            color: !winButton.shownHovered ? "transparent"
                 : winButton.danger ? Kirigami.Theme.negativeTextColor
                 : Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                           Kirigami.Theme.textColor.b, 0.15)
            Behavior on color { ColorAnimation { duration: 100 } }
        }

        // Wrapped rather than the icon being the contentItem directly: a
        // button stretches its contentItem to the whole content area, so an
        // icon put there ignores its own implicit size and comes out as the
        // heaviest glyph in the bar.
        contentItem: Item {
            Kirigami.Icon {
                anchors.centerIn: parent
                source: winButton.iconName
                isMask: true
                width: Kirigami.Units.iconSizes.small
                height: width
                color: winButton.danger && winButton.shownHovered ? "white" : Kirigami.Theme.textColor
            }
        }

        HoverHandler { cursorShape: Qt.PointingHandCursor }
    }
}
