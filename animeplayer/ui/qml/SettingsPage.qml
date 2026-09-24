import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page

    // Paints this page in the app's colour scheme -- see AppTheming.qml
    // for why this is per-page rather than set once on the window.
    AppTheming {}
    title: "Settings"

    property bool loggedIn: false
    property string viewerName: ""
    property bool remoteRunning: false
    property string remoteUrl: ""
    property string remotePin: ""

    Component.onCompleted: {
        clientIdField.text = backend.anilistClientId()
        page.loggedIn = backend.isAnilistLoggedIn()
        page.viewerName = backend.anilistViewerName()
        autoSkipToggle.checked = backend.getAutoSkipEnabled()
        skipFinalToggle.checked = backend.getSkipFinalEpisodeEnabled()
        autoNextToggle.checked = backend.getAutoNextEnabled()
        autoFullscreenToggle.checked = backend.getAutoFullscreenEnabled()
        page.remoteRunning = backend.isRemoteServerRunning()
        page.remoteUrl = backend.getRemoteUrl()
        page.remotePin = backend.getRemotePin()
        qrImage.source = backend.getRemoteApkQrPath()
    }

    Connections {
        target: backend
        function onAnilistLoggedIn(name) {
            page.loggedIn = true
            page.viewerName = name
            tokenField.text = ""
            showPassiveNotification("Logged in to AniList as " + name)
        }
        function onAnilistLoggedOut() {
            page.loggedIn = false
            page.viewerName = ""
        }
        function onAnilistError(message) {
            showPassiveNotification("AniList: " + message)
        }
        function onAnilistListRefreshed() {
            showPassiveNotification("AniList list refreshed")
        }
    }

    ColumnLayout {
        width: page.width
        spacing: Kirigami.Units.largeSpacing

        Kirigami.FormLayout {
            Layout.fillWidth: true

            Controls.Label {
                Kirigami.FormData.label: "AniList:"
                text: page.loggedIn ? ("Logged in as " + page.viewerName) : "Not logged in"
                font.bold: true
            }

            RowLayout {
                Kirigami.FormData.label: " "
                visible: page.loggedIn
                Controls.Button {
                    // The QQC2 desktop style sets Kirigami.Theme.inherit = false on its
                    // controls, which stops the app's accent reaching them -- measured
                    // live: a page themed red still drew Breeze-blue Sub/Dub buttons.
                    // Turning inheritance back on is what makes one accent value reach
                    // every control in the app. See AppTheming.qml.
                    Kirigami.Theme.inherit: true
                    text: "Refresh lists"
                    onClicked: backend.refreshAnilistList()
                }
                Controls.Button {
                    Kirigami.Theme.inherit: true
                    text: "Log out"
                    onClicked: backend.logoutAnilist()
                }
            }
        }

        Kirigami.Separator { Layout.fillWidth: true }

        // Appearance. The swatches are AniList's own profile colours, and the
        // default is its blue, so the app and the site it syncs with read as
        // the same product. Light/dark follows the desktop -- see
        // AppTheming.qml for why this app does not override that itself.
        Kirigami.FormLayout {
            Layout.fillWidth: true

            RowLayout {
                Kirigami.FormData.label: "Accent:"
                spacing: Kirigami.Units.smallSpacing
                Repeater {
                    model: backend.themeAccents()
                    Rectangle {
                        required property var modelData
                        readonly property bool current: backend.theme.accentName === modelData.key
                        implicitWidth: Kirigami.Units.gridUnit * 1.6
                        implicitHeight: implicitWidth
                        radius: width / 2
                        color: modelData.color
                        // The selected swatch gets a ring in the page's own
                        // text colour rather than a tick: a checkmark has to
                        // be readable against eight different fills.
                        border.width: current ? 3 : 0
                        border.color: Kirigami.Theme.textColor
                        scale: swatchHover.hovered ? 1.15 : 1
                        Behavior on scale { NumberAnimation { duration: 100 } }

                        HoverHandler { id: swatchHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: backend.setThemeAccent(modelData.key) }
                    }
                }
            }
        }

        Kirigami.Separator { Layout.fillWidth: true }

        Kirigami.FormLayout {
            Layout.fillWidth: true

            Controls.CheckBox {
                Kirigami.Theme.inherit: true
                id: autoSkipToggle
                Kirigami.FormData.label: "Playback:"
                text: "Auto-skip intro/outro"
                onToggled: backend.setAutoSkipEnabled(checked)
            }
            Controls.CheckBox {
                Kirigami.Theme.inherit: true
                id: skipFinalToggle
                Kirigami.FormData.label: " "
                text: "Also auto-skip on the last episode"
                onToggled: backend.setSkipFinalEpisodeEnabled(checked)
            }
            Controls.CheckBox {
                Kirigami.Theme.inherit: true
                id: autoNextToggle
                Kirigami.FormData.label: " "
                text: "Auto-play next episode"
                onToggled: backend.setAutoNextEnabled(checked)
            }
            Controls.CheckBox {
                Kirigami.Theme.inherit: true
                id: autoFullscreenToggle
                Kirigami.FormData.label: " "
                text: "Go fullscreen when an episode starts"
                onToggled: backend.setAutoFullscreenEnabled(checked)
            }
        }

        Kirigami.Separator { Layout.fillWidth: true }

        Kirigami.FormLayout {
            Layout.fillWidth: true

            RowLayout {
                Kirigami.FormData.label: "Phone remote:"
                Controls.Button {
                    Kirigami.Theme.inherit: true
                    text: page.remoteRunning ? "Stop" : "Start"
                    onClicked: {
                        if (page.remoteRunning) backend.stopRemoteServer()
                        else backend.startRemoteServer()
                        page.remoteRunning = backend.isRemoteServerRunning()
                        page.remoteUrl = backend.getRemoteUrl()
                        page.remotePin = backend.getRemotePin()
                        // The QR's target URL depends on whether the server is
                        // running (LAN download vs GitHub fallback) -- getRemoteApkQrPath()
                        // has no NOTIFY signal, so re-point the Image explicitly
                        // instead of relying on a binding to pick up the change.
                        qrImage.source = ""
                        qrImage.source = backend.getRemoteApkQrPath()
                    }
                }
                Controls.Label {
                    text: page.remoteRunning ? "Running" : "Not running"
                    opacity: 0.7
                }
            }

            ColumnLayout {
                Kirigami.FormData.label: " "
                visible: page.remoteRunning
                spacing: Kirigami.Units.smallSpacing

                Controls.Label {
                    text: "On your phone (same Wi-Fi), open:"
                    opacity: 0.7
                }
                Controls.Label {
                    text: page.remoteUrl
                    font.bold: true
                    font.family: "monospace"
                }
                Controls.Label {
                    text: "PIN: " + page.remotePin
                    font.bold: true
                    font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.4
                }
            }

            ColumnLayout {
                Kirigami.FormData.label: "Remote app:"
                spacing: Kirigami.Units.smallSpacing

                Controls.Label {
                    Layout.fillWidth: true
                    Layout.maximumWidth: page.width - Kirigami.Units.largeSpacing * 2
                    wrapMode: Text.WordWrap
                    opacity: 0.7
                    text: "Scan with your phone's camera to install the Android remote app, then open it and enter the address and PIN above."
                }
                Image {
                    id: qrImage
                    sourceSize.width: 220
                    sourceSize.height: 220
                    smooth: false // keep QR modules crisp, no blur filtering
                }
            }
        }

        Kirigami.Separator { Layout.fillWidth: true; visible: !page.loggedIn }

        ColumnLayout {
            visible: !page.loggedIn
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            Controls.Label {
                Layout.fillWidth: true
                Layout.maximumWidth: page.width - Kirigami.Units.largeSpacing * 2
                wrapMode: Text.WordWrap
                text: "To sync your AniList account:\n" +
                      "1. Go to anilist.co/settings/developer and create an API client.\n" +
                      "2. Set its Redirect URL to exactly: https://anilist.co/api/v2/oauth/pin\n" +
                      "3. Paste the Client ID below, then click \"Open AniList Login\".\n" +
                      "4. Approve access in the browser, copy the token AniList shows you, and paste it below."
            }

            Kirigami.FormLayout {
                Layout.fillWidth: true

                Controls.TextField {
                    Kirigami.Theme.inherit: true
                    id: clientIdField
                    Kirigami.FormData.label: "Client ID:"
                    placeholderText: "e.g. 12345"
                    onEditingFinished: backend.setAnilistClientId(text)
                }

                Controls.Button {
                    Kirigami.Theme.inherit: true
                    Kirigami.FormData.label: " "
                    text: "Open AniList Login"
                    onClicked: {
                        backend.setAnilistClientId(clientIdField.text)
                        backend.startAnilistLogin()
                    }
                }

                Controls.TextField {
                    Kirigami.Theme.inherit: true
                    id: tokenField
                    Kirigami.FormData.label: "Access token:"
                    placeholderText: "Paste token here"
                    echoMode: TextInput.Password
                }

                Controls.Button {
                    Kirigami.Theme.inherit: true
                    Kirigami.FormData.label: " "
                    text: "Confirm Login"
                    onClicked: backend.confirmAnilistLogin(tokenField.text)
                }
            }
        }
    }
}
