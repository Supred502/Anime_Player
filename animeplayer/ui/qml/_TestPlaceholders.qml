// Pictures of pages caught while loading, to see the placeholders.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    Timer {
        interval: 2500; running: true; repeat: true
        onTriggered: {
            root.step++
            if (root.step === 1) { root.goTo("seasonal", "SeasonalPage.qml"); shot.name = "seasonal"; shot.start() }
            if (root.step === 2) { root.goTo("schedule", "SchedulePage.qml"); shot.name = "schedule"; shot.start() }
            if (root.step === 3) { root.goBrowse(); shot.name = "browse"; shot.start() }
            if (root.step === 4) Qt.quit()
        }
    }
    Timer { id: shot; property string name; interval: 150; onTriggered: windowChrome.saveScreenshot(root, testShots + "/" + name + ".png") }
}
