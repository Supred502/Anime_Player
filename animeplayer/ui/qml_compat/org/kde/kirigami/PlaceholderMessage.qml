// Kirigami.PlaceholderMessage: icon, heading and explanation, centred.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as K

ColumnLayout {
    id: root
    property string text
    property string explanation
    property QQC2.Action helpfulAction: null
    component IconProperties: QtObject {
        property string name: ""
        property string source: ""
        property int width: Math.round(K.Units.iconSizes.huge * 1.5)
        property int height: Math.round(K.Units.iconSizes.huge * 1.5)
        property color color: K.Theme.textColor
    }
    property IconProperties icon: IconProperties {}
    signal linkActivated(string link)

    spacing: K.Units.largeSpacing

    K.Icon {
        visible: root.icon.name !== "" || root.icon.source !== ""
        opacity: 0.75
        Layout.alignment: Qt.AlignHCenter
        Layout.preferredWidth: root.icon.width
        Layout.preferredHeight: root.icon.height
        color: root.icon.color
        isMask: true
        source: root.icon.source !== "" ? root.icon.source : root.icon.name
    }
    K.Heading {
        text: root.text
        visible: text.length > 0
        type: K.Heading.Primary
        opacity: 0.75
        Layout.fillWidth: true
        horizontalAlignment: Qt.AlignHCenter
        wrapMode: Text.Wrap
    }
    QQC2.Label {
        text: root.explanation
        visible: text.length > 0
        opacity: 0.75
        horizontalAlignment: Qt.AlignHCenter
        wrapMode: Text.Wrap
        Layout.fillWidth: true
        onLinkActivated: (link) => root.linkActivated(link)
    }
    QQC2.Button {
        Layout.alignment: Qt.AlignHCenter
        Layout.topMargin: K.Units.gridUnit
        visible: root.helpfulAction !== null && root.helpfulAction.enabled
        action: root.helpfulAction
    }
}
