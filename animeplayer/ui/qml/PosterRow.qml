// One horizontal shelf of poster cards: a heading, an optional "See all",
// and a row that scrolls sideways.
//
// Horizontal rather than a wrapping grid, which is what the home page used
// to do. A grid of every row stacked vertically meant one row of six shows
// filled the window and everything below it was off-screen; a shelf shows
// the top of each row at a glance and puts the rest one flick away, which is
// the whole point of having rows in the first place.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: row

    property alias model: shelf.model
    property string heading: ""
    property string emptyHint: ""      // shown instead of the shelf when the row has no items
    property bool loading: false
    property bool showSeeAll: false
    property bool ranked: false        // draws 1,2,3... on the posters
    property real cardWidth: Kirigami.Units.gridUnit * 9

    // Per-row, because each row describes a different kind of entry -- the
    // card text can't come from one hardcoded model role.
    property var subtitleFor: (entry) => ""
    property var fractionFor: (entry) => 0
    property var badgeFor: (entry) => ""

    signal cardClicked(int index)
    signal seeAllClicked()

    spacing: Kirigami.Units.smallSpacing
    visible: loading || shelf.count > 0 || emptyHint !== ""

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing
        // A shelf used under someone else's heading (the detail page does
        // this) passes no heading of its own, and this row would otherwise
        // still draw its accent bar -- a stray tick floating above the row.
        visible: row.heading !== "" || row.showSeeAll

        // An accent bar beside the heading. Purely decorative, but with seven
        // shelves stacked up it is what makes a heading read as the start of
        // a new one rather than as a caption on the row above.
        Rectangle {
            Layout.preferredWidth: 4
            Layout.preferredHeight: headingLabel.implicitHeight * 0.8
            radius: 2
            color: Kirigami.Theme.highlightColor
        }

        Kirigami.Heading {
            id: headingLabel
            level: 3
            text: row.heading
        }

        Controls.BusyIndicator {
            running: row.loading
            visible: row.loading
            Layout.preferredHeight: headingLabel.implicitHeight
            Layout.preferredWidth: Layout.preferredHeight
        }

        Item { Layout.fillWidth: true }

        Controls.ToolButton {
            visible: row.showSeeAll && shelf.count > 0
            text: "See all"
            icon.name: "go-next-symbolic"
            // Label first, arrow after it -- "See all >" rather than "> See all".
            LayoutMirroring.enabled: true
            LayoutMirroring.childrenInherit: true
            onClicked: row.seeAllClicked()
        }
    }

    Controls.Label {
        Layout.fillWidth: true
        visible: !row.loading && shelf.count === 0 && row.emptyHint !== ""
        text: row.emptyHint
        opacity: 0.6
        wrapMode: Text.WordWrap
    }

    Item {
        Layout.fillWidth: true
        Layout.preferredHeight: shelf.height
        visible: row.loading || shelf.count > 0

        ListView {
            id: shelf
            anchors.left: parent.left
            anchors.right: parent.right
            orientation: ListView.Horizontal
            // Sized from the card rather than from a constant, so a card
            // design change can't leave every shelf in the app clipping its
            // subtitles.
            height: sizer.heightForWidth(row.cardWidth) + Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.largeSpacing
            clip: true
            reuseItems: true
            boundsBehavior: Flickable.StopAtBounds
            // Cards lift and grow on hover, and a clipped ListView would cut
            // the grown edge off. The margin gives the outermost card room to
            // grow into on both sides.
            leftMargin: Kirigami.Units.smallSpacing
            rightMargin: Kirigami.Units.smallSpacing

            // Measures only; never drawn. AnimeCard deliberately doesn't
            // expose its height as an implicit property (see its comments),
            // so something has to ask it.
            AnimeCard { id: sizer; visible: false; width: row.cardWidth }

            delegate: AnimeCard {
                required property int index
                required property var model

                width: row.cardWidth
                height: shelf.height - Kirigami.Units.smallSpacing
                posterUrl: model.poster_url || ""
                title: model.title
                subtitle: row.subtitleFor(model)
                badgeText: row.badgeFor(model)
                scoreText: model.rating || ""
                rankText: row.ranked ? String(index + 1) : ""
                cornerText: model.dub_count > 0 ? "SUB · DUB"
                          : (model.sub_count > 0 ? "SUB" : (model.kind || ""))
                watchedFraction: row.fractionFor(model)
                onClicked: row.cardClicked(index)
            }

            // Placeholder cards while the row's request is in flight. Without
            // these the page grows by a shelf's height as each row lands, and
            // whatever you were reading jumps down the screen.
            Row {
                anchors.left: parent.left
                anchors.leftMargin: shelf.leftMargin
                spacing: shelf.spacing
                visible: row.loading && shelf.count === 0
                Repeater {
                    model: 8
                    Rectangle {
                        width: row.cardWidth
                        height: Math.round(row.cardWidth * 1.5)
                        radius: Kirigami.Units.mediumSpacing
                        color: Kirigami.Theme.alternateBackgroundColor
                        opacity: 0.5 + 0.3 * Math.sin(shimmer.phase + index)
                    }
                }
            }
        }

        // Keyboard/trackpad users flick; a pointer needs something to click.
        // Only drawn while the pointer is over the shelf, and only on the
        // side there is actually more content on.
        HoverHandler { id: shelfHover }

        ScrollArrow {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            icon: "go-previous-symbolic"
            shown: shelfHover.hovered && !shelf.atXBeginning
            onTriggered: shelf.flick(2200, 0)
        }

        ScrollArrow {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            icon: "go-next-symbolic"
            shown: shelfHover.hovered && !shelf.atXEnd
            onTriggered: shelf.flick(-2200, 0)
        }
    }

    // Drives the loading placeholders' pulse. One timer for the whole row
    // rather than an animation per placeholder.
    QtObject {
        id: shimmer
        property real phase: 0
    }

    NumberAnimation {
        target: shimmer
        property: "phase"
        from: 0
        to: Math.PI * 2
        duration: 1400
        loops: Animation.Infinite
        running: row.loading
    }

    component ScrollArrow: Rectangle {
        id: arrow
        property string icon: ""
        property bool shown: false
        signal triggered()

        width: Kirigami.Units.gridUnit * 2
        height: width
        radius: width / 2
        color: Kirigami.Theme.backgroundColor
        border.width: 1
        border.color: Kirigami.Theme.disabledTextColor
        opacity: shown ? 0.95 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 120 } }

        Kirigami.Icon {
            anchors.centerIn: parent
            source: arrow.icon
            width: Kirigami.Units.iconSizes.small
            height: width
        }

        HoverHandler { cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: arrow.triggered() }
    }
}
