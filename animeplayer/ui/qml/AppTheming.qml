// Paints the page it sits in with the app's accent colour.
//
// Only the accent -- backgrounds and text are left to the desktop's own
// colour scheme. That is a deliberate retreat. Four ways of imposing a full
// palette were tried in this app and measured live; none of them worked:
//
//   * Kirigami.Theme set on the ApplicationWindow: a Window is not an Item,
//     so the attached property propagates to nothing. Pages went on reporting
//     the platform's own #202326 / #3daee9.
//   * The same assigned imperatively to pageStack: same result.
//   * Kirigami.Theme set per page: recolours the labels but *not* the
//     surfaces behind them, because a page and the scroll view inside it use
//     different Kirigami colour sets and an override lands on one of them.
//     The light scheme came out as dark text on a dark background.
//   * Replacing the page's background item: the scroll view paints over it.
//   * QPalette on the QGuiApplication, and a generated KColorScheme file
//     pointed at by KDE_COLOR_SCHEME_PATH: neither reached anything.
//
// The accent roles do apply cleanly, and the accent is the colour that
// actually reads as "this is an AniList app". It is also how AniList itself
// splits things: the site picks a background scheme and a profile colour
// independently.
import QtQuick
import org.kde.kirigami as Kirigami

Item {
    id: theming

    // Guarded and remembered: Qt clears context properties during teardown
    // while bindings are still live, so a bare `backend.theme` re-evaluates
    // against a null backend on quit and hands every colour below undefined.
    property var lastTheme: ({})
    readonly property var appTheme: backend ? backend.theme : theming.lastTheme
    readonly property color accent: appTheme.accent || "#3db4f2"

    onAppThemeChanged: {
        if (backend) theming.lastTheme = appTheme
        if (parent) theming.applyTo(parent)
    }

    // Zero-sized and invisible: a carrier for the attached property, not
    // something to look at.
    visible: false
    width: 0
    height: 0

    Component.onCompleted: if (parent) theming.applyTo(parent)

    function applyTo(item) {
        // inherit must go false first, or an inheriting Theme copies its
        // parent's values straight back over these.
        item.Kirigami.Theme.inherit = false
        item.Kirigami.Theme.highlightColor = theming.accent
        item.Kirigami.Theme.activeTextColor = theming.accent
        item.Kirigami.Theme.linkColor = theming.accent
        item.Kirigami.Theme.visitedLinkColor = theming.accent
        item.Kirigami.Theme.focusColor = theming.accent
        item.Kirigami.Theme.hoverColor = Qt.rgba(
            theming.accent.r, theming.accent.g, theming.accent.b, 0.25)
    }
}
