// Opens one page and screenshots it (ANIMEPLAYER_TEST_MODE=<section>:<file>).
import QtQuick
AppWindow {
    id: root
    width: 1280; height: 800
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    Timer {
        interval: 7000; running: true; repeat: true
        onTriggered: {
            root.step++
            let parts = testMode.split(":")
            if (root.step === 1) root.goTo(parts[0], parts[1])
            if (root.step === 2 || root.step === 3) {
                let p = root.pageStack.currentItem
                if (root.step === 3 && p.flickable) p.flickable.contentY = p.flickable.contentHeight / 2
                windowChrome.saveScreenshot(root, testShots + "/" + parts[0] + "-" + root.step + ".png")
            }
            if (root.step === 4) Qt.quit()
        }
    }
}
