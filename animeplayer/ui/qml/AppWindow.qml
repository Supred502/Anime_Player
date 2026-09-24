// The application window, with the app's own navigation bar.
//
// The three places you can go are in the bar, not behind a hamburger. A
// drawer costs a click and a guess to reach three destinations, and this app
// only has three -- so they are just there, with the current one marked.
//
// It is also why this is a component rather than living in Main.qml: the
// live E2E drivers (_Test*Real.qml) each open their own window, and a bar
// only Main.qml had would mean every screenshot taken through a driver
// showed a different app from the real one.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root
    title: "Anime Player"
    width: 1280
    height: 800

    // Which nav entry is lit. Set by the go* functions rather than derived
    // from the page stack, because pushing a detail page on top of Browse
    // should not un-light Browse.
    property string section: "home"

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

    header: Rectangle {
        id: navBar
        implicitHeight: navRow.implicitHeight + Kirigami.Units.smallSpacing * 2
        color: Kirigami.Theme.alternateBackgroundColor

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
            anchors.leftMargin: Kirigami.Units.largeSpacing
            anchors.rightMargin: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.smallSpacing

            Image {
                Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                Layout.rightMargin: Kirigami.Units.smallSpacing
                source: Qt.resolvedUrl("../assets/images/AP.svg")
                sourceSize.width: Kirigami.Units.iconSizes.medium * 2
                fillMode: Image.PreserveAspectFit
            }

            NavButton {
                text: "Home"
                iconName: "go-home-symbolic"
                current: root.section === "home"
                onClicked: root.goHome()
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
}
