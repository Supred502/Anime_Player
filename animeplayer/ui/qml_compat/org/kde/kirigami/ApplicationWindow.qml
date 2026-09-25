// Kirigami.ApplicationWindow: a Controls window with a page stack, and the
// two functions Kirigami makes available to every page -- applicationWindow()
// and showPassiveNotification().
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as K

QQC2.ApplicationWindow {
    id: root

    property alias pageStack: row
    property var globalDrawer: null
    property var contextDrawer: null
    readonly property bool wideScreen: width >= K.Units.gridUnit * 40

    // Shown as soon as it exists, as Kirigami's window is.
    visible: true
    color: K.Theme.backgroundColor

    function applicationWindow() { return root }


    function showPassiveNotification(message, timeout, actionText, callBack) {
        toast.text = message
        let ms = typeof timeout === "number" ? timeout : (timeout === "long" ? 4500 : 2500)
        toastTimer.interval = ms
        toast.opacity = 1
        toastTimer.restart()
    }
    function hidePassiveNotification() { toast.opacity = 0 }

    K.PageRow {
        id: row
        anchors.fill: parent
    }

    // Passive notifications: a pill near the bottom, over everything.
    QQC2.Label {
        id: toast
        parent: QQC2.Overlay.overlay
        z: 1000
        anchors.horizontalCenter: parent ? parent.horizontalCenter : undefined
        anchors.bottom: parent ? parent.bottom : undefined
        anchors.bottomMargin: K.Units.gridUnit * 2
        width: Math.min(implicitWidth, (parent ? parent.width : 600) - K.Units.gridUnit * 4)
        opacity: 0
        visible: opacity > 0
        wrapMode: Text.WordWrap
        padding: K.Units.largeSpacing
        leftPadding: K.Units.gridUnit
        rightPadding: K.Units.gridUnit
        color: K.Theme.textColor
        background: Rectangle {
            radius: height / 2
            color: K.Theme.alternateBackgroundColor
            border.color: K.Theme.disabledTextColor
            border.width: 1
            opacity: 0.97
        }
        Behavior on opacity { NumberAnimation { duration: K.Units.longDuration } }
        Timer { id: toastTimer; onTriggered: toast.opacity = 0 }
    }
}
