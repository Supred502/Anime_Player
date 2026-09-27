// F11 on a normal page, then the player's fullscreen and its Back button.
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
    Component.onCompleted: { backend.setAutoFullscreenEnabled(true); backend.search("Frieren") }
    Timer {
        interval: 5000; running: true; repeat: true
        onTriggered: {
            root.step++
            let p = root.pageStack.currentItem
            if (root.step === 1) {
                root.toggleAppFullscreen()
                log("F11: visibility=" + root.visibility + " fullscreen=" + (root.visibility === Window.FullScreen) + " navbar=" + root.chromeVisible)
                windowChrome.saveScreenshot(root, testShots + "/1-f11.png")
            }
            if (root.step === 2) {
                root.toggleAppFullscreen()
                log("F11 again: fullscreen=" + (root.visibility === Window.FullScreen) + " navbar=" + root.chromeVisible)
                root.goTo("browse", "DetailPage.qml", { anime: root.found })
            }
            if (root.step === 3) p.playEpisode(1, 300)
            if (root.step === 5) { p.controlsVisible = true; log("player: fullscreen=" + p.isFullscreen + " SHOOT-NOW") }
            if (root.step === 7) {
                root.pageStack.goBack()   // what the Back button does
                log("right after Back: page=" + root.pageStack.currentItem.title + " fullscreen=" + (root.visibility === Window.FullScreen) + " navbar=" + root.chromeVisible)
            }
            if (root.step === 8) {
                log("after Back: fullscreen=" + (root.visibility === Window.FullScreen) + " navbar=" + root.chromeVisible)
                Qt.quit()
            }
        }
    }
}
