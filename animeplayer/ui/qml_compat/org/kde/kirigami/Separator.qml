// Kirigami.Separator: a hairline in the text colour faded into the background.
import QtQuick
import org.kde.kirigami as K

Rectangle {
    implicitWidth: 1
    implicitHeight: 1
    color: Qt.tint(K.Theme.textColor, Qt.rgba(K.Theme.backgroundColor.r, K.Theme.backgroundColor.g,
                                              K.Theme.backgroundColor.b, 0.8))
}
