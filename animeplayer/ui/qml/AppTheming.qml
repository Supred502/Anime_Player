// Paints the page it sits in with the app's accent colour.
//
// Where the accent has to be applied is not obvious, and getting it wrong is
// silent -- the colour is set, nothing reports an error, and the app keeps
// drawing Breeze blue. Two things about Kirigami's theme make it so, both
// measured live by walking the item chain and printing inherit/highlightColor
// at every step:
//
//   * Kirigami.Page sets Kirigami.Theme.inherit = false on itself. So a page
//     ignores everything set above it -- on the window, on its content item,
//     on the page stack. The accent has to be set ON THE PAGE, and then it
//     does reach the whole page (its flickable and every child measured red).
//   * The window's header is a child of the window's root item, a sibling of
//     the entire page stack. Nothing set on a page can reach it, so the
//     window paints its own chrome (see AppWindow.qml).
//
// A declared child of a ScrollablePage is reparented into the scrolling
// content, so `parent` here is neither of those things -- which is exactly
// how the accent came to be applied to an inner column and nothing else.
// pageOf() walks up to the real page instead.
//
// Only the accent is set. Backgrounds and text are left to the desktop's own
// colour scheme. That is a deliberate retreat: imposing a full palette was
// tried five ways here and none worked (a page and its scroll view use
// different Kirigami colour sets, so an override lands on one of them and a
// light scheme comes out as dark text on a dark background; replacing the
// page background gets painted over; QPalette and a generated KColorScheme
// pointed at by KDE_COLOR_SCHEME_PATH reached nothing at all). It is also how
// AniList itself splits it: a background scheme, and a profile colour on top.
import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Item {
    id: theming

    // Extra items to paint besides the page this sits in. AppWindow uses
    // this for its own chrome, which no page can reach.
    property var targets: []

    // Guarded and remembered: Qt clears context properties during teardown
    // while bindings are still live, so a bare `backend.theme` re-evaluates
    // against a null backend on quit and hands every colour below undefined.
    property var lastTheme: ({})
    readonly property var appTheme: backend ? backend.theme : theming.lastTheme
    readonly property color accent: appTheme.accent || "#3db4f2"

    onAppThemeChanged: {
        if (backend) theming.lastTheme = appTheme
        theming.apply()
    }
    onTargetsChanged: theming.apply()

    // Zero-sized and invisible: a carrier for the attached property, not
    // something to look at.
    visible: false
    width: 0
    height: 0

    Component.onCompleted: {
        theming.apply()
        // Deferred: ScrollablePage builds its flickable after its children
        // are constructed, so it is still null right here.
        attachHint.restart()
    }

    Timer {
        id: attachHint
        interval: 0
        onTriggered: {
            // The page is only wired into the PageRow a tick after this item
            // is built, and until then it can still report the platform's
            // theme -- so re-apply here as well as at construction.
            theming.apply()
            theming.attachScrollHint()
        }
    }

    ScrollHint { id: scrollHint }

    // The page this lives in, found by walking up. Identified by
    // globalToolBarStyle, which every Kirigami.Page has and nothing between
    // here and it does -- `flickable` would miss PlayerPage, which is a plain
    // Page with no scroll view.
    function pageOf(item) {
        let node = item
        while (node && !node.hasOwnProperty("globalToolBarStyle")) node = node.parent
        return node
    }

    function apply() {
        let page = theming.pageOf(theming)
        if (page) theming.applyTo(page)
        for (let i = 0; i < theming.targets.length; i++) {
            if (theming.targets[i]) theming.applyTo(theming.targets[i])
        }
    }

    function attachScrollHint() {
        let page = theming.pageOf(theming)
        if (!page || !page.hasOwnProperty("flickable") || !page.flickable) return
        scrollHint.parent = page
        scrollHint.flickable = page.flickable
        scrollHint.anchors.right = page.right
        scrollHint.anchors.top = page.top
        scrollHint.anchors.bottom = page.bottom
        scrollHint.anchors.rightMargin = 2
    }

    function applyTo(item) {
        // Deliberately NOT setting Kirigami.Theme.inherit = false here.
        // Doing that makes the theme stop deriving *any* role from the
        // platform, and Kirigami then answers every unset role with the
        // custom colour it does have -- measured live, setting only the
        // accent left textColor reporting the accent too, which rendered the
        // whole app in one colour. (A page arrives with inherit already
        // false, set by Kirigami itself, and that case is fine: textColor
        // still measures as the platform's #fcfcfc afterwards.)
        item.Kirigami.Theme.highlightColor = theming.accent
        item.Kirigami.Theme.focusColor = theming.accent
        item.Kirigami.Theme.hoverColor = Qt.rgba(
            theming.accent.r, theming.accent.g, theming.accent.b, 0.25)
    }
}
