// The window's page stack (Kirigami's PageRow), always one page wide, with
// Kirigami's global toolbar across the top: back button, the current page's
// title, and its actions.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as K

Item {
    id: row

    property var initialPage
    readonly property int depth: stack.depth
    // Always the last page: this row pops on back instead of scrolling.
    readonly property int currentIndex: stack.depth - 1
    readonly property Item currentItem: stack.currentItem
    readonly property Item lastItem: stack.currentItem
    component ColumnViewSettings: QtObject { property int columnResizeMode: K.ColumnView.SingleColumn }
    property ColumnViewSettings columnView: ColumnViewSettings {}

    function push(page, properties) {
        return stack.push(page, properties || {}, QQC2.StackView.Immediate)
    }
    function pop(page) {
        return page ? stack.pop(page, QQC2.StackView.Immediate) : stack.pop(QQC2.StackView.Immediate)
    }
    function replace(page, properties) {
        return stack.replace(page, properties || {}, QQC2.StackView.Immediate)
    }
    function clear() { stack.clear(QQC2.StackView.Immediate) }
    function get(index) { return stack.get(index, QQC2.StackView.ForceLoad) }
    function goBack() {
        // As Kirigami does: the page hears about it first, and can refuse.
        let event = { accepted: false }
        if (stack.currentItem && stack.currentItem.backRequested) stack.currentItem.backRequested(event)
        if (event.accepted) return true
        if (stack.depth > 1) { stack.pop(QQC2.StackView.Immediate); return true }
        return false
    }

    Component.onCompleted: if (row.initialPage) row.push(row.initialPage)

    readonly property bool toolbarShown: !!stack.currentItem
        && stack.currentItem.globalToolBarStyle !== K.ApplicationHeaderStyle.None

    // Alt+Left and the mouse's back button, as in Kirigami.
    Shortcut { sequences: [StandardKey.Back]; onActivated: row.goBack() }
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.BackButton
        onClicked: row.goBack()
    }

    Rectangle {
        id: toolbar
        anchors.left: parent.left
        anchors.right: parent.right
        visible: row.toolbarShown
        height: visible ? K.Units.gridUnit * 2 + K.Units.smallSpacing * 3 : 0
        color: K.Theme.alternateBackgroundColor

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: stack.depth > 1 ? K.Units.smallSpacing : K.Units.gridUnit
            anchors.rightMargin: K.Units.smallSpacing
            spacing: K.Units.smallSpacing

            QQC2.ToolButton {
                visible: stack.depth > 1
                icon.name: "go-previous-symbolic"
                onClicked: row.goBack()
                QQC2.ToolTip.visible: hovered
                QQC2.ToolTip.text: "Back"
                QQC2.ToolTip.delay: K.Units.toolTipDelay
            }

            K.Heading {
                Layout.fillWidth: true
                level: 1
                text: stack.currentItem ? stack.currentItem.title : ""
                elide: Text.ElideRight
            }

            Repeater {
                model: stack.currentItem ? stack.currentItem.actions : []
                QQC2.ToolButton {
                    id: actionButton
                    required property var modelData
                    action: modelData
                    visible: modelData.visible !== false
                    display: QQC2.AbstractButton.TextBesideIcon
                    hoverEnabled: true
                    QQC2.ToolTip.visible: hovered && (modelData.tooltip || "") !== ""
                    QQC2.ToolTip.text: modelData.tooltip || ""
                    QQC2.ToolTip.delay: K.Units.toolTipDelay
                    background: Rectangle {
                        radius: 3
                        color: actionButton.checked
                            ? Qt.rgba(K.Theme.highlightColor.r, K.Theme.highlightColor.g, K.Theme.highlightColor.b, 0.25)
                            : (actionButton.hovered && actionButton.enabled
                               ? Qt.rgba(K.Theme.highlightColor.r, K.Theme.highlightColor.g, K.Theme.highlightColor.b, 0.12)
                               : "transparent")
                        border.width: actionButton.checked || (actionButton.hovered && actionButton.enabled) ? 1 : 0
                        border.color: K.Theme.highlightColor
                    }
                }
            }
        }

        K.Separator {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
        }
    }

    QQC2.StackView {
        id: stack
        anchors.top: toolbar.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
    }
}
