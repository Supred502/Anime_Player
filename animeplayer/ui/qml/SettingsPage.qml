import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page

    // Paints this page in the app's colour scheme -- see AppTheming.qml
    // for why this is per-page rather than set once on the window.
    AppTheming {}

    property var themeAccents: []
    property string currentAccent: ""
    property bool canDownload: false
    property int downloadBytes: 0

    function refreshDownloadSize() { page.downloadBytes = backend.downloadBytes() }

    function formatSize(bytes) {
        if (bytes >= 1024 * 1024 * 1024) return (bytes / (1024 * 1024 * 1024)).toFixed(1) + " GB"
        return Math.round(bytes / (1024 * 1024)) + " MB"
    }

    Connections {
        target: backend
        function onDownloadsChanged() { page.refreshDownloadSize() }
        function onDictionaryProgress(fraction) { page.dictionaryState = "building"; page.dictionaryProgress = fraction }
        function onDictionaryReady() { page.dictionaryState = "ready" }
        function onDictionaryFailed(message) { page.dictionaryState = "missing"; showPassiveNotification(message) }
        function onThemeChanged() { page.currentAccent = backend.theme.accentName }
    }

    // Deleting every saved episode is not undoable and not obviously
    // reversible from the button's label alone, so it asks first.
    Kirigami.PromptDialog {
        id: clearDownloadsPrompt
        title: "Delete all downloads?"
        subtitle: "Every episode saved for offline watching will be removed from "
                + "this computer. They can be downloaded again."
        standardButtons: Kirigami.Dialog.NoButton
        customFooterActions: [
            Kirigami.Action {
                text: "Delete them"
                icon.name: "edit-delete-symbolic"
                onTriggered: {
                    let rows = backend.allDownloads()
                    for (let i = 0; i < rows.length; i++) {
                        backend.removeDownload(rows[i].episode_id, rows[i].dub)
                    }
                    clearDownloadsPrompt.close()
                }
            },
            Kirigami.Action {
                text: "Keep them"
                icon.name: "dialog-cancel-symbolic"
                onTriggered: clearDownloadsPrompt.close()
            }
        ]
    }
    title: "Settings"

    property bool loggedIn: false
    property string viewerName: ""
    property bool remoteRunning: false
    property string remoteUrl: ""
    property string remotePin: ""
    property bool hasJimakuKey: false
    property string dictionaryState: "missing"
    property real dictionaryProgress: 0

    Component.onCompleted: {
        clientIdField.text = backend.anilistClientId()
        page.loggedIn = backend.isAnilistLoggedIn()
        page.viewerName = backend.anilistViewerName()
        autoSkipToggle.checked = backend.getAutoSkipEnabled()
        skipFinalToggle.checked = backend.getSkipFinalEpisodeEnabled()
        autoNextToggle.checked = backend.getAutoNextEnabled()
        autoFullscreenToggle.checked = backend.getAutoFullscreenEnabled()
        deleteWatchedToggle.checked = backend.getDeleteAfterWatchingEnabled()
        newEpisodeToggle.checked = backend.getNewEpisodeAlertsEnabled()
        dubEnglishToggle.checked = backend.getDubEnglishEnabled()
        page.hasJimakuKey = backend.hasJimakuKey()
        page.dictionaryState = backend.dictionaryState()
        let style = backend.subtitleStyle()
        subScaleSlider.value = style.scale
        subPosSlider.value = style.position
        page.themeAccents = backend.themeAccents()
        page.currentAccent = backend.theme.accentName
        page.canDownload = backend.canDownload()
        page.refreshDownloadSize()
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
                    // Assigned once, not bound: the swatch list never changes,
                    // and a binding that reads `backend` is re-evaluated during
                    // teardown after the context property is gone.
                    model: page.themeAccents
                    Rectangle {
                        required property var modelData
                        readonly property bool current: page.currentAccent === modelData.key
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

            // Japanese subtitles come from Jimaku, which needs a free
            // account's API key; the dictionary is JMdict, downloaded once.
            RowLayout {
                Kirigami.FormData.label: "Learn Japanese:"
                Controls.TextField {
                    id: jimakuField
                    Kirigami.Theme.inherit: true
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 18
                    echoMode: TextInput.Password
                    placeholderText: page.hasJimakuKey ? "Key saved \u2014 paste a new one to replace it"
                                                       : "Paste your Jimaku API key"
                    onAccepted: saveKeyButton.clicked()
                }
                Controls.Button {
                    id: saveKeyButton
                    Kirigami.Theme.inherit: true
                    text: "Save"
                    enabled: jimakuField.text.trim() !== ""
                    onClicked: {
                        backend.setJimakuKey(jimakuField.text)
                        jimakuField.text = ""
                        page.hasJimakuKey = backend.hasJimakuKey()
                        showPassiveNotification("Jimaku key saved")
                    }
                }
            }
            Controls.Label {
                Kirigami.FormData.label: " "
                Layout.maximumWidth: Kirigami.Units.gridUnit * 28
                wrapMode: Text.WordWrap
                textFormat: Text.StyledText
                onLinkActivated: (link) => Qt.openUrlExternally(link)
                text: (page.hasJimakuKey ? "Key saved. " : "")
                    + "Japanese subtitles come from <a href=\"https://jimaku.cc\">jimaku.cc</a>: "
                    + "make a free account, then generate a key on its <a href=\"https://jimaku.cc/account\">account page</a>."
                opacity: 0.8
                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                HoverHandler { cursorShape: parent.hoveredLink ? Qt.PointingHandCursor : Qt.ArrowCursor }
            }
            RowLayout {
                Kirigami.FormData.label: "Dictionary:"
                Controls.Label {
                    text: page.dictionaryState === "ready" ? "Ready (works offline)"
                        : page.dictionaryState === "building"
                          ? (page.dictionaryProgress >= 1 ? "Building\u2026"
                             : "Downloading " + Math.round(page.dictionaryProgress * 100) + "%")
                          : "Not set up yet (10 MB, one-time)"
                }
                Controls.Button {
                    Kirigami.Theme.inherit: true
                    visible: page.dictionaryState === "missing"
                    text: "Set up now"
                    onClicked: { page.dictionaryState = "building"; backend.prepareDictionary() }
                }
            }
            Controls.Label {
                Kirigami.FormData.label: " "
                text: "JMdict, from the Electronic Dictionary Research and Development Group (CC BY-SA 4.0)."
                opacity: 0.6
                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
            }
        }

        Kirigami.Separator { Layout.fillWidth: true }

        Kirigami.FormLayout {
            Layout.fillWidth: true

            AppCheckBox {
                id: autoSkipToggle
                Kirigami.FormData.label: "Playback:"
                text: "Auto-skip intro/outro"
                onToggled: backend.setAutoSkipEnabled(checked)
            }
            AppCheckBox {
                id: skipFinalToggle
                Kirigami.FormData.label: " "
                text: "Also auto-skip on the last episode"
                onToggled: backend.setSkipFinalEpisodeEnabled(checked)
            }
            AppCheckBox {
                id: autoNextToggle
                Kirigami.FormData.label: " "
                text: "Auto-play next episode"
                onToggled: backend.setAutoNextEnabled(checked)
            }
            AppCheckBox {
                id: autoFullscreenToggle
                Kirigami.FormData.label: " "
                text: "Go fullscreen when an episode starts"
                onToggled: backend.setAutoFullscreenEnabled(checked)
            }

            RowLayout {
                Kirigami.FormData.label: "Subtitle size:"
                Controls.Slider {
                    id: subScaleSlider
                    Kirigami.Theme.inherit: true
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 12
                    from: 0.5; to: 2.0; stepSize: 0.05; value: 1.0
                    onMoved: backend.setSubtitleStyle(value, subPosSlider.value)
                }
                Controls.Label { text: Math.round(subScaleSlider.value * 100) + "%" }
            }
            RowLayout {
                Kirigami.FormData.label: "Subtitle height:"
                Controls.Slider {
                    id: subPosSlider
                    Kirigami.Theme.inherit: true
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 12
                    from: 60; to: 100; stepSize: 1; value: 100
                    onMoved: backend.setSubtitleStyle(subScaleSlider.value, value)
                }
                Controls.Label {
                    text: subPosSlider.value >= 100 ? "bottom" : (100 - subPosSlider.value) + "% up"
                }
            }

            AppCheckBox {
                id: dubEnglishToggle
                Kirigami.FormData.label: " "
                text: "English subtitles on dubs"
                onToggled: backend.setDubEnglishEnabled(checked)
            }

            AppCheckBox {
                id: newEpisodeToggle
                Kirigami.FormData.label: "Alerts:"
                text: "Tell me when a show I'm watching gets a new episode"
                onToggled: backend.setNewEpisodeAlertsEnabled(checked)
            }
            Controls.Label {
                Kirigami.FormData.label: " "
                text: "Checked every half hour while the app is open, for everything in "
                    + "Continue Watching. Uses AniList's airing schedule, which is for the sub."
                wrapMode: Text.WordWrap
                Layout.maximumWidth: Kirigami.Units.gridUnit * 28
                opacity: 0.7
                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
            }

            AppCheckBox {
                id: deleteWatchedToggle
                Kirigami.FormData.label: "Downloads:"
                enabled: page.canDownload
                text: "Clear saved episodes as I watch (keeps the one before)"
                onToggled: backend.setDeleteAfterWatchingEnabled(checked)
            }
            Controls.Label {
                Kirigami.FormData.label: " "
                text: !page.canDownload
                    ? "ffmpeg isn't installed, so episodes can't be saved for offline watching."
                    : page.downloadBytes > 0
                      ? page.formatSize(page.downloadBytes) + " saved on disk"
                      : "Nothing saved right now."
                opacity: 0.7
                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
            }
            Controls.Button {
                Kirigami.Theme.inherit: true
                Kirigami.FormData.label: " "
                text: "Delete all downloads"
                enabled: page.downloadBytes > 0
                icon.name: "edit-delete-symbolic"
                onClicked: clearDownloadsPrompt.open()
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
