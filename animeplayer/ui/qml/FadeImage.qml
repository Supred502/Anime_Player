// An Image that fades in once it has loaded instead of popping in. One the
// cache already has is there at once; the fade is for ones still loading.
import QtQuick
import org.kde.kirigami as Kirigami

Image {
    property real shownOpacity: 1
    asynchronous: true
    opacity: status === Image.Ready ? shownOpacity : 0
    Behavior on opacity { NumberAnimation { duration: Kirigami.Units.longDuration; easing.type: Easing.OutCubic } }
}
