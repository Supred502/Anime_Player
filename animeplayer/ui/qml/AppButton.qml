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
    // The QQC2 desktop style sets Kirigami.Theme.inherit = false on its
    // controls, which stops the app's accent reaching them -- measured
    // live: a page themed red still drew Breeze-blue Sub/Dub buttons.
    // Turning inheritance back on is what makes one accent value reach
    // every control in the app. See AppTheming.qml.
    Kirigami.Theme.inherit: true
    id: button

    // Filled in the accent colour rather than outlined. For the one primary
    // action on a page.
    property bool accented: false

    readonly property color accent: Kirigami.Theme.highlightColor
    readonly property bool active: accented || checked

    hoverEnabled: true
    // An icon with no words is a square the height of a worded button, so
    // a row mixing the two (the player's toolbar) lines up.
    readonly property bool iconOnly: text === ""
    readonly property real squarePadding: Math.round((contentItem.implicitHeight + topPadding + bottomPadding
                                                      - Kirigami.Units.iconSizes.small) / 2)
    leftPadding: iconOnly ? squarePadding : Kirigami.Units.largeSpacing
    rightPadding: iconOnly ? squarePadding : Kirigami.Units.largeSpacing
    topPadding: Kirigami.Units.smallSpacing
    bottomPadding: Kirigami.Units.smallSpacing
    // Sized by what's in it. The system style otherwise pads every button
    // out to a minimum width, so "1×" was as wide as "Auto" and "Presets".
    implicitWidth: contentItem.implicitWidth + leftPadding + rightPadding
    implicitHeight: contentItem.implicitHeight + topPadding + bottomPadding

    background: Rectangle {
        radius: Kirigami.Units.largeSpacing   // the one roundness for buttons and chips
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

    // Centred in whatever width the button is given. A bare Row as the
    // contentItem is laid out from the left, so a button sized wider than
    // its text (the player's あ button) drew the text off to one side.
    contentItem: Item {
        implicitWidth: contentRow.implicitWidth
        // A line of text tall even with no text, for the same reason.
        implicitHeight: Math.max(contentRow.implicitHeight, lineHeight.height)
        FontMetrics { id: lineHeight; font: button.font }

        Row {
            id: contentRow
            anchors.centerIn: parent
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
                visible: button.text !== ""
                text: button.text
                color: button.active ? Kirigami.Theme.highlightedTextColor
                                     : Kirigami.Theme.textColor
                font.bold: button.active || button.font.bold
            }
        }
    }
}
