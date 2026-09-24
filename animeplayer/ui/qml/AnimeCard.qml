// One poster card, shared by every grid and row in the app (the home rows,
// browse, search results), so they can't drift apart in size, spacing or
// hover behaviour the way two hand-maintained copies of this layout did.
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
    property string scoreText: ""        // top-left pill, e.g. "8.6"
    property string rankText: ""         // big number in the corner, for ranked rows
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

    readonly property bool hovered: hoverHandler.hovered

    signal clicked()

    ColumnLayout {
        anchors.fill: parent
        spacing: Kirigami.Units.smallSpacing

        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: card.posterHeight

            // The frame scales on hover, so the scaling has to happen inside a
            // fixed-size Item rather than on the laid-out item itself --
            // scaling a layout child makes it overlap its neighbours by half
            // the growth in every direction, which in a tight grid reads as
            // the row jittering.
            Rectangle {
                id: posterFrame
                anchors.fill: parent
                radius: Kirigami.Units.mediumSpacing
                clip: true
                color: Kirigami.Theme.alternateBackgroundColor
                scale: card.hovered ? 1.03 : 1.0
                Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }

                Image {
                    id: poster
                    anchors.fill: parent
                    source: card.posterUrl
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    // Decode at the size actually drawn. A grid of full-size
                    // posters is a lot of pixels to keep around for boxes this
                    // small, and sourceSize also stops the scale animation
                    // resampling the original every frame.
                    sourceSize.width: Math.max(1, Math.round(card.width * 2))
                    // A visible placeholder beats a flash of empty frame while
                    // a whole grid of posters loads in.
                    Kirigami.Icon {
                        anchors.centerIn: parent
                        source: "video-television"
                        width: Kirigami.Units.iconSizes.large
                        height: width
                        opacity: 0.35
                        visible: parent.status !== Image.Ready
                    }
                }

                // Bottom scrim. The pills sit on top of whatever the poster
                // happens to be, and a white-bottomed poster made white pill
                // text invisible; a gradient reads as part of the art rather
                // than as a box behind the text.
                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: parent.height * 0.35
                    visible: card.textOf(card.cornerText) !== "" || card.textOf(card.rankText) !== ""
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: "transparent" }
                        GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.75) }
                    }
                }

                // Hover affordance: dim the art and put a play glyph on it, so
                // it's obvious the whole poster is the click target rather
                // than just the title beneath it.
                Rectangle {
                    anchors.fill: parent
                    color: Qt.rgba(0, 0, 0, 0.45)
                    opacity: card.hovered ? 1 : 0
                    visible: opacity > 0
                    Behavior on opacity { NumberAnimation { duration: 120 } }

                    Rectangle {
                        anchors.centerIn: parent
                        width: Kirigami.Units.iconSizes.large + Kirigami.Units.largeSpacing
                        height: width
                        radius: width / 2
                        color: Kirigami.Theme.highlightColor
                        // Grows in from slightly small, so the overlay reads
                        // as appearing rather than as having been there all
                        // along under a fade.
                        scale: card.hovered ? 1 : 0.8
                        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutBack } }

                        Kirigami.Icon {
                            anchors.centerIn: parent
                            // Nudged right by an eighth of its width: the
                            // glyph is a triangle, so its visual centre of
                            // mass sits left of its bounding box's centre and
                            // it looks off-centre in a circle without this.
                            anchors.horizontalCenterOffset: Math.round(width / 8)
                            source: Qt.resolvedUrl("../assets/images/play-button.png")
                            // The asset is a solid black glyph on transparency
                            // -- isMask throws the colour away and paints the
                            // shape in `color`, which is what lets one file
                            // work on the accent circle in every theme.
                            isMask: true
                            color: Kirigami.Theme.highlightedTextColor
                            width: Math.round(Kirigami.Units.iconSizes.medium * 0.8)
                            height: width
                        }
                    }
                }

                Pill {
                    visible: card.textOf(card.scoreText) !== ""
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.margins: Kirigami.Units.smallSpacing
                    text: "★ " + card.textOf(card.scoreText)
                    background: Qt.rgba(0, 0, 0, 0.7)
                    foreground: "#ffd166"
                }

                Pill {
                    visible: card.textOf(card.badgeText) !== ""
                    anchors.top: parent.top
                    anchors.right: parent.right
                    anchors.margins: Kirigami.Units.smallSpacing
                    text: card.textOf(card.badgeText)
                    background: Kirigami.Theme.highlightColor
                    foreground: Kirigami.Theme.highlightedTextColor
                }

                Pill {
                    visible: card.textOf(card.cornerText) !== ""
                    anchors.left: parent.left
                    anchors.bottom: parent.bottom
                    anchors.margins: Kirigami.Units.smallSpacing
                    anchors.bottomMargin: card.watchedFraction > 0
                        ? Kirigami.Units.smallSpacing + 4 : Kirigami.Units.smallSpacing
                    text: card.textOf(card.cornerText)
                    background: Qt.rgba(0, 0, 0, 0.7)
                    foreground: "white"
                }

                // Rank numeral for ranked rows (Trending, Top Airing). Drawn
                // oversized and half-transparent in the corner rather than as
                // another pill, so ten of them down a row read as a sequence
                // instead of as ten more labels competing with the titles.
                Controls.Label {
                    visible: card.textOf(card.rankText) !== ""
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.rightMargin: Kirigami.Units.smallSpacing
                    // Sits on the poster's bottom edge rather than hanging
                    // over it: the frame clips, so a bigger negative margin
                    // cut the numerals off halfway down (confirmed live).
                    // Digits have no descender, so pulling the label down by
                    // roughly the font's descent closes the gap under them
                    // without eating into the glyph itself.
                    anchors.bottomMargin: -Math.round(font.pixelSize * 0.16)
                    text: card.textOf(card.rankText)
                    color: "white"
                    opacity: 0.9
                    font.bold: true
                    font.pixelSize: Math.round(card.width * 0.28)
                }

                // Resume bar: where the user left off, on the poster itself,
                // so Continue Watching says how far in they are rather than
                // only which episode they were on.
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
            }

            // Outside the scaling frame: a border that scales with it ends up
            // 3px on one card and 2px on its neighbour mid-animation.
            Rectangle {
                anchors.fill: posterFrame
                radius: posterFrame.radius
                color: "transparent"
                border.width: 2
                border.color: Kirigami.Theme.highlightColor
                opacity: card.hovered ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 120 } }
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
            color: card.hovered ? Kirigami.Theme.highlightColor : Kirigami.Theme.textColor
            Behavior on color { ColorAnimation { duration: 120 } }

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

    // A rounded label chip. Four of these sit on the poster, and they were
    // four near-identical Rectangle+Label pairs before.
    component Pill: Rectangle {
        property alias text: pillLabel.text
        property color background: Qt.rgba(0, 0, 0, 0.7)
        property color foreground: "white"

        radius: height / 2
        color: background
        width: pillLabel.implicitWidth + Kirigami.Units.smallSpacing * 2.5
        height: pillLabel.implicitHeight + Kirigami.Units.smallSpacing

        Controls.Label {
            id: pillLabel
            anchors.centerIn: parent
            color: parent.foreground
            font.pixelSize: Kirigami.Theme.smallFont.pixelSize
            font.bold: true
        }
    }
}
