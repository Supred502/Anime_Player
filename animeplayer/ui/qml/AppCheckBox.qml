// A checkbox that actually follows the app's accent colour.
//
// The same problem AppButton solves, one level deeper. A stock
// Controls.CheckBox draws its tick through an indicator item the style builds
// itself, and that item sets Kirigami.Theme.inherit = false again -- measured
// live, a checkbox whose own theme read #ff0000 still had an indicator
// reading Breeze's #3daee9. Painting the accent onto every descendant that
// opted out (see AppTheming.applyDeep) recolours the indicator's border but
// not its fill, which comes from further inside the style still.
//
// Drawing the indicator here ends the chase: there is nothing between the
// accent and the pixels.
import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Controls.CheckBox {
    id: control

    Kirigami.Theme.inherit: true
    hoverEnabled: true
    spacing: Kirigami.Units.smallSpacing

    indicator: Rectangle {
        implicitWidth: Kirigami.Units.iconSizes.small + 2
        implicitHeight: implicitWidth
        x: control.leftPadding
        y: control.topPadding + (control.availableHeight - height) / 2
        radius: 3

        color: control.checked ? Kirigami.Theme.highlightColor : "transparent"
        border.width: control.checked ? 0 : 2
        border.color: control.hovered ? Kirigami.Theme.highlightColor
                                      : Kirigami.Theme.disabledTextColor
        opacity: control.enabled ? 1 : 0.5
        Behavior on color { ColorAnimation { duration: 100 } }

        Kirigami.Icon {
            anchors.centerIn: parent
            visible: control.checked
            source: "checkmark-symbolic"
            isMask: true
            color: Kirigami.Theme.highlightedTextColor
            width: parent.width - 4
            height: width
        }
    }

    contentItem: Controls.Label {
        leftPadding: control.indicator.width + control.spacing
        text: control.text
        color: Kirigami.Theme.textColor
        opacity: control.enabled ? 1 : 0.5
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.WordWrap
    }
}
