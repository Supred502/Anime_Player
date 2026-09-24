// The home page's hero: a wide banner carousel of the source's featured
// shows, with a synopsis and a Watch button.
//
// This is the one place in the app that gets a landscape image. Everywhere
// else is 2:3 poster art, and a hero built from a poster is either a tiny
// image in a wide box or a badly cropped one -- the source publishes a
// separate banner per spotlight entry, and this uses it.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Item {
    id: hero

    property alias model: pages.model
    signal watchClicked(int index)

    // Wide-but-not-tall, and capped: on a maximised 4K window a 16:9 hero
    // would be the entire first screen and the rows beneath it would need
    // scrolling to discover at all.
    implicitHeight: Math.min(Kirigami.Units.gridUnit * 22, Math.round(width * 0.38))
    visible: pages.count > 0

    // Advances on its own so the row reads as a carousel, but stops while the
    // pointer is over it -- a banner that slides out from under a half-read
    // synopsis is worse than no rotation at all.
    Timer {
        interval: 7000
        running: hero.visible && pages.count > 1 && !heroHover.hovered
        repeat: true
        onTriggered: pages.incrementCurrentIndex()
    }

    HoverHandler { id: heroHover }

    Rectangle {
        anchors.fill: parent
        radius: Kirigami.Units.largeSpacing
        clip: true
        color: Kirigami.Theme.alternateBackgroundColor

        ListView {
            id: pages
            anchors.fill: parent
            orientation: ListView.Horizontal
            snapMode: ListView.SnapOneItem
            highlightRangeMode: ListView.StrictlyEnforceRange
            highlightMoveDuration: 450
            preferredHighlightBegin: 0
            preferredHighlightEnd: width
            boundsBehavior: Flickable.StopAtBounds
            // Wraps, so the auto-advance doesn't stall on the last slide.
            // With a non-wrapping view incrementCurrentIndex() at the end is
            // a no-op and the carousel silently stops after ten rotations.
            keyNavigationWraps: true
            clip: true
            cacheBuffer: width * 2

            delegate: Item {
                id: slide
                required property var model
                required property int index

                width: pages.width
                height: pages.height

                Image {
                    anchors.fill: parent
                    source: slide.model.banner_url || ""
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    // Anchor the crop to the top: banner art is composed with
                    // the characters' faces in the upper half, and a centred
                    // crop of a very wide box cuts them off.
                    verticalAlignment: Image.AlignTop
                }

                // Two scrims, not one. The horizontal one makes the text side
                // readable over bright art; the vertical one keeps the bottom
                // edge dark so the page's own background doesn't show a hard
                // seam where the banner ends.
                Rectangle {
                    anchors.fill: parent
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0.88) }
                        GradientStop { position: 0.55; color: Qt.rgba(0, 0, 0, 0.55) }
                        GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.15) }
                    }
                }
                Rectangle {
                    anchors.fill: parent
                    gradient: Gradient {
                        GradientStop { position: 0.55; color: "transparent" }
                        GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.6) }
                    }
                }

                ColumnLayout {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: Kirigami.Units.gridUnit * 2
                    anchors.rightMargin: Kirigami.Units.gridUnit * 2
                    width: Math.min(Kirigami.Units.gridUnit * 30, parent.width * 0.55)
                    spacing: Kirigami.Units.smallSpacing

                    Controls.Label {
                        text: "#" + slide.model.rank + " Spotlight"
                        color: Kirigami.Theme.highlightColor
                        font.bold: true
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    }

                    Controls.Label {
                        Layout.fillWidth: true
                        text: slide.model.title || ""
                        color: "white"
                        font.bold: true
                        font.pixelSize: Math.round(Kirigami.Theme.defaultFont.pixelSize * 2.1)
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }

                    RowLayout {
                        spacing: Kirigami.Units.largeSpacing
                        Repeater {
                            // Built here rather than as four conditional
                            // items: an upcoming show has no runtime and a
                            // sub-only one no dub count, and filtering the
                            // list keeps the separators from doubling up.
                            model: [
                                slide.model.kind || "",
                                slide.model.duration || "",
                                slide.model.released || "",
                                slide.model.sub_count > 0 ? "SUB " + slide.model.sub_count : "",
                                slide.model.dub_count > 0 ? "DUB " + slide.model.dub_count : ""
                            ].filter((part) => part !== "")

                            Controls.Label {
                                required property var modelData
                                text: modelData
                                color: "white"
                                opacity: 0.85
                                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                            }
                        }
                    }

                    Controls.Label {
                        Layout.fillWidth: true
                        Layout.topMargin: Kirigami.Units.smallSpacing
                        // Hidden rather than shrunk on a short window: below
                        // about this height the synopsis would push the Watch
                        // button off the bottom of the banner.
                        visible: hero.height > Kirigami.Units.gridUnit * 14
                        text: slide.model.description || ""
                        color: "white"
                        opacity: 0.8
                        wrapMode: Text.WordWrap
                        maximumLineCount: 3
                        elide: Text.ElideRight
                    }

                    Controls.Button {
                        Layout.topMargin: Kirigami.Units.smallSpacing
                        text: "Watch Now"
                        icon.name: "media-playback-start-symbolic"
                        highlighted: true
                        onClicked: hero.watchClicked(slide.index)
                    }
                }
            }
        }

        // Slide indicators. Clickable, so the carousel is navigable without
        // waiting out the timer or flicking blind.
        RowLayout {
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.smallSpacing
            visible: pages.count > 1

            Repeater {
                model: pages.count
                Rectangle {
                    required property int index
                    readonly property bool current: index === pages.currentIndex
                    // The current dot stretches into a bar, which reads at a
                    // glance where ten same-sized dots in two shades of grey
                    // do not.
                    width: current ? Kirigami.Units.gridUnit : Kirigami.Units.smallSpacing
                    height: Kirigami.Units.smallSpacing
                    radius: height / 2
                    color: current ? Kirigami.Theme.highlightColor : Qt.rgba(1, 1, 1, 0.5)
                    Behavior on width { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: pages.currentIndex = index }
                }
            }
        }
    }
}
