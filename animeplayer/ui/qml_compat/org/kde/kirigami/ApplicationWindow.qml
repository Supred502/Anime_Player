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

    // Explicit, so every control inherits these rather than whatever the
    // system's palette is (see install() in kirigami_compat.py). Text roles
    // are set per state: a role set without one applies to the disabled
    // state too, and disabled buttons then looked enabled.
    palette.window: K.Theme.backgroundColor
    palette.active.windowText: K.Theme.textColor
    palette.inactive.windowText: K.Theme.textColor
    palette.base: "#141618"
    palette.alternateBase: "#1d1f22"
    palette.active.text: K.Theme.textColor
    palette.inactive.text: K.Theme.textColor
    palette.button: "#292c30"
    palette.active.buttonText: K.Theme.textColor
    palette.inactive.buttonText: K.Theme.textColor
    palette.brightText: "#ffffff"
    palette.highlight: K.Theme.highlightColor
    palette.accent: K.Theme.highlightColor
    palette.highlightedText: K.Theme.highlightedTextColor
    palette.toolTipBase: "#292c30"
    palette.toolTipText: K.Theme.textColor
    palette.placeholderText: K.Theme.disabledTextColor
    palette.link: K.Theme.linkColor
    palette.linkVisited: K.Theme.visitedLinkColor
    palette.light: "#3b4045"
    palette.midlight: "#33373b"
    palette.mid: "#25282b"
    palette.dark: "#141618"
    palette.shadow: "#0a0b0c"
    palette.disabled.windowText: "#6e7175"
    palette.disabled.text: "#6e7175"
    palette.disabled.buttonText: "#6e7175"

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
