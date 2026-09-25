// Kirigami.Icon: an icon by theme name (from the bundled Breeze subset) or
// by URL. Symbolic icons and masks are tinted, as Kirigami does.
import QtQuick
import QtQuick.Controls.impl as QQC2Impl
import org.kde.kirigami as K

Item {
    id: icon
    property var source
    property color color: "transparent"
    property bool isMask: false
    property bool active: false
    property bool selected: false
    property string fallback: ""
    property string placeholder: ""
    property bool roundToIconSize: true
    property bool animated: false
    readonly property bool valid: image.status === Image.Ready

    implicitWidth: K.Units.iconSizes.smallMedium
    implicitHeight: K.Units.iconSizes.smallMedium

    readonly property string sourceText: icon.source === undefined || icon.source === null ? "" : String(icon.source)
    readonly property bool isUrl: sourceText.indexOf("/") >= 0 || sourceText.indexOf(":") >= 0
    readonly property bool tinted: icon.isMask || (!icon.isUrl && icon.sourceText.endsWith("-symbolic"))

    QQC2Impl.IconImage {
        id: image
        anchors.fill: parent
        name: icon.isUrl ? "" : icon.sourceText
        source: icon.isUrl ? icon.sourceText : ""
        sourceSize.width: Math.max(1, Math.round(width))
        sourceSize.height: Math.max(1, Math.round(height))
        fillMode: Image.PreserveAspectFit
        color: icon.tinted
               ? (icon.color.a > 0 ? icon.color : K.Theme.textColor)
               : (icon.color.a > 0 ? icon.color : "transparent")
    }
}
