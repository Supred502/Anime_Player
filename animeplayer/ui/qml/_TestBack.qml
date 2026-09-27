// What "back" from the player leaves behind.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    property var found: null
    function log(m) { console.warn("[test] " + m) }
    Connections {
        target: backend
        function onSearchFinished(results) { if (!root.found && results.length) root.found = results[0] }
    }
    Component.onCompleted: { backend.setAutoFullscreenEnabled(testMode.indexOf("windowed") < 0); backend.search("Dorohedoro") }
    Timer {
        interval: 5000; running: true; repeat: true
        onTriggered: {
            root.step++
            let p = root.pageStack.currentItem
            if (root.step === 1) root.goTo("browse", "DetailPage.qml", { anime: root.found })
            if (root.step === 2) p.playEpisode(1, 300)
            if (root.step === 4) {
                log("before back: depth=" + root.pageStack.depth + " current=" + p.title + " key=" + testMode)
                if (testMode.indexOf("alt-left") === 0) windowChrome.testKey(root, Qt.Key_Left, Qt.AltModifier)
                else if (testMode.indexOf("back-key") === 0) windowChrome.testKey(root, Qt.Key_Back, 0)
                else if (testMode === "backspace") windowChrome.testKey(root, Qt.Key_Backspace, 0)
                else if (testMode === "escape") windowChrome.testKey(root, Qt.Key_Escape, 0)
                else if (testMode === "mute") windowChrome.testKey(root, Qt.Key_M, 0)
                else root.pageStack.goBack()
            }
            if (root.step === 5) {
                log("after goBack: depth=" + root.pageStack.depth + " currentIndex=" + root.pageStack.currentIndex
                    + " current=" + p.title + " last=" + (root.pageStack.lastItem ? root.pageStack.lastItem.title : "?")
                    + " fullscreen=" + (root.visibility === Window.FullScreen) + " state=" + JSON.stringify(backend.phoneState ? "" : ""))
            }
            if (root.step === 6) Qt.quit()
        }
    }
}
