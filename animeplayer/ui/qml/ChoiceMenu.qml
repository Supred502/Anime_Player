// A menu for picking one of a few things -- playback speed, quality. The
// current one has a tick and is in bold; stock checkable items drew a box
// beside every entry, which read as "pick several".
import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Controls.Menu {
    id: menu
    Kirigami.Theme.inherit: true
    property var options: []      // [{ label, value }]
    property var current
    signal chosen(var value)

    // Above or below a button, lined up with its edge, rather than wherever
    // the pointer happened to be.
    // Bound rather than set once: the menu's size is only known after its
    // items are built, and a first opening measured nothing and overlapped
    // the button.
    function openAbove(item) {
        parent = item
        x = Qt.binding(() => item.width - menu.width)
        y = Qt.binding(() => -menu.height - Kirigami.Units.smallSpacing)
        open()
    }
    function openBelow(item) {
        parent = item
        x = Qt.binding(() => item.width - menu.width)
        y = Qt.binding(() => item.height + Kirigami.Units.smallSpacing)
        open()
    }

    Instantiator {
        model: menu.options
        onObjectAdded: (index, object) => menu.insertItem(index, object)
        onObjectRemoved: (index, object) => menu.removeItem(object)
        delegate: Controls.MenuItem {
            required property var modelData
            readonly property bool selected: !!menu && modelData.value === menu.current
            id: choice
            text: modelData.label
            // Drawn here: the styles colour a menu icon themselves, so a tick
            // can't be hidden on the rows that aren't picked. Every row keeps
            // the tick's room, so the labels line up.
            contentItem: Row {
                spacing: Kirigami.Units.smallSpacing
                Kirigami.Icon {
                    anchors.verticalCenter: parent.verticalCenter
                    width: Kirigami.Units.iconSizes.small
                    height: width
                    source: "checkmark-symbolic"
                    isMask: true
                    color: Kirigami.Theme.textColor
                    opacity: choice.selected ? 1 : 0
                }
                Controls.Label {
                    anchors.verticalCenter: parent.verticalCenter
                    text: choice.text
                    font.bold: choice.selected
                }
            }
            onTriggered: menu.chosen(modelData.value)
        }
    }
}
