// The card menu (right-click) and the spotlight's Library button.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property int step: 0
    function log(m) { console.warn("[test] " + m) }
    function findCard(item) {
        if (item.hasOwnProperty("slugId") && item.visible && item.title && item.width > 50) return item
        for (let i = 0; i < item.children.length; i++) { let f = findCard(item.children[i]); if (f) return f }
        return null
    }
    Connections { target: backend; function onQuickActionDone(m) { log("notice: " + m) } }
    Timer {
        interval: 3500; running: true; repeat: true
        onTriggered: {
            root.step++
            let p = root.pageStack.currentItem
            if (root.step === 1) { backend.createLibraryList("Test tab"); root.goBrowse() }
            if (root.step === 3) {
                let card = root.findCard(p)
                let r = card.mapToItem(null, card.width / 2, card.width * 0.6)
                windowChrome.click(root, r.x, r.y, true)
                log("right-clicked " + card.title + " menu info=" + JSON.stringify(root.cardMenuInfo))
            }
            if (root.step === 4) {
                windowChrome.saveScreenshot(root, testShots + "/menu.png")
                p.flickable.contentY += 300
            }
            if (root.step === 5) {
                root.goHome()
                log("after scrolling, menu still open: " + root.menuOpen())
            }
            if (root.step === 7) {
                let home = root.pageStack.currentItem
                let entry = home.spotlight[0]
                log("spotlight: " + entry.title + " (anilist " + entry.anilist_id + ")")
                backend.quickAddToLibrary(backend.libraryLists()[0].id, { anilist_id: entry.anilist_id, title: entry.title,
                                                                           poster_url: entry.banner_url })
            }
            if (root.step === 9) {
                log("tab now holds: " + JSON.stringify(backend.libraryItems(backend.libraryLists()[0].id).map((i) => i.title + " / " + i.slug_id)))
                Qt.quit()
            }
        }
    }
    function menuOpen() {
        let kids = gamepadNav.overlay.children
        for (let i = 0; i < kids.length; i++)
            if (kids[i].visible && String(kids[i]).indexOf("PopupItem") >= 0 && kids[i].height > 20) return true
        return false
    }
}
