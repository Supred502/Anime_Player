// Using the app with a game controller (see gamepad.py for the actions).
//
// Everywhere but the player: the D-pad (or left stick) moves a highlight to
// the nearest clickable thing in that direction -- any button, card, episode
// cell or chip, found by looking at what's on screen rather than by every
// page listing its own -- and A clicks it, with a real click, so nothing in
// the pages needed to change. Scroll areas glide after the highlight. B goes back
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
                    && nav.inScene(item) } catch (e) { return false }
    }
    // Still on screen, not a delegate a list has thrown away or put aside
    // for reuse: those keep their size and visibility, off in no-man's land.
    function inScene(item) {
        let root = nav.window.contentItem.parent
        for (let p = item; p; p = p.parent) if (p === root) return true
        return false
    }
    // Where the highlight last was, on screen. A list that rebuilds itself
    // (Browse loading its next page reassigns every card) takes the
    // highlighted card with it; the one now in its place carries on.
    property var lastSpot: null
    function standIn(all) {
        if (!nav.lastSpot) return null
        let cx = nav.lastSpot.x + nav.lastSpot.width / 2, cy = nav.lastSpot.y + nav.lastSpot.height / 2
        let best = null, bestDistance = Math.max(nav.lastSpot.width, nav.lastSpot.height)
        for (let item of all) {
            let r = nav.rectOf(item)
            let d = Math.hypot(r.x + r.width / 2 - cx, r.y + r.height / 2 - cy)
            if (d < bestDistance) { best = item; bestDistance = d }
        }
        return best
    }
    function forget() { nav.target = null; nav.lastSpot = null }

    // ---- Moving ---------------------------------------------------------------

    // Left and right stay in the row: past its end the highlight stays put,
    // rather than leaping to whatever lies that way (a header button, the
    // next row) and scrolling the page after it. Up and down go to what's
    // above or below, the nearest row first.
    function move(direction) {
        let all = nav.candidates()
        if (all.length === 0) return
        if (!nav.alive(nav.target) || all.indexOf(nav.target) < 0) {
            let replacement = nav.standIn(all)
            if (!replacement) { nav.focusOn(nav.first(all)); return }
            nav.target = replacement
        }
        // Within the list or shelf it's in first; out of it only past its end.
        // A row scrolled out of the grid is still the grid's, and up goes
        // there, not to the search box that's nearer on screen.
        let area = nav.scrollAreaOf(nav.target)
        let best = area ? nav.pick(direction, all.filter((i) => nav.contains(area, i))) : null
        if (!best) best = nav.pick(direction, all)
        if (best) nav.focusOn(best)
    }
    function scrollAreaOf(item) {
        for (let p = item.parent; p; p = p.parent) if (p instanceof Flickable) return p
        return null
    }
    function pick(direction, all) {
        let from = nav.rectOf(nav.target)
        let horizontal = direction === "left" || direction === "right"
        let inLine = null, inLineScore = Infinity, cone = null, coneScore = Infinity
        for (let item of all) {
            if (item === nav.target || nav.contains(nav.target, item)) continue
            let r = nav.rectOf(item)
            let along
            if (direction === "left")  along = from.x - (r.x + r.width)
            if (direction === "right") along = r.x - (from.x + from.width)
            if (direction === "up")    along = from.y - (r.y + r.height)
            if (direction === "down")  along = r.y - (from.y + from.height)
            // A little overlap is still "that way"; more is beside it.
            if (along < -Math.min(from.width, from.height, r.width, r.height) / 4) continue
            along = Math.max(0, along)
            // In line: the two share part of a row (left/right) or a column.
            let overlap = horizontal
                ? Math.min(from.y + from.height, r.y + r.height) - Math.max(from.y, r.y)
                : Math.min(from.x + from.width, r.x + r.width) - Math.max(from.x, r.x)
            if (overlap > 0) {
                // Among a row's worth: from a wide thing (the search box)
                // down onto cards, the one under its start, not its middle.
                let offset = horizontal ? Math.abs((r.y + r.height / 2) - (from.y + from.height / 2))
                           : from.width > r.width * 2 ? Math.abs(r.x - from.x)
                           : Math.abs((r.x + r.width / 2) - (from.x + from.width / 2))
                let score = along * 4 + offset
                if (score < inLineScore) { inLine = item; inLineScore = score }
            } else if (!horizontal) {
                // Nothing straight above/below: the nearest within 45 degrees.
                let across = Math.abs((r.x + r.width / 2) - (from.x + from.width / 2)) - (from.width + r.width) / 2
                if (across > along) continue
                let score = along + across * 2
                if (score < coneScore) { cone = item; coneScore = score }
            }
        }
        return inLine || cone
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
        nav.lastSpot = nav.rectOf(item)
        nav.active = true
        nav.scrollIntoView(item)
    }

    // Scrolls just enough to show the highlight, and glides there: a card
    // row is half the Deck's screen, and the page jumping by that much on
    // every press is impossible to follow.
    function scrollIntoView(item) {
        let didY = false, didX = false
        for (let p = item.parent; p; p = p.parent) {
            if (!(p instanceof Flickable)) continue
            let r = item.mapToItem(p.contentItem, 0, 0)
            let margin = Kirigami.Units.gridUnit
            // Where it's going, not where it is mid-glide.
            let atY = scrollY.running && scrollY.target === p ? scrollY.to : p.contentY
            let atX = scrollX.running && scrollX.target === p ? scrollX.to : p.contentX
            if (p.contentHeight > p.height) {
                let to = atY
                if (r.y < atY + margin) to = Math.max(p.originY, r.y - margin * 3)
                else if (r.y + item.height > atY + p.height - margin)
                    to = Math.min(p.originY + p.contentHeight - p.height, r.y + item.height - p.height + margin * 3)
                if (to !== atY) { didY = nav.glide(scrollY, p, "contentY", to, didY) }
            }
            if (p.contentWidth > p.width) {
                let to = atX
                if (r.x < atX + margin) to = Math.max(p.originX, r.x - margin * 2)
                else if (r.x + item.width > atX + p.width - margin)
                    to = Math.min(p.originX + p.contentWidth - p.width, r.x + item.width - p.width + margin * 2)
                if (to !== atX) { didX = nav.glide(scrollX, p, "contentX", to, didX) }
            }
        }
    }
    // One glide per direction at a time; a second scroll area the same way
    // (rare) just jumps.
    function glide(animation, flickable, property, to, busy) {
        if (busy) { flickable[property] = to; return true }
        if (animation.running && animation.target !== flickable) animation.complete()
        animation.stop()
        animation.target = flickable
        animation.property = property
        animation.to = to
        animation.start()
        return true
    }
    NumberAnimation { id: scrollY; duration: 170; easing.type: Easing.OutCubic }
    NumberAnimation { id: scrollX; duration: 170; easing.type: Easing.OutCubic }

    function press(right) {
        if (!nav.alive(nav.target)) {
            // The card went with a rebuilt list: A presses the one in its place.
            let replacement = nav.standIn(nav.candidates())
            if (!replacement) { nav.move("down"); return }
            nav.target = replacement
        }
        if (!right && (nav.target instanceof T.TextField)) { keyboard.openFor(nav.target); return }
        if (nav.target instanceof T.Slider) return
        let r = nav.rectOf(nav.target)
        nav.lastPointer = Qt.point(r.x + r.width / 2, r.y + r.height / 2)
        windowChrome.click(nav.window, nav.lastPointer.x, nav.lastPointer.y, !!right)
        Qt.callLater(function() {
            // A click that opened or closed something moves the scene; the
            // highlight re-finds its footing on the next move.
            if (!nav.alive(nav.target)) nav.target = null
            // Not in the player: its controls stay up while the pointer is
            // over them, and nothing scrolls there.
            if (!nav.onPlayer) nav.parkPointer()
        })
    }
    // The pointer out of the way once a click is done: left over the card
    // it clicked, whatever scrolled under it next looked hovered (a second
    // highlight) and opened its preview.
    function parkPointer() {
        nav.lastPointer = Qt.point(-20, -20)
        windowChrome.hover(nav.window, -20, -20)
    }

    function back() {
        let s = nav.scope()
        if (keyboard.opened) { keyboard.close(); return }
        if (s !== nav.window.contentItem.parent) {
            // A popup (menu, dialog): Escape closes it, as on a keyboard.
            windowChrome.key(nav.window, Qt.Key_Escape)
            nav.forget()
            return
        }
        nav.forget()
        nav.window.pageStack.goBack()
    }

    function stepSection(delta) {
        let order = [["home", function() { nav.window.goHome() }], ["browse", function() { nav.window.goBrowse() }],
                     ["seasonal", function() { nav.window.goSeasonal() }],
                     ["continue", function() { nav.window.goContinue() }],
                     ["library", function() { nav.window.goTo("library", "LibraryPage.qml") }],
                     ["words", function() { nav.window.goTo("words", "WordsPage.qml") }],
                     ["profile", function() { nav.window.goTo("profile", "ProfilePage.qml") }],
                     ["settings", function() { nav.window.goSettings() }]]
        // Words only exists with Learn Japanese on.
        if (!backend.learnFeatures) order = order.filter((e) => e[0] !== "words")
        let i = order.findIndex((e) => e[0] === nav.window.section)
        i = (Math.max(0, i) + delta + order.length) % order.length
        nav.forget()
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
            if (nav.onPlayer && nav.playerMenu) { nav.playerMenu = false; nav.forget(); return }
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
        case "view": if (nav.onPlayer) { nav.playerMenu = false; nav.forget() } break
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
        function onCurrentItemChanged() { nav.forget(); nav.playerMenu = false }
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
                nav.lastSpot = nav.rectOf(nav.target)
                let r = nav.target.mapToItem(nav.overlay, 0, 0)
                let x1 = r.x - 4, y1 = r.y - 4
                let x2 = r.x + nav.target.width + 4, y2 = r.y + nav.target.height + 4
                // Only the part of it showing: mid-scroll, a card half under
                // the header mustn't have its ring drawn over the header.
                let area = nav.scrollAreaOf(nav.target)
                if (area) {
                    let a = area.mapToItem(nav.overlay, 0, 0)
                    x1 = Math.max(x1, a.x); y1 = Math.max(y1, a.y)
                    x2 = Math.min(x2, a.x + area.width); y2 = Math.min(y2, a.y + area.height)
                }
                focusRing.x = x1
                focusRing.y = y1
                focusRing.width = Math.max(0, x2 - x1)
                focusRing.height = Math.max(0, y2 - y1)
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
