// The home page's hero: a crossfading carousel of the source's featured
// shows, with a synopsis and a Watch button.
//
// This is the one place in the app that gets a landscape image. Everywhere
// else is 2:3 poster art, and a hero built from a poster is either a tiny
// image in a wide box or a badly cropped one -- the source publishes a
// separate banner per spotlight entry, and this uses it.
//
// A crossfade between two Images rather than a ListView of slides. The
// ListView version had to be flickable to animate, which meant its index
// could be moved by a drag, by the auto-advance timer and by a dot click at
// once -- so the dots regularly disagreed with what was on screen and a
// half-flick left it stuck between two slides. Here the index is a plain
// integer that only three things set, and the image follows it.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Item {
    id: hero

    property var model: []
    // How far the bottom of the hero dissolves into the page. The page's own
    // background is painted over the art across this band so the hero ends in
    // a fade instead of the hard horizontal edge it used to cut off at.
    property color fadeColor: Kirigami.Theme.backgroundColor

    signal watchClicked(int index)

    property int index: 0
    readonly property int count: model ? model.length : 0
    readonly property var current: count > 0 ? model[Math.min(index, count - 1)] : null

    // Wide-but-not-tall, and capped: on a maximised 4K window a 16:9 hero
    // would be the entire first screen and the rows beneath it would need
    // scrolling to discover at all.
    implicitHeight: Math.min(Kirigami.Units.gridUnit * 22, Math.round(width * 0.38))
    visible: count > 0
    clip: true

    onCountChanged: if (index >= count) index = 0

    function show(next) {
        if (count === 0) return
        // Wraps both ways, so the auto-advance never stalls on the last slide
        // and the dots stay usable in either direction.
        hero.index = (next + count) % count
    }

    // Advances on its own so the row reads as a carousel, but stops while the
    // pointer is over it -- a banner that slides out from under a half-read
    // synopsis is worse than no rotation at all.
    Timer {
        interval: 7000
        running: hero.visible && hero.count > 1 && !heroHover.hovered
        repeat: true
        onTriggered: hero.show(hero.index + 1)
    }

    HoverHandler { id: heroHover }

    // Two stacked images crossfaded by swapping which one is in front. A
    // single Image with a fade on `source` flashes its placeholder between
    // slides, because the opacity animation starts before the new art has
    // decoded. Here the swap waits for the incoming image to report Ready.
    //
    // Both sources are *assigned*, never bound. Binding them to "whichever of
    // these two strings is in front" and then reassigning those strings from
    // the image's own onStatusChanged is a binding loop, which Qt detects and
    // breaks -- leaving the carousel stuck on one slide.
    Item {
        id: art
        anchors.fill: parent

        property bool showBack: false

        function display(url) {
            if (url === "" || url === (showBack ? backImage.source : frontImage.source)) return
            if (showBack) frontImage.source = url
            else backImage.source = url
            swapFallback.restart()
        }

        function reveal(which) {
            // Ignore a load finishing for the image that is already showing:
            // that is the previous slide settling, not the new one arriving.
            if (which === showBack) return
            showBack = which
            swapFallback.stop()
        }

        Image {
            id: frontImage
            anchors.fill: parent
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            // Anchor the crop to the top: banner art is composed with the
            // characters' faces in the upper half, and a centred crop of a
            // very wide box cuts them off.
            verticalAlignment: Image.AlignTop
            opacity: art.showBack ? 0 : 1
            Behavior on opacity { NumberAnimation { duration: 400 } }
            onStatusChanged: if (status === Image.Ready) art.reveal(false)
        }

        Image {
            id: backImage
            anchors.fill: parent
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            verticalAlignment: Image.AlignTop
            opacity: art.showBack ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 400 } }
            onStatusChanged: if (status === Image.Ready) art.reveal(true)
        }

        // Fallback for art that fails to load at all: without it a broken
        // banner url would park the carousel on the previous slide for good.
        Timer {
            id: swapFallback
            interval: 1500
            onTriggered: art.reveal(!art.showBack)
        }
    }

    onCurrentChanged: if (hero.current) art.display(hero.current.banner_url || "")

    // Scrims. The horizontal one makes the text side readable over bright
    // art; the vertical one carries the art into the page background so the
    // hero has no bottom edge at all.
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0.9) }
            GradientStop { position: 0.55; color: Qt.rgba(0, 0, 0, 0.55) }
            GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.1) }
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        // A generous band: a short fade still reads as a line where it starts.
        height: Math.round(parent.height * 0.45)
        gradient: Gradient {
            GradientStop { position: 0.0; color: "transparent" }
            GradientStop {
                position: 0.55
                color: Qt.rgba(hero.fadeColor.r, hero.fadeColor.g, hero.fadeColor.b, 0.75)
            }
            GradientStop { position: 1.0; color: hero.fadeColor }
        }
    }

    ColumnLayout {
        id: heroText
        anchors.left: parent.left
        anchors.leftMargin: Kirigami.Units.gridUnit * 2
        anchors.top: parent.top
        anchors.topMargin: Kirigami.Units.gridUnit * 1.5
        width: Math.min(Kirigami.Units.gridUnit * 32, parent.width * 0.55)
        spacing: Kirigami.Units.smallSpacing
        visible: hero.current !== null

        // Anchored to the top rather than centred: the text block's own height
        // changes with each entry (some have no runtime, some a longer title),
        // and a centred block made every slide change nudge the title and the
        // Watch button up or down by a few pixels.

        Controls.Label {
            // Why this one is here (AniList-built spotlight), or the site's
            // own numbering for its fallback carousel.
            text: hero.current ? (hero.current.reason || ("#" + hero.current.rank + " Spotlight")) : ""
            color: Kirigami.Theme.highlightColor
            font.bold: true
            font.pixelSize: Kirigami.Theme.smallFont.pixelSize
        }

        SelectableText {
            Layout.fillWidth: true
            text: hero.current ? (hero.current.title || "") : ""
            color: "white"
            font.bold: true
            font.pixelSize: Math.round(Kirigami.Theme.defaultFont.pixelSize * 2.1)
            maxLines: 2
        }

        RowLayout {
            spacing: Kirigami.Units.largeSpacing
            Repeater {
                // Built here rather than as four conditional items: an
                // upcoming show has no runtime and a sub-only one no dub
                // count, and filtering the list keeps the separators from
                // doubling up.
                model: hero.current ? [
                    hero.current.kind || "",
                    hero.current.duration || "",
                    hero.current.released || "",
                    hero.current.sub_count > 0 ? "SUB " + hero.current.sub_count : "",
                    hero.current.dub_count > 0 ? "DUB " + hero.current.dub_count : "",
                    hero.current.score > 0 ? "\u2605 " + (hero.current.score / 10).toFixed(1) : ""
                ].filter((part) => part !== "") : []

                Controls.Label {
                    required property var modelData
                    text: modelData
                    color: "white"
                    opacity: 0.85
                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                }
            }
        }

        SelectableText {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.smallSpacing
            // Hidden rather than shrunk on a short window: below about this
            // height the synopsis would push the Watch button off the bottom.
            visible: hero.height > Kirigami.Units.gridUnit * 14
            text: hero.current ? (hero.current.description || "") : ""
            color: "white"
            opacity: 0.8
            maxLines: 3
        }

        AppButton {
            Layout.topMargin: Kirigami.Units.smallSpacing
            text: "Watch Now"
            icon.name: "media-playback-start-symbolic"
            accented: true
            onClicked: hero.watchClicked(hero.index)
        }
    }

    // Step arrows, shown on hover. The dots alone make a ten-entry carousel a
    // game of darts.
    HeroArrow {
        anchors.left: parent.left
        anchors.leftMargin: Kirigami.Units.smallSpacing
        anchors.verticalCenter: parent.verticalCenter
        icon: "go-previous-symbolic"
        shown: heroHover.hovered && hero.count > 1
        onTriggered: hero.show(hero.index - 1)
    }

    HeroArrow {
        anchors.right: parent.right
        anchors.rightMargin: Kirigami.Units.smallSpacing
        anchors.verticalCenter: parent.verticalCenter
        icon: "go-next-symbolic"
        shown: heroHover.hovered && hero.count > 1
        onTriggered: hero.show(hero.index + 1)
    }

    // Slide indicators. Clickable, so the carousel is navigable without
    // waiting out the timer.
    RowLayout {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: Kirigami.Units.gridUnit * 2
        anchors.bottomMargin: Kirigami.Units.largeSpacing
        spacing: Kirigami.Units.smallSpacing
        visible: hero.count > 1

        Repeater {
            model: hero.count
            // A tap target the size of a dot is a hard target, so each dot is
            // drawn inside a larger invisible box that takes the click.
            Item {
                required property int index
                readonly property bool current: index === hero.index

                implicitWidth: dot.width + Kirigami.Units.smallSpacing * 2
                implicitHeight: Kirigami.Units.gridUnit

                Rectangle {
                    id: dot
                    anchors.centerIn: parent
                    // The current dot stretches into a bar, which reads at a
                    // glance where ten same-sized dots in two shades of grey
                    // do not.
                    width: parent.current ? Kirigami.Units.gridUnit : Kirigami.Units.smallSpacing
                    height: Kirigami.Units.smallSpacing
                    radius: height / 2
                    color: parent.current ? Kirigami.Theme.highlightColor
                                          : Qt.rgba(1, 1, 1, dotHover.hovered ? 0.9 : 0.45)
                    Behavior on width { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
                    Behavior on color { ColorAnimation { duration: 120 } }
                }

                HoverHandler { id: dotHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: hero.show(index) }
            }
        }
    }

    component HeroArrow: Rectangle {
        id: arrow
        property string icon: ""
        property bool shown: false
        signal triggered()

        width: Kirigami.Units.gridUnit * 2.2
        height: width
        radius: width / 2
        color: Qt.rgba(0, 0, 0, arrowHover.hovered ? 0.8 : 0.5)
        opacity: shown ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 120 } }
        Behavior on color { ColorAnimation { duration: 120 } }

        Kirigami.Icon {
            anchors.centerIn: parent
            source: arrow.icon
            width: Kirigami.Units.iconSizes.small
            height: width
            color: "white"
            isMask: true
        }

        HoverHandler { id: arrowHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: arrow.triggered() }
    }
}
