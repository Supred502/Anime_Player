// A Library tab holding a show that arrived from AniList (another device
// added it) and isn't matched to the streaming source here yet: it opens,
// its page knows it's in the tab, and taking it out and back in works.
// Seed the throwaway database with such an item ("al:<id>") first:
//
//   ANIMEPLAYER_DB_PATH=<tmp>/a.db ANIMEPLAYER_TEST_QML=_TestLibrarySync.qml \
//   ANIMEPLAYER_TEST_SHOTS=<dir> python -m animeplayer
import QtQuick
import org.kde.kirigami as Kirigami

AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")

    property int step: 0
    property int tabId: 0
    function log(message) { console.warn("[test] " + message) }
    function shoot(name) {
        let path = testShots + "/" + name + ".png"
        log((windowChrome.saveScreenshot(root, path) ? "saved " : "FAILED ") + path)
    }
    function current() { return root.pageStack.currentItem }
    function items() {
        return backend.libraryItems(root.tabId).map((i) => i.slug_id + "/" + i.anilist_id).join(", ")
    }

    Timer {
        interval: 6000
        running: true
        repeat: true
        onTriggered: {
            root.step++
            let p = root.current()
            switch (root.step) {
            case 1:
                root.tabId = backend.libraryLists()[0].id
                root.goTo("library", "LibraryPage.qml")
                break
            case 2:
                p.showTab(String(root.tabId))
                log("cards: " + p.cards.map((c) => c.title + " slug=" + c.slug_id
                                             + " sourceSlug=" + p.sourceSlug(c)).join(" | "))
                root.shoot("1-tab")
                p.openShow(p.cards.find((c) => c.slug_id.startsWith("al:")))
                break
            case 3:
            case 4:
                log("page: " + (p.anime ? p.anime.title + " slug=" + p.anime.slug_id : "(none)")
                    + " anilistId=" + p.anilistId + " tabs=" + JSON.stringify(p.libraryTabs))
                if (root.step === 4) root.shoot("2-detail")
                break
            case 5:
                p.toggleLibrary(root.tabId)
                log("after removing: tabs=" + JSON.stringify(p.libraryTabs) + " items=" + root.items())
                break
            case 6:
                p.toggleLibrary(root.tabId)
                log("after adding back: tabs=" + JSON.stringify(p.libraryTabs) + " items=" + root.items())
                root.shoot("3-back-in")
                break
            case 7: Qt.quit(); break
            }
        }
    }
}
