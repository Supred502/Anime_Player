// Kirigami.Heading: sizes as Kirigami computes them, from the default font.
import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as K

QQC2.Label {
    id: heading
    enum Type { Normal, Primary, Secondary }
    property int level: 1
    property int type: Heading.Type.Normal

    font.pointSize: {
        let factor = [1, 1.35, 1.20, 1.15, 1.10][heading.level] || 1
        return K.Theme.defaultFont.pointSize * factor
    }
    font.weight: heading.type === Heading.Type.Primary ? Font.DemiBold : Font.Normal
    opacity: heading.type === Heading.Type.Secondary ? 0.75 : 1
    color: K.Theme.textColor
}
