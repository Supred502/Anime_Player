// A round picture of a person: an AniList avatar, or a plain person icon
// until there is one.
import QtQuick
import QtQuick.Effects
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Item {
    id: avatar
    property string source: ""
    property real size: Kirigami.Units.gridUnit * 2
    implicitWidth: size
    implicitHeight: size
    Layout.preferredWidth: size
    Layout.preferredHeight: size

    Image {
        id: picture
        anchors.fill: parent
        source: avatar.source
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        visible: false
        layer.enabled: true
    }
    Rectangle {
        id: circle
        anchors.fill: parent
        radius: width / 2
        visible: false
        layer.enabled: true
    }
    MultiEffect {
        anchors.fill: parent
        source: picture
        maskEnabled: true
        maskSource: circle
        visible: picture.status === Image.Ready
    }
    Kirigami.Icon {
        anchors.fill: parent
        anchors.margins: parent.width * 0.15
        visible: picture.status !== Image.Ready
        source: "im-user-symbolic"
    }
}
