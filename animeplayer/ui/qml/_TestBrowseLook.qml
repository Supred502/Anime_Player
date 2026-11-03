// Browse with the filters open, for a look (screenshot from outside).
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("BrowsePage.qml")
    Timer { interval: 1500; running: true; onTriggered: { root.pageStack.currentItem.filtersOpen = true; console.warn("[test] open") } }
    function walk(i, d) { if (!i || d > 30) return; if (i.displayText !== undefined && i.textRole !== undefined) console.warn("[test] combo h " + i.height + " ih " + i.implicitHeight + " content " + i.contentItem.implicitHeight + " bg " + i.background.implicitHeight + " tp " + i.topPadding + " bp " + i.bottomPadding + " w " + i.width + " lp " + i.leftPadding + " rp " + i.rightPadding + " ind " + i.indicator); for (let c of i.children) walk(c, d + 1) }
    Timer { interval: 5000; running: true; onTriggered: root.walk(root.pageStack.currentItem, 0) }
    Timer { interval: 12000; running: true; onTriggered: Qt.quit() }
}
