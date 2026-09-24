// A slim always-visible scroll indicator down the right edge of a page.
//
// Kirigami's own scrollbar stays hidden until the pointer is over it, which
// on a page as long as Home reads as "there is nothing below" -- rows were
// being missed entirely. This says both things a hidden bar cannot: that
// there is more, and how far down you are.
//
// Drawn rather than configured because the flickable and its scrollbar are
// built by ScrollablePage itself, so there is nothing to attach a
// ScrollBar.vertical declaration to, and reaching the attached property
// imperatively from JS is not something QML allows.
import QtQuick
import org.kde.kirigami as Kirigami

Item {
    id: hint

    property Flickable flickable: null

    readonly property real ratio: flickable ? flickable.visibleArea.heightRatio : 1
    readonly property real position: flickable ? flickable.visibleArea.yPosition : 0
    // Nothing to say when everything already fits.
    readonly property bool scrollable: flickable !== null && ratio > 0 && ratio < 1

    width: Kirigami.Units.smallSpacing
    visible: scrollable

    Rectangle {
        id: track
        anchors.fill: parent
        anchors.topMargin: Kirigami.Units.smallSpacing
        anchors.bottomMargin: Kirigami.Units.smallSpacing
        radius: width / 2
        color: Kirigami.Theme.textColor
        opacity: 0.12
    }

    Rectangle {
        id: thumb
        x: 0
        width: parent.width
        radius: width / 2
        // A floor on the height: on a thousand-episode page the true
        // proportion is a couple of pixels, which is invisible.
        height: Math.max(Kirigami.Units.gridUnit * 1.5,
                         track.height * Math.min(1, hint.ratio))
        y: track.y + (track.height - height) * Math.min(1, Math.max(0, hint.position / (1 - hint.ratio) || 0))
        color: Kirigami.Theme.highlightColor
        opacity: hoverHandler.hovered ? 1 : 0.65
        Behavior on opacity { NumberAnimation { duration: 120 } }
    }

    HoverHandler { id: hoverHandler }
}
