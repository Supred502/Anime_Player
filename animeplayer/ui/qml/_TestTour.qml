// Walks the main pages and saves a picture of each -- used to compare the
// Linux build with the Windows one, which runs this in CI where nobody can
// look at the screen. Run with:
//
//   ANIMEPLAYER_TEST_QML=_TestTour.qml ANIMEPLAYER_TEST_SHOTS=<dir> python -m animeplayer
//
// Pictures are taken by the window itself (QQuickWindow::grabWindow), so it
// works on a headless machine too.
import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")

    property int step: 0
    property var found: null
    readonly property string shots: testShots

    function log(message) { console.warn("[test] " + message) }
    function shoot(name) {
        let path = root.shots + "/" + name + ".png"
        log((windowChrome.saveScreenshot(root, path) ? "saved " : "FAILED ") + path
            + " window " + root.width + "x" + root.height
            + " content " + root.contentItem.width + "x" + root.contentItem.height)
        let chain = [], n = root.contentItem
        while (n) { chain.push(String(n).split("(")[0] + ":" + n.width + "x" + n.height); n = n.parent }
        log("chain " + chain.join(" < "))
    }

    // Items that stick out past the right edge of the page, outermost first
    // -- how a layout that is wider than the window gets tracked down.
    function reportOverflow(page) {
        let found = []
        function walk(item, depth) {
            if (!item || depth > 14 || found.length > 12) return
            let kids = item.children
            for (let i = 0; i < kids.length; i++) {
                let k = kids[i]
                if (!k.visible || k.width <= 0) continue
                let right = k.mapToItem(page, k.width, 0).x
                if (right > page.width + 1) {
                    found.push(depth + " " + String(k).split("(")[0] + " right=" + Math.round(right)
                               + " w=" + Math.round(k.width) + " implicitW=" + Math.round(k.implicitWidth))
                }
                walk(k, depth + 1)
            }
        }
        walk(page, 0)
        log("page width " + page.width + "; overflowing:\n  " + found.join("\n  "))
    }

    Connections {
        target: backend
        function onSearchFinished(results) { if (!root.found && results.length) root.found = results[0] }
    }

    // Each stop: go there, wait for it to load, take the picture.
    readonly property var stops: [
        ["1-home", function() { backend.search("Frieren") }],
        ["2-browse", function() { root.goBrowse() }],
        ["3-settings", function() { root.goSettings() }],
        ["4-detail", function() { if (root.found) root.goTo("browse", "DetailPage.qml", { anime: root.found }) }],
        ["5-stats", function() { root.goTo("stats", "StatsPage.qml") }],
        ["6-words", function() { root.goTo("words", "WordsPage.qml") }],
        ["7-update", function() {
            root.goHome()
            backend.updateAvailable("9.9.9", "- A test update\n- With notes", "installer")
        }]
    ]

    Timer {
        interval: 7000
        running: true
        repeat: true
        onTriggered: {
            if (root.step >= root.stops.length) { log("done"); Qt.quit(); return }
            root.stops[root.step][1]()
            shotTimer.name = root.stops[root.step][0]
            shotTimer.restart()
            root.step++
        }
    }
    Timer {
        id: shotTimer
        property string name
        interval: 6000
        onTriggered: {
            root.shoot(name)
            if (name === "4-detail") root.reportOverflow(root.pageStack.currentItem)
        }
    }
}
