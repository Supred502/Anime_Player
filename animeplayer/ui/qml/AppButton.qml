// A button that actually follows the app's accent colour.
//
// The stock Controls.Button does not: the desktop QQC2 style draws through
// the platform QStyle, which reads the system colour scheme and ignores
// Kirigami.Theme entirely. That is why a "Sub / Dub" pair and a Start
// Watching button kept their Breeze-blue ring no matter what accent was
// chosen. Anything where the accent has to read as the accent uses this.
import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Controls.Button {
    id: button

    // Filled in the accent colour rather than outlined. For the one primary
    // action on a page.
    property bool accented: false

    readonly property color accent: Kirigami.Theme.highlightColor
    readonly property bool active: accented || checked

    hoverEnabled: true
    leftPadding: Kirigami.Units.largeSpacing
    rightPadding: Kirigami.Units.largeSpacing
    topPadding: Kirigami.Units.smallSpacing
    bottomPadding: Kirigami.Units.smallSpacing

    background: Rectangle {
        radius: Kirigami.Units.smallSpacing
        color: button.active
            ? (button.hovered ? Qt.lighter(button.accent, 1.15) : button.accent)
            : (button.hovered
               ? Qt.rgba(button.accent.r, button.accent.g, button.accent.b, 0.18)
               : Kirigami.Theme.alternateBackgroundColor)
        border.width: button.active ? 0 : 1
        border.color: button.hovered ? button.accent : Kirigami.Theme.disabledTextColor
        opacity: button.enabled ? 1 : 0.5
        Behavior on color { ColorAnimation { duration: 100 } }
    }

    contentItem: Row {
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Icon {
            anchors.verticalCenter: parent.verticalCenter
            visible: button.icon.name !== "" || button.icon.source != ""
            source: button.icon.name !== "" ? button.icon.name : button.icon.source
            width: Kirigami.Units.iconSizes.small
            height: width
            isMask: true
            color: button.active ? Kirigami.Theme.highlightedTextColor
                                 : Kirigami.Theme.textColor
        }

        Controls.Label {
            anchors.verticalCenter: parent.verticalCenter
            text: button.text
            color: button.active ? Kirigami.Theme.highlightedTextColor
                                 : Kirigami.Theme.textColor
            font.bold: button.active
        }
    }
}
