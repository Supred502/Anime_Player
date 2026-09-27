// Opens Settings (the AniList login is at the top when logged out) and
// saves a picture.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("SettingsPage.qml")
    Timer {
        interval: 4000; running: true
        onTriggered: {
            shot.start()
        }
    }
    Timer { id: shot; interval: 800; onTriggered: { windowChrome.saveScreenshot(root, testShots + "/settings-login.png"); Qt.quit() } }
}
