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
    AppTheming { targets: [root.windowRoot] }

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
    function goBrowse(properties) { return root.goTo("browse", "BrowsePage.qml", properties) }
    function goSettings() { return root.goTo("settings", "SettingsPage.qml") }
    // Its own section rather than a Browse preset arrived at sideways, so the
    // nav entry stays lit while you are looking at it.
    function goContinue() {
        return root.goTo("continue", "BrowsePage.qml", { startCategory: "continue" })
    }

    function toggleMaximised() {
        if (root.maximised) root.showNormal()
        else root.showMaximized()
    }

    // Size and maximised state are remembered between launches. Not position:
    // a Wayland client cannot place itself, so a saved x/y could be written
    // but never honoured (see backend.windowGeometry).
    Component.onCompleted: {
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
            anchors.leftMargin: Kirigami.Units.smallSpacing
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

                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Home"
                Controls.ToolTip.delay: 500

                // Hover only, with no "you are here" tint. On Home -- where
                // the app opens -- a permanent tint box drawn around a
                // wordmark just reads as a border someone forgot to remove,
                // and the page's own title already says Home.
                background: NavBackground { lit: logoButton.hovered }

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
                text: "Continue"
                iconName: "media-playback-start-symbolic"
                current: root.section === "continue"
                onClicked: root.goContinue()
            }

            NavButton {
                text: "Stats"
                iconName: "office-chart-bar-symbolic"
                current: root.section === "stats"
                onClicked: root.goTo("stats", "StatsPage.qml")
            }

            Item { Layout.fillWidth: true }

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
        // edges counts as the close button. The bar keeps a margin above its
        // buttons, so without this the very corner -- where a pointer thrown
        // at the corner of the screen lands -- hit nothing.
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

            Kirigami.Icon {
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
