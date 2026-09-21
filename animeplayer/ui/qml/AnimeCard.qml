// One poster card, shared by every grid in the app (Home's rows and the
// search results), so they can't drift apart in size, spacing or hover
// behaviour the way two hand-maintained copies of this layout did.
//
// Two rules here exist specifically to keep a grid of these looking like a
// grid rather than a ragged pile:
//   * the poster is a fixed 2:3 box (the standard anime poster ratio), so it
//     never changes shape as the window resizes; and
//   * the title block always reserves two lines whether the title needs one
//     or two, so every card in a row is exactly as tall as its neighbours and
//     the subtitles line up across the row.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Item {
    id: card

    property string posterUrl: ""
    property string title: ""
    property string subtitle: ""
    property string badgeText: ""        // top-right pill, e.g. an AniList status
    property string cornerText: ""       // bottom-left pill on the poster, e.g. "TV"
    property real watchedFraction: 0     // 0..1, draws a resume bar along the poster's bottom edge

    // A model role that exists but was never set reads back as `undefined`,
    // and QML renders that as the literal word. Every text property here is
    // filtered through this, so the worst a missing role can do is leave a
    // label blank -- a card once showed an "undefined" badge because one of
    // two producers feeding the same model didn't set this role.
    function textOf(value) { return value === undefined || value === null ? "" : String(value) }

    // The poster is a 2:3 box and the text block is a fixed two title lines
    // plus one subtitle line, so a caller that knows the column width knows
    // the whole card height: heightForWidth(w).
    //
    // Deliberately NOT exposed as implicitHeight derived from this item's own
    // width. A layout that sets the width from the column and the height from
    // implicitHeight makes the height depend on a width the same layout pass
    // is still deciding, and it settles with the poster collapsed -- measured
    // live: a card 436px wide reported a total height of 57px, the text block
    // alone. Callers pass the column width in explicitly instead.
    readonly property real textHeight: Math.ceil(titleLabel.lineHeight * 2 + subtitleLabel.implicitHeight
                                                 + Kirigami.Units.smallSpacing * 2)
    readonly property real posterHeight: Math.round(width * 1.5)
    function heightForWidth(w) { return Math.round(w * 1.5) + textHeight }

    signal clicked()

    ColumnLayout {
        anchors.fill: parent
        spacing: Kirigami.Units.smallSpacing

        Rectangle {
            id: posterFrame
            Layout.fillWidth: true
            Layout.preferredHeight: card.posterHeight
            radius: Kirigami.Units.smallSpacing
            clip: true
            color: Kirigami.Theme.alternateBackgroundColor
            border.width: hoverHandler.hovered ? 2 : 0
            border.color: Kirigami.Theme.highlightColor

            Image {
                anchors.fill: parent
                source: card.posterUrl
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                // A visible placeholder beats a flash of empty frame while a
                // whole grid of posters loads in.
                Kirigami.Icon {
                    anchors.centerIn: parent
                    source: "video-television"
                    width: Kirigami.Units.iconSizes.large
                    height: width
                    opacity: 0.35
                    visible: parent.status !== Image.Ready
                }
            }

            // Lifts the poster slightly on hover so a pointer has some feedback
            // beyond the cursor shape.
            scale: hoverHandler.hovered ? 1.02 : 1.0
            Behavior on scale { NumberAnimation { duration: 100 } }

            Rectangle {
                visible: card.textOf(card.badgeText) !== ""
                anchors.top: parent.top
                anchors.right: parent.right
                anchors.margins: Kirigami.Units.smallSpacing
                radius: height / 2
                color: Kirigami.Theme.highlightColor
                width: badgeLabel.implicitWidth + Kirigami.Units.largeSpacing
                height: badgeLabel.implicitHeight + Kirigami.Units.smallSpacing

                Controls.Label {
                    id: badgeLabel
                    anchors.centerIn: parent
                    text: card.textOf(card.badgeText)
                    color: Kirigami.Theme.highlightedTextColor
                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    font.bold: true
                }
            }

            Rectangle {
                visible: card.textOf(card.cornerText) !== ""
                anchors.left: parent.left
                anchors.bottom: parent.bottom
                anchors.margins: Kirigami.Units.smallSpacing
                radius: Kirigami.Units.smallSpacing / 2
                color: Qt.rgba(0, 0, 0, 0.65)
                width: cornerLabel.implicitWidth + Kirigami.Units.smallSpacing * 2
                height: cornerLabel.implicitHeight + Kirigami.Units.smallSpacing / 2

                Controls.Label {
                    id: cornerLabel
                    anchors.centerIn: parent
                    text: card.textOf(card.cornerText)
                    color: "white"
                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                    font.bold: true
                }
            }

            // Resume bar: where the user left off, on the poster itself, so
            // Continue Watching says how far in they are rather than only which
            // episode they were on.
            Rectangle {
                visible: card.watchedFraction > 0
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 4
                color: Qt.rgba(0, 0, 0, 0.5)

                Rectangle {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: parent.width * Math.min(1, card.watchedFraction)
                    color: Kirigami.Theme.highlightColor
                }
            }

            HoverHandler {
                id: hoverHandler
                cursorShape: Qt.PointingHandCursor
            }
            TapHandler {
                onTapped: card.clicked()
            }
        }

        Controls.Label {
            id: titleLabel
            Layout.fillWidth: true
            // Fixed two-line box -- see the note at the top of this file.
            // minimumHeight as well as preferredHeight: a ColumnLayout that
            // finds itself even a fraction of a pixel short compresses items
            // down towards their implicit height, and one line is a Label's
            // implicit height -- which showed up as long titles eliding at the
            // end of line one inside a box visibly tall enough for two.
            Layout.minimumHeight: lineHeight * 2
            Layout.preferredHeight: lineHeight * 2
            // lineSpacing (not FontMetrics.height, which is only ascent plus
            // descent), rounded up. Both halves matter: measured live, an
            // exactly-two-lines-tall box of 35.375px for a 17.6875px line
            // spacing still laid out as one elided line, and only a box with
            // a little slack (36px) actually took the second line.
            readonly property real lineHeight: Math.ceil(fontMetrics.lineSpacing)
            text: card.textOf(card.title)
            wrapMode: Text.WordWrap
            font.bold: true
            maximumLineCount: 2
            elide: Text.ElideRight
            verticalAlignment: Text.AlignTop

            FontMetrics { id: fontMetrics; font: titleLabel.font }
        }

        Controls.Label {
            id: subtitleLabel
            Layout.fillWidth: true
            text: card.textOf(card.subtitle)
            opacity: 0.7
            elide: Text.ElideRight
            font.pixelSize: Kirigami.Theme.smallFont.pixelSize
        }
    }
}
