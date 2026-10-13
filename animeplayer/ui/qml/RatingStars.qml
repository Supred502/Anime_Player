// A score out of 10 in halves, as ten stars. Hovering previews, clicking sets, and
// clicking the star that is already the score clears it -- the same
// behaviour as Browse's minimum-rating stars, so there's one way to do it.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

RowLayout {
    id: stars
    property real score: 0          // 0-10; 0 means unrated
    property int starSize: Kirigami.Units.iconSizes.smallMedium
    signal picked(real score)

    property real hovered: 0        // score under the pointer, 0.5-10; 0 when none
    readonly property real shown: hovered > 0 ? hovered : score
    // No gaps: the pointer crossing one dropped the preview for a moment.
    spacing: 0

    // Each star is an outline with a filled star over it, clipped to how
    // much of it the score covers -- so 8.5 is eight full stars and a half.
    // AniList scores in halves; the left half of a star picks x.5.
    Repeater {
        model: 10
        Item {
            id: star
            required property int index
            readonly property real fill: Math.max(0, Math.min(1, stars.shown - index))
            implicitWidth: stars.starSize + 2
            implicitHeight: stars.starSize

            Kirigami.Icon {
                width: stars.starSize
                height: stars.starSize
                source: "star-shape-outline-symbolic"
                isMask: true
                color: Kirigami.Theme.disabledTextColor
            }
            Item {
                width: stars.starSize * (star.fill >= 1 ? 1 : star.fill >= 0.5 ? 0.5 : 0)
                height: parent.height
                clip: true
                Kirigami.Icon {
                    width: stars.starSize
                    height: stars.starSize
                    source: "star-shape-symbolic"
                    isMask: true
                    color: Kirigami.Theme.neutralTextColor
                }
            }

            HoverHandler {
                id: starHover
                cursorShape: Qt.PointingHandCursor
                readonly property real value: star.index + (point.position.x < stars.starSize / 2 ? 0.5 : 1)
                onValueChanged: if (hovered) stars.hovered = value
                onHoveredChanged: {
                    if (hovered) stars.hovered = value
                    else if (Math.ceil(stars.hovered) === star.index + 1) stars.hovered = 0
                }
            }
            TapHandler {
                onTapped: (eventPoint) => {
                    let value = star.index + (eventPoint.position.x < stars.starSize / 2 ? 0.5 : 1)
                    stars.picked(stars.score === value ? 0 : value)
                }
            }
        }
    }
    Controls.Label {
        id: scoreLabel
        Layout.leftMargin: Kirigami.Units.smallSpacing
        text: stars.shown > 0 ? stars.shown + "/10" : "not rated"
        // One width for every score: a label that grew from "8/10" to
        // "8.5/10" moved the stars under the pointer, which changed the score.
        Layout.preferredWidth: widest.width
        TextMetrics { id: widest; font: scoreLabel.font; text: "not rated" }
        opacity: 0.7
        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
    }
}
