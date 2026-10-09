// Text you can select and copy -- titles, synopses, reviews. A Label can't be
// selected at all, which meant finding an anime and then retyping its title
// to search for it anywhere else.
//
// Drag to select, Ctrl+C, or right-click for Copy / Select all. Built on a
// plain TextEdit, not Controls.TextArea: the Breeze style's TextArea brings
// no desktop right-click menu (the stock Qt styles added one in 6.9; Breeze
// hasn't), and its tablet-mode toolbar logs a type warning for every
// instance on a desktop.
//
// What a Label has and this doesn't: elide and maximumLineCount. Set
// `maxLines` instead -- the text is clipped to that many lines until
// `expanded`, and `overflowing` says whether there is more to show.
import QtQuick
import QtQuick.Effects
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

// An Item around the TextEdit rather than the TextEdit itself: a TextEdit's
// implicitHeight is read-only, and clipping to `maxLines` needs to set it.
Item {
    id: root

    property alias text: area.text
    property alias color: area.color
    property alias font: area.font
    property alias horizontalAlignment: area.horizontalAlignment
    readonly property alias selectedText: area.selectedText

    property int maxLines: 0
    property bool expanded: false
    readonly property real lineHeight: fontMetrics.lineSpacing
    readonly property bool overflowing: maxLines > 0 && area.contentHeight > lineHeight * maxLines + 1

    implicitWidth: area.implicitWidth
    implicitHeight: (maxLines > 0 && !expanded)
        ? Math.min(area.contentHeight, Math.ceil(lineHeight * maxLines))
        : area.contentHeight
    clip: maxLines > 0 && !expanded

    // Cut short, the last line fades out: a TextEdit can't end in "…" as a
    // Label does, and a synopsis that just stopped mid-sentence looked broken.
    layer.enabled: overflowing && !expanded
    layer.effect: MultiEffect { maskEnabled: true; maskSource: fade }
    Rectangle {
        id: fade
        anchors.fill: parent
        visible: false
        layer.enabled: true
        gradient: Gradient {
            GradientStop { position: 0; color: "white" }
            GradientStop { position: Math.max(0, 1 - root.lineHeight / Math.max(1, root.height)); color: "white" }
            GradientStop { position: 1; color: "transparent" }
        }
    }

    FontMetrics { id: fontMetrics; font: area.font }

    TextEdit {
        id: area
        width: root.width
        readOnly: true
        selectByMouse: true
        wrapMode: Text.WordWrap
        textFormat: TextEdit.PlainText
        color: Kirigami.Theme.textColor
        selectionColor: Kirigami.Theme.highlightColor
        selectedTextColor: Kirigami.Theme.highlightedTextColor
        font: Kirigami.Theme.defaultFont
        activeFocusOnTab: false

        // An I-beam over text that can be selected.
        HoverHandler { cursorShape: Qt.IBeamCursor }

        TapHandler {
            acceptedButtons: Qt.RightButton
            onTapped: menu.popup()
        }
    }

    Controls.Menu {
        id: menu
        Kirigami.Theme.inherit: true
        Controls.MenuItem {
            text: area.selectedText !== "" ? "Copy" : "Copy all"
            icon.name: "edit-copy-symbolic"
            onTriggered: {
                if (area.selectedText === "") area.selectAll()
                area.copy()
                area.deselect()
            }
        }
        Controls.MenuItem {
            text: "Select all"
            icon.name: "edit-select-all-symbolic"
            onTriggered: area.selectAll()
        }
    }
}
