import QtQuick
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root
    title: "real remote test"
    width: 900
    height: 700
    pageStack.initialPage: HomePage {
        Component.onCompleted: {
            backend.startRemoteServer()
        }
    }
}
