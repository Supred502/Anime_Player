// A rectangle whose contents are clipped to its rounded corners. Plain
// `clip: true` clips to the square box, so a picture filling a rounded card
// covered the corners and every card looked square.
import QtQuick
import QtQuick.Effects

Rectangle {
    id: frame
    layer.enabled: true
    layer.smooth: true
    layer.effect: MultiEffect {
        maskEnabled: true
        maskSource: mask
        // A soft edge on the mask, or the corners come out jagged.
        maskThresholdMin: 0.5
        maskSpreadAtMin: 1.0
    }
    Rectangle {
        id: mask
        anchors.fill: parent
        radius: frame.radius
        visible: false
        layer.enabled: true
        layer.smooth: true
    }
}
