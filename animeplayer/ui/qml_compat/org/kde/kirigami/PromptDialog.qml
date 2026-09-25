// Kirigami.PromptDialog: a title, a line of text and a row of actions.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as K

QQC2.Dialog {
    id: dialog
    property string subtitle: ""
    property list<QtObject> customFooterActions

    parent: QQC2.Overlay.overlay
    anchors.centerIn: parent
    modal: true
    width: Math.min(parent ? parent.width - K.Units.gridUnit * 2 : 400, K.Units.gridUnit * 24)
    padding: K.Units.gridUnit

    contentItem: QQC2.Label {
        text: dialog.subtitle
        wrapMode: Text.WordWrap
    }

    footer: RowLayout {
        spacing: K.Units.smallSpacing
        Item { Layout.fillWidth: true }
        Repeater {
            model: dialog.customFooterActions
            QQC2.Button {
                required property var modelData
                action: modelData
                Layout.bottomMargin: K.Units.largeSpacing
            }
        }
        Item { Layout.preferredWidth: K.Units.largeSpacing }
    }
}
