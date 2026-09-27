// Using the app with a game controller (see gamepad.py for the actions).
//
// Everywhere but the player: the D-pad (or left stick) moves a highlight to
// the nearest clickable thing in that direction -- any button, card, episode
// cell or chip, found by looking at what's on screen rather than by every
// page listing its own -- and A clicks it, with a real click, so nothing in
// the pages needed to change. Scroll areas follow the highlight. B goes back
// (or closes whatever is open), LB/RB step through the nav bar, X
// right-clicks (save an episode, a card's menu), Y goes to search, Start is
// fullscreen.
//
// In the player the buttons are the player's own (see PlayerPage's
// gamepadAction), until View/Select hands the highlight over to its
// on-screen controls.
//
// Text boxes open an on-screen keyboard: there's no keyboard on a controller.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import QtQuick.Templates as T
import org.kde.kirigami as Kirigami

Item {
    id: nav

    required property var window
    // Shown once a controller is used; hidden again when the mouse moves.
    property bool active: false
    property Item target: null
    property bool playerMenu: false

    readonly property Item overlay: Controls.Overlay.overlay
    readonly property var page: nav.window.pageStack.currentItem
    readonly property bool onPlayer: !!nav.page && typeof nav.page.gamepadAction === "function"

    // ---- What can be pressed ------------------------------------------------

    // T.*, not Controls.*: a style's own Button (Fusion's, Breeze's) derives
    // from the template type, not from the Controls one, and failed the
    // check -- so no plain button could be reached, only cards.
    function isClickable(item) {
        if (item instanceof T.AbstractButton || item instanceof T.TextField
                || item instanceof T.ComboBox || item instanceof T.Slider)
            return true
        let data = item.data
        for (let i = 0; i < data.length; i++) {
            let d = data[i]
            if (d && String(d).startsWith("QQuickTapHandler") && d.enabled
                    && (d.acceptedButtons & Qt.LeftButton)) return true
        }
        return false
    }

    function collect(item, out, depth) {
        if (!item || !item.visible || item.opacity <= 0.01 || depth > 60) return
        if (item.width > 4 && item.height > 4 && item.enabled && nav.isClickable(item)) out.push(item)
        let kids = item.children
        for (let i = 0; i < kids.length; i++) nav.collect(kids[i], out, depth + 1)
    }

    // The open popup's contents if there is one (a dialog, a menu, the
    // keyboard), else the window.
    function scope() {
        let popups = nav.overlay.children
        for (let i = popups.length - 1; i >= 0; i--) {
            let p = popups[i]
            if (p.visible && p.width > 0 && String(p).indexOf("PopupItem") >= 0
                    && nav.takesController(p) && nav.hasSomethingToPress(p)) return p
        }
        return nav.window.contentItem.parent
    }
    // The update card sits in a corner without blocking anything; it
    // mustn't trap the highlight either. It's reached like anything else.
    // A tooltip is a popup too. Resting the highlight on an episode showed
    // its tooltip, which then counted as an open dialog with nothing in it
    // to move to -- and the controller was stuck. Only popups with
    // something to press take over.
    function hasSomethingToPress(item) {
        let found = []
        nav.collect(item, found, 0)
        return found.length > 0
    }
    function takesController(popupItem) {
        for (let i = 0; i < popupItem.children.length; i++)
            if (popupItem.children[i].objectName === "updateCard") return false
        return popupItem.objectName !== "updateCard"
    }

    function candidates() {
        let out = []
        nav.collect(nav.scope(), out, 0)
        // Only what the window actually shows, or a scroll away from it.
        let w = nav.window.width, h = nav.window.height
        return out.filter(function(item) {
            let r = nav.rectOf(item)
            return r.x + r.width > -w && r.x < 2 * w && r.y + r.height > -h * 3 && r.y < h * 4
        })
    }

    function rectOf(item) {
        let p = item.mapToItem(null, 0, 0)
        return { x: p.x, y: p.y, width: item.width, height: item.height }
    }
    function alive(item) {
        try { return !!item && item.visible && item.width > 0 && nav.window.contentItem !== null
                    && item.mapToItem(null, 0, 0) !== undefined } catch (e) { return false }
    }

    // ---- Moving ---------------------------------------------------------------

    function move(direction) {
        let all = nav.candidates()
        if (all.length === 0) return
        if (!nav.alive(nav.target) || all.indexOf(nav.target) < 0) {
            nav.focusOn(nav.first(all))
            return
        }
        let from = nav.rectOf(nav.target)
        let cx = from.x + from.width / 2, cy = from.y + from.height / 2
        let best = null, bestScore = Infinity
        for (let item of all) {
            if (item === nav.target || nav.contains(nav.target, item)) continue
            let r = nav.rectOf(item)
            let x = r.x + r.width / 2, y = r.y + r.height / 2
            let along, across
            if (direction === "left")  { along = from.x - (r.x + r.width); across = y - cy }
            if (direction === "right") { along = r.x - (from.x + from.width); across = y - cy }
            if (direction === "up")    { along = from.y - (r.y + r.height); across = x - cx }
            if (direction === "down")  { along = r.y - (from.y + from.height); across = x - cx }
            // Overlapping edges count as zero distance, not as behind.
            if (along < -Math.min(from.width, from.height) / 2) continue
            let score = Math.max(0, along) + Math.abs(across) * 2.2
            if (score < bestScore) { best = item; bestScore = score }
        }
        if (best) nav.focusOn(best)
    }
    function contains(outer, inner) {
        for (let p = inner.parent; p; p = p.parent) if (p === outer) return true
        return false
    }
    // Where to start: the top-left of the page (not the nav bar), or the
    // first thing in a popup.
    function first(all) {
        let headerBottom = nav.window.header && nav.window.header.visible ? nav.window.header.height : 0
        let inPage = all.filter((i) => nav.rectOf(i).y >= headerBottom + 40)
        let pool = inPage.length > 0 && nav.scope() === nav.window.contentItem.parent ? inPage : all
        pool.sort(function(a, b) {
            let ra = nav.rectOf(a), rb = nav.rectOf(b)
            return (ra.y - rb.y) * 3 + (ra.x - rb.x) > 0 ? 1 : -1
        })
        return pool[0]
    }

    function focusOn(item) {
        nav.target = item
        nav.active = true
        nav.scrollIntoView(item)
        Qt.callLater(nav.pointAt, item)
    }
    // The pointer follows, so the highlighted card shows its hover state
    // (and, if left there, its preview).
    function pointAt(item) {
        if (!nav.alive(item)) return
        let r = nav.rectOf(item)
        nav.lastPointer = Qt.point(r.x + r.width / 2, r.y + r.height / 2)
        windowChrome.hover(nav.window, nav.lastPointer.x, nav.lastPointer.y)
    }

    function scrollIntoView(item) {
        for (let p = item.parent; p; p = p.parent) {
            if (!(p instanceof Flickable)) continue
            let r = item.mapToItem(p.contentItem, 0, 0)
            let margin = Kirigami.Units.gridUnit
            if (p.contentHeight > p.height) {
                let top = p.contentY, bottom = p.contentY + p.height
                if (r.y < top + margin) p.contentY = Math.max(p.originY, r.y - margin * 3)
                else if (r.y + item.height > bottom - margin)
                    p.contentY = Math.min(p.originY + p.contentHeight - p.height, r.y + item.height - p.height + margin * 3)
            }
            if (p.contentWidth > p.width) {
                let left = p.contentX, right = p.contentX + p.width
                if (r.x < left + margin) p.contentX = Math.max(p.originX, r.x - margin * 2)
                else if (r.x + item.width > right - margin)
                    p.contentX = Math.min(p.originX + p.contentWidth - p.width, r.x + item.width - p.width + margin * 2)
            }
        }
    }

    function press(right) {
        if (!nav.alive(nav.target)) { nav.move("down"); return }
        if (!right && (nav.target instanceof T.TextField)) { keyboard.openFor(nav.target); return }
        if (nav.target instanceof T.Slider) return
        let r = nav.rectOf(nav.target)
        nav.lastPointer = Qt.point(r.x + r.width / 2, r.y + r.height / 2)
        windowChrome.click(nav.window, nav.lastPointer.x, nav.lastPointer.y, !!right)
        // A click that opened or closed something moves the scene; the
        // highlight re-finds its footing on the next move.
        Qt.callLater(function() { if (!nav.alive(nav.target)) nav.target = null })
    }

    function back() {
        let s = nav.scope()
        if (keyboard.opened) { keyboard.close(); return }
        if (s !== nav.window.contentItem.parent) {
            // A popup (menu, dialog): Escape closes it, as on a keyboard.
            windowChrome.key(nav.window, Qt.Key_Escape)
            nav.target = null
            return
        }
        nav.target = null
        nav.window.pageStack.goBack()
    }

    function stepSection(delta) {
        let order = [["home", function() { nav.window.goHome() }], ["browse", function() { nav.window.goBrowse() }],
                     ["seasonal", function() { nav.window.goTo("seasonal", "SeasonalPage.qml") }],
                     ["continue", function() { nav.window.goContinue() }],
                     ["library", function() { nav.window.goTo("library", "LibraryPage.qml") }],
                     ["schedule", function() { nav.window.goTo("schedule", "SchedulePage.qml") }],
                     ["words", function() { nav.window.goTo("words", "WordsPage.qml") }],
                     ["stats", function() { nav.window.goTo("stats", "StatsPage.qml") }],
                     ["settings", function() { nav.window.goSettings() }]]
        let i = order.findIndex((e) => e[0] === nav.window.section)
        i = (Math.max(0, i) + delta + order.length) % order.length
        nav.target = null
        order[i][1]()
    }

    function handle(action) {
        nav.active = true
        if (keyboard.opened && keyboard.handle(action)) return
        if (nav.onPlayer && !nav.playerMenu) {
            if (action === "view") { nav.playerMenu = true; nav.page.gamepadAction("show"); nav.move("down"); return }
            nav.page.gamepadAction(action)
            return
        }
        switch (action) {
        case "left": case "right":
            // A highlighted slider moves rather than handing the highlight on.
            if (nav.alive(nav.target) && nav.target instanceof T.Slider) {
                if (action === "left") nav.target.decrease(); else nav.target.increase()
                nav.target.moved()
                break
            }
            nav.move(action); break
        case "up": case "down": nav.move(action); break
        case "accept": nav.press(false); break
        case "x": nav.press(true); break
        case "back":
            if (nav.onPlayer && nav.playerMenu) { nav.playerMenu = false; nav.target = null; return }
            nav.back(); break
        case "lb": nav.stepSection(-1); break
        case "rb": nav.stepSection(1); break
        case "y":
            nav.window.goBrowse()
            Qt.callLater(function() {
                let field = nav.findField(nav.window.pageStack.currentItem)
                if (field) keyboard.openFor(field)
            })
            break
        case "menu": nav.window.toggleAppFullscreen(); break
        case "view": if (nav.onPlayer) { nav.playerMenu = false; nav.target = null } break
        }
    }
    function keyboardText() { return keyboard.field ? keyboard.field.text : "" }
    function keyboardOpen() { return keyboard.opened }
    function findField(item) {
        if (!item) return null
        if (item instanceof T.TextField && item.visible) return item
        let parts = item.children
        for (let i = 0; i < parts.length; i++) { let f = nav.findField(parts[i]); if (f) return f }
        if (item.header) return nav.findField(item.header)
        return null
    }

    Connections {
        target: gamepad
        function onAction(name) { nav.handle(name) }
        function onConnected(name) {
            nav.window.showPassiveNotification(name + " connected -- A select, B back, LB/RB switch pages, Y search", "long")
        }
    }
    // A page change leaves the old highlight behind.
    Connections {
        target: nav.window.pageStack
        function onCurrentItemChanged() { nav.target = null; nav.playerMenu = false }
    }
    // The real mouse takes over again -- told apart from the pointer moves
    // made here by where the pointer is: the scene re-sends hover whenever
    // things move under a still pointer, so timing alone got it wrong.
    property point lastPointer: Qt.point(-1, -1)
    HoverHandler {
        parent: nav.window.contentItem.parent
        onPointChanged: {
            let p = point.scenePosition
            if (Math.abs(p.x - nav.lastPointer.x) > 3 || Math.abs(p.y - nav.lastPointer.y) > 3) nav.active = false
        }
    }

    // ---- The highlight ------------------------------------------------------
    Rectangle {
        id: focusRing
        parent: nav.overlay
        z: 990
        visible: nav.active && nav.alive(nav.target) && !(nav.onPlayer && !nav.playerMenu)
        color: "transparent"
        radius: Kirigami.Units.smallSpacing * 2
        border.width: 3
        // The app's accent: the overlay sits outside every themed page.
        border.color: backend && backend.theme.accent ? backend.theme.accent : Kirigami.Theme.highlightColor
        // Follows its target through scrolling and layout changes.
        Timer {
            interval: 16; repeat: true
            running: focusRing.visible || nav.active
            onTriggered: {
                if (!nav.alive(nav.target)) return
                let r = nav.target.mapToItem(nav.overlay, 0, 0)
                focusRing.x = r.x - 4
                focusRing.y = r.y - 4
                focusRing.width = nav.target.width + 8
                focusRing.height = nav.target.height + 8
            }
        }
    }

    // ---- On-screen keyboard -------------------------------------------------
    Controls.Popup {
        id: keyboard
        property var field: null
        Kirigami.Theme.inherit: true
        parent: nav.overlay
        x: (parent.width - width) / 2
        y: parent.height - height - Kirigami.Units.gridUnit * 2
        modal: true
        padding: Kirigami.Units.largeSpacing
        closePolicy: Controls.Popup.CloseOnEscape | Controls.Popup.CloseOnPressOutside

        function openFor(f) {
            keyboard.field = f
            keyboard.open()
            Qt.callLater(function() { nav.focusOn(keyGrid.children[0]) })
        }
        function type(text) { if (keyboard.field) keyboard.field.text += text }
        function erase() { if (keyboard.field) keyboard.field.text = keyboard.field.text.slice(0, -1) }
        function done() {
            let f = keyboard.field
            keyboard.close()
            if (f) f.accepted()
        }
        // Shortcuts while it's open: X deletes, Y adds a space, Start is done.
        function handle(action) {
            if (action === "x") { keyboard.erase(); return true }
            if (action === "y") { keyboard.type(" "); return true }
            if (action === "menu") { keyboard.done(); return true }
            return false
        }

        background: Rectangle {
            radius: Kirigami.Units.smallSpacing * 2
            color: Kirigami.Theme.alternateBackgroundColor
            border.color: Kirigami.Theme.highlightColor
        }

        contentItem: ColumnLayout {
            spacing: Kirigami.Units.smallSpacing
            Controls.Label {
                Layout.fillWidth: true
                text: (keyboard.field ? keyboard.field.text : "") + "│"
                font.pixelSize: Kirigami.Units.gridUnit * 1.2
                elide: Text.ElideLeft
            }
            GridLayout {
                id: keyGrid
                columns: 10
                columnSpacing: Kirigami.Units.smallSpacing
                rowSpacing: Kirigami.Units.smallSpacing
                Repeater {
                    model: "1234567890qwertyuiopasdfghjkl'zxcvbnm-.!".split("")
                    Controls.Button {
                        required property string modelData
                        Kirigami.Theme.inherit: true
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 2.4
                        Layout.preferredHeight: Kirigami.Units.gridUnit * 2.2
                        text: modelData
                        focusPolicy: Qt.NoFocus
                        onClicked: keyboard.type(modelData)
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Controls.Button {
                    Kirigami.Theme.inherit: true
                    Layout.fillWidth: true
                    text: "Space (Y)"
                    focusPolicy: Qt.NoFocus
                    onClicked: keyboard.type(" ")
                }
                Controls.Button {
                    Kirigami.Theme.inherit: true
                    text: "Delete (X)"
                    icon.name: "edit-clear-symbolic"
                    focusPolicy: Qt.NoFocus
                    onClicked: keyboard.erase()
                }
                AppButton {
                    text: "Search (Start)"
                    accented: true
                    focusPolicy: Qt.NoFocus
                    onClicked: keyboard.done()
                }
            }
        }
    }
}
