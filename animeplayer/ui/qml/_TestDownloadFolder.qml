// Moves the download folder with an episode already saved, through the
// same calls the Settings page's "Move them" button makes, then pictures
// the Downloads section of Settings.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("SettingsPage.qml")
    property int step: 0
    function log(m) { console.warn("[test] " + m) }
    Connections {
        target: backend
        function onDownloadFolderMoved(message) { log("status: " + message) }
    }
    Timer {
        interval: 3000; running: true; repeat: true
        onTriggered: {
            root.step++
            let p = root.pageStack.currentItem
            if (root.step === 1) {
                log("before: folder=" + p.downloadFolder + " bytes=" + p.downloadBytes)
                p.pendingFolder = testShots + "/elsewhere"
                backend.setDownloadFolder(p.pendingFolder, true)
                p.refreshFolder()
            }
            if (root.step === 2) {
                p.refreshDownloadSize()
                log("after: folder=" + p.downloadFolder + " default=" + p.defaultFolder + " bytes=" + p.downloadBytes)
                p.flickable.contentY = p.flickable.contentHeight * 0.42
                shot.start()
            }
            if (root.step === 3) Qt.quit()
        }
    }
    Timer {
        id: shot
        interval: 500
        onTriggered: windowChrome.saveScreenshot(root, testShots + "/settings.png")
    }
}
