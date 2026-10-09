// "Pure black" switched on and off again in Settings: the surfaces follow
// both ways, without a restart. Logs anything still black after "off".
import QtQuick
import org.kde.kirigami as Kirigami
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    function walk(item, depth) {
        if (!item || depth > 16) return
        if (String(item.Kirigami.Theme.backgroundColor) === "#000000")
            console.warn("[test] still black: depth " + depth + " " + String(item).split("(")[0]
                         + " inherit=" + item.Kirigami.Theme.inherit)
        for (let i = 0; i < item.children.length; i++) root.walk(item.children[i], depth + 1)
    }
    Timer {
        interval: 3000; running: true; repeat: true
        onTriggered: {
            root.step++
            if (root.step === 1) root.goSettings()
            if (root.step === 2) { console.warn("[test] refs before " + [0,1,2,6].map((i) => root.platformSurfaces(i)[0])); backend.setThemeOled(true) }
            if (root.step === 3) { console.warn("[test] refs while on " + [0,1,2,6].map((i) => root.platformSurfaces(i)[0])); windowChrome.saveScreenshot(root, testShots + "/on.png"); backend.setThemeOled(false) }
            if (root.step === 4) {
                windowChrome.saveScreenshot(root, testShots + "/off.png")
                root.walk(root.windowRoot, 0)
                let page = root.pageStack.currentItem
                console.warn("[test] window colour " + root.color + ", page background "
                             + (page.background ? page.background.color : "none"))
                Qt.quit()
            }
        }
    }
}
