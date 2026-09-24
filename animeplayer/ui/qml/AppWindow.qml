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

    function toggleMaximised() {
        if (root.maximised) root.showNormal()
        else root.showMaximized()
    }

    header: Rectangle {
        id: navBar
        implicitHeight: navRow.implicitHeight + Kirigami.Units.smallSpacing * 2
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
                Layout.preferredWidth: Kirigami.Units.iconSizes.large
                Layout.preferredHeight: Kirigami.Units.iconSizes.large
                hoverEnabled: true
                onClicked: root.goHome()

                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Home"
                Controls.ToolTip.delay: 500

                background: Rectangle {
                    radius: Kirigami.Units.smallSpacing
                    color: root.section === "home"
                        ? Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g,
                                  Kirigami.Theme.highlightColor.b, 0.2)
                        : (logoButton.hovered
                           ? Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g,
                                     Kirigami.Theme.highlightColor.b, 0.1)
                           : "transparent")
                    Behavior on color { ColorAnimation { duration: 100 } }
                }

                contentItem: Image {
                    source: Qt.resolvedUrl("../assets/images/AP.svg")
                    sourceSize.width: Kirigami.Units.iconSizes.large * 2
                    fillMode: Image.PreserveAspectFit
                }

                HoverHandler { cursorShape: Qt.PointingHandCursor }
            }

            NavButton {
                text: "Browse"
                iconName: "view-list-details-symbolic"
                current: root.section === "browse"
                onClicked: root.goBrowse()
            }

            Item { Layout.fillWidth: true }

            NavButton {
                text: "Settings"
                iconName: "configure-symbolic"
                current: root.section === "settings"
                onClicked: root.goSettings()
            }

            // Window buttons. Close is the only one that gets a colour, so a
            // mis-aimed click on the row is a minimise rather than a quit.
            WindowButton {
                iconName: "window-minimize-symbolic"
                onClicked: root.showMinimized()
            }
            WindowButton {
                iconName: root.maximised ? "window-restore-symbolic" : "window-maximize-symbolic"
                onClicked: root.toggleMaximised()
            }
            WindowButton {
                iconName: "window-close-symbolic"
                danger: true
                onClicked: root.close()
            }
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

    // Flat until it is the current section or hovered, so the bar reads as
    // navigation rather than as a row of buttons competing with the page.
    component NavButton: Controls.AbstractButton {
        id: nav
        property bool current: false
        // Its own property rather than the inherited icon.name: an
        // AbstractButton with a custom contentItem does not draw icon.name
        // itself, and reading back a grouped property nothing renders is a
        // trap for whoever edits this next.
        property string iconName: ""

        hoverEnabled: true
        implicitWidth: navContent.implicitWidth + Kirigami.Units.largeSpacing * 2
        implicitHeight: navContent.implicitHeight + Kirigami.Units.smallSpacing * 2

        background: Rectangle {
            radius: Kirigami.Units.smallSpacing
            color: nav.current
                ? Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g,
                          Kirigami.Theme.highlightColor.b, 0.2)
                : (nav.hovered
                   ? Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g,
                             Kirigami.Theme.highlightColor.b, 0.1)
                   : "transparent")
            Behavior on color { ColorAnimation { duration: 100 } }
        }

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

        hoverEnabled: true
        Layout.preferredWidth: Kirigami.Units.gridUnit * 2.2
        Layout.preferredHeight: Kirigami.Units.gridUnit * 1.8

        background: Rectangle {
            color: !winButton.hovered ? "transparent"
                 : winButton.danger ? Kirigami.Theme.negativeTextColor
                 : Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                           Kirigami.Theme.textColor.b, 0.15)
            Behavior on color { ColorAnimation { duration: 100 } }
        }

        contentItem: Kirigami.Icon {
            source: winButton.iconName
            isMask: true
            color: winButton.danger && winButton.hovered ? "white" : Kirigami.Theme.textColor
        }

        HoverHandler { cursorShape: Qt.PointingHandCursor }
    }
}
