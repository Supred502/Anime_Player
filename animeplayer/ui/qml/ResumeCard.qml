// A wide "pick up where you left off" card: the poster art as a backdrop,
// the title, which episode you're on, and how far into it you got.
//
// Deliberately a different shape from the poster cards everywhere else. The
// home page was eight identical rows of identical posters, which made the one
// row you actually came for -- this one -- impossible to pick out at a
// glance. Landscape cards at the top read as "your stuff", and the poster
// shelves below them read as "everything else".
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Item {
    id: resume

    property string posterUrl: ""
    property string title: ""
    property string subtitle: ""
    property real watchedFraction: 0

    readonly property bool hovered: hoverHandler.hovered
    signal clicked()

    Rectangle {
        id: frame
        anchors.fill: parent
        radius: Kirigami.Units.mediumSpacing
        clip: true
        color: Kirigami.Theme.alternateBackgroundColor
        scale: resume.hovered ? 1.02 : 1
        Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }

        // The poster is portrait and this box is landscape, so it is cropped
        // hard and blurred into a backdrop rather than letterboxed. The
        // readable copy sits on top of it.
        Image {
            anchors.fill: parent
            source: resume.posterUrl
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            verticalAlignment: Image.AlignTop
            opacity: 0.55
        }

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0.85) }
                GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.35) }
            }
        }

        RowLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.largeSpacing

            // A small upright poster beside the copy, so the card still shows
            // the art the way it was drawn.
            Rectangle {
                Layout.preferredWidth: Math.round(resume.height * 0.5)
                Layout.preferredHeight: Math.round(Layout.preferredWidth * 1.5)
                Layout.alignment: Qt.AlignVCenter
                radius: Kirigami.Units.smallSpacing
                clip: true
                color: "transparent"

                Image {
                    anchors.fill: parent
                    source: resume.posterUrl
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignVCenter
                spacing: Kirigami.Units.smallSpacing

                Controls.Label {
                    Layout.fillWidth: true
                    text: resume.title
                    color: "white"
                    font.bold: true
                    elide: Text.ElideRight
                    maximumLineCount: 2
                    wrapMode: Text.WordWrap
                }

                Controls.Label {
                    text: resume.subtitle
                    color: "white"
                    opacity: 0.8
                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                }

                // Only drawn once there is progress worth drawing: a bar
                // pinned at zero on every card says nothing.
                Rectangle {
                    Layout.fillWidth: true
                    Layout.topMargin: Kirigami.Units.smallSpacing
                    visible: resume.watchedFraction > 0
                    height: 4
                    radius: 2
                    color: Qt.rgba(1, 1, 1, 0.25)

                    Rectangle {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: parent.width * Math.min(1, resume.watchedFraction)
                        radius: parent.radius
                        color: Kirigami.Theme.highlightColor
                    }
                }
            }

            Rectangle {
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredWidth: Kirigami.Units.iconSizes.large
                Layout.preferredHeight: Kirigami.Units.iconSizes.large
                radius: width / 2
                color: resume.hovered ? Kirigami.Theme.highlightColor : Qt.rgba(1, 1, 1, 0.18)
                Behavior on color { ColorAnimation { duration: 120 } }

                Kirigami.Icon {
                    anchors.centerIn: parent
                    // Nudged right: the glyph is a triangle, so its visual
                    // centre sits left of its bounding box's centre.
                    anchors.horizontalCenterOffset: Math.round(width / 8)
                    source: Qt.resolvedUrl("../assets/images/play-button.png")
                    isMask: true
                    color: "white"
                    width: Math.round(Kirigami.Units.iconSizes.small)
                    height: width
                }
            }
        }
    }

    Rectangle {
        anchors.fill: frame
        radius: frame.radius
        color: "transparent"
        border.width: 2
        border.color: Kirigami.Theme.highlightColor
        opacity: resume.hovered ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 120 } }
    }

    HoverHandler { id: hoverHandler; cursorShape: Qt.PointingHandCursor }
    TapHandler { onTapped: resume.clicked() }
    // A page with its own right-click menu for these cards handles the
    // signal; otherwise it's the app's usual "Copy title" menu.
    signal contextMenuRequested()
    property bool customMenu: false
    TapHandler {
        acceptedButtons: Qt.RightButton
        onTapped: resume.customMenu ? resume.contextMenuRequested()
                                    : applicationWindow().showCardMenu(resume.title)
    }
}
