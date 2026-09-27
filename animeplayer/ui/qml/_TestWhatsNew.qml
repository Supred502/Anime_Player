// The "What's new" dialog, with notes the way the release script makes them.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    Timer {
        interval: 3000; running: true
        onTriggered: {
            backend.whatsNew("0.4.0", "- Choose where downloads are saved, and move what's already there\n"
                + "- Continue is its own page; Browse can no longer get stuck on it\n"
                + "- A fresh spotlight every launch, with why each show is there; Sub and Dub apart\n"
                + "- Episode list view: thumbnails and titles, beside the number grid\n"
                + "- Seasonal page: a whole anime season at a time")
            shot.start()
        }
    }
    Timer { id: shot; interval: 1500; onTriggered: { windowChrome.saveScreenshot(root, testShots + "/whatsnew.png"); Qt.quit() } }
}
