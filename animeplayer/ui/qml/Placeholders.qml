// Grey shapes where content is about to be, pulsing gently while it loads:
// poster cards ("cards"), rows of a list ("rows") or episode squares
// ("squares"). They take the space the real thing will, so the page doesn't
// jump when it lands, and read as "coming" rather than "broken".
import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Item {
    id: root
    property string kind: "cards"
    property int count: 12
    property int columns: 6
    property real cellWidth: Kirigami.Units.gridUnit * 10
    property real spacing: Kirigami.Units.largeSpacing
    property real rowHeight: Kirigami.Units.gridUnit * 3
    readonly property color shade: Kirigami.Theme.alternateBackgroundColor

    implicitWidth: grid.implicitWidth
    implicitHeight: grid.implicitHeight

    property real phase: 0
    NumberAnimation on phase {
        from: 0; to: Math.PI * 2; duration: 1400
        loops: Animation.Infinite
        running: root.visible
    }

    GridLayout {
        id: grid
        width: parent.width
        columns: root.kind === "rows" ? 1 : root.columns
        columnSpacing: root.spacing
        rowSpacing: root.spacing
        Repeater {
            model: root.count
            Item {
                required property int index
                readonly property real pulse: 0.7 + 0.25 * Math.sin(root.phase + index * 0.6)
                Layout.preferredWidth: root.kind === "rows" ? grid.width : root.cellWidth
                Layout.preferredHeight: root.kind === "cards" ? Math.round(root.cellWidth * 1.5) + Kirigami.Units.gridUnit * 2.6
                                      : root.kind === "rows" ? root.rowHeight : root.cellWidth
                // A poster and two lines of title, or a row, or a square.
                Rectangle {
                    width: parent.width
                    height: root.kind === "cards" ? Math.round(root.cellWidth * 1.5) : parent.height
                    radius: Kirigami.Units.mediumSpacing
                    color: root.shade
                    opacity: parent.pulse
                }
                Rectangle {
                    visible: root.kind === "cards"
                    y: Math.round(root.cellWidth * 1.5) + Kirigami.Units.smallSpacing * 2
                    width: parent.width * 0.85; height: Kirigami.Units.gridUnit * 0.7
                    radius: height / 2; color: root.shade; opacity: parent.pulse
                }
                Rectangle {
                    visible: root.kind === "cards"
                    y: Math.round(root.cellWidth * 1.5) + Kirigami.Units.gridUnit * 1.5
                    width: parent.width * 0.5; height: Kirigami.Units.gridUnit * 0.6
                    radius: height / 2; color: root.shade; opacity: parent.pulse * 0.8
                }
            }
        }
    }
}
