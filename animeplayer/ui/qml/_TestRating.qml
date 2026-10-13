// The rating stars under a moving pointer: every half is reachable, and
// the row stays put while the score label changes.
import QtQuick
import org.kde.kirigami as Kirigami
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("SettingsPage.qml")
    function log(m) { console.warn("[test] " + m) }
    RatingStars {
        id: rs
        parent: root.contentItem
        anchors.centerIn: parent
        z: 999
        starSize: Kirigami.Units.iconSizes.medium
        onPicked: (score) => rs.score = score
    }
    property real px: 0
    property var seen: []
    property real x0: 0
    Timer {
        interval: 2000; running: true
        onTriggered: { root.x0 = rs.mapToItem(null, 0, 0).x; root.px = root.x0 + 1; sweep.start() }
    }
    Timer {
        id: sweep
        interval: 30; repeat: true
        onTriggered: {
            let o = rs.mapToItem(null, 0, 0)
            if (o.x !== root.x0) log("ROW MOVED to " + o.x + " at score " + rs.hovered)
            windowChrome.hover(root, root.px, o.y + rs.height / 2)
            if (rs.hovered !== root.seen[root.seen.length - 1]) root.seen.push(rs.hovered)
            root.px += 2
            if (root.seen.length && rs.hovered === 8.5 && rs.score !== 8.5) {
                windowChrome.click(root, root.px - 2, o.y + rs.height / 2, false)
                log("clicked at 8.5 -> score " + rs.score)
            }
            if (root.px > root.x0 + rs.width) {
                stop()
                log("previews in order: " + JSON.stringify(root.seen) + ", row x " + root.x0 + " -> " + rs.mapToItem(null, 0, 0).x)
                windowChrome.saveScreenshot(root, testShots + "/rating.png")
                Qt.quit()
            }
        }
    }
}
