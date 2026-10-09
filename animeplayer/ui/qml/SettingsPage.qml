import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import QtQuick.Dialogs
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page

    // Paints this page in the app's colour scheme -- see AppTheming.qml
    // for why this is per-page rather than set once on the window.
    AppTheming {}

    property var themeAccents: []
    property string currentAccent: ""
    property bool canDownload: false
    property real downloadBytes: 0
    property string downloadFolder: ""
    property string downloadFolderUrl: ""
    property bool defaultFolder: true
    property string pendingFolder: ""
    function refreshFolder() {
        page.downloadFolder = backend.downloadFolder()
        page.downloadFolderUrl = backend.downloadFolderUrl()
        page.defaultFolder = backend.isDefaultDownloadFolder()
    }
    // With episodes already saved, ask whether they come along.
    function chooseFolder(folder) {
        if (page.downloadBytes > 0) {
            page.pendingFolder = folder
            moveDialog.open()
        } else {
            backend.setDownloadFolder(folder, false)
            page.refreshFolder()
        }
    }

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
    FolderDialog {
        id: folderDialog
        title: "Where should episodes be saved?"
        currentFolder: page.downloadFolderUrl
        onAccepted: page.chooseFolder(selectedFolder.toString())
    }
    Kirigami.PromptDialog {
        id: moveDialog
        title: "Move your saved episodes too?"
        subtitle: page.formatSize(page.downloadBytes) + " is saved in the current folder. "
                + "New downloads will go to the new one either way."
        standardButtons: Kirigami.Dialog.NoButton
        customFooterActions: [
            Kirigami.Action {
                text: "Move them"
                icon.name: "go-next-symbolic"
                onTriggered: {
                    backend.setDownloadFolder(page.pendingFolder, true)
                    page.refreshFolder()
                    moveDialog.close()
                }
            },
            Kirigami.Action {
                text: "Leave them where they are"
                icon.name: "dialog-cancel-symbolic"
                onTriggered: {
                    backend.setDownloadFolder(page.pendingFolder, false)
                    page.refreshFolder()
                    moveDialog.close()
                }
            }
        ]
    }
    Connections {
        target: backend
        function onDownloadFolderMoved(message) {
            folderStatus.text = message
            page.refreshDownloadSize()
        }
    }
    title: "Settings"

    property bool loggedIn: false
    property string builtInClientId: ""
    property string viewerName: ""
    property bool remoteRunning: false
    property string remoteUrl: ""
    property string remotePin: ""
    property bool hasJimakuKey: false
    property string dictionaryState: "missing"
    property real dictionaryProgress: 0

    Component.onCompleted: {
        page.builtInClientId = backend.builtInAnilistClientId()
        clientIdField.text = backend.anilistClientId() === page.builtInClientId ? "" : backend.anilistClientId()
        page.loggedIn = backend.isAnilistLoggedIn()
        page.viewerName = backend.anilistViewerName()
        autoSkipToggle.checked = backend.getAutoSkipEnabled()
        skipFinalToggle.checked = backend.getSkipFinalEpisodeEnabled()
        autoNextToggle.checked = backend.getAutoNextEnabled()
        autoFullscreenToggle.checked = backend.getAutoFullscreenEnabled()
        deleteWatchedToggle.checked = backend.getDeleteAfterWatchingEnabled()
        newEpisodeToggle.checked = backend.getNewEpisodeAlertsEnabled()
        updateChecksToggle.checked = backend.getUpdateChecksEnabled()
        discordToggle.checked = backend.getDiscordEnabled()
        previewToggle.checked = backend.getHoverPreviewEnabled()
        dubEnglishToggle.checked = backend.getDubEnglishEnabled()
        page.hasJimakuKey = backend.hasJimakuKey()
        page.dictionaryState = backend.dictionaryState()
        let style = backend.subtitleStyle()
        subScaleSlider.value = style.scale
        subPosSlider.value = style.position
        page.themeAccents = backend.themeAccents()
        page.currentAccent = backend.theme.accentName
        page.canDownload = backend.canDownload()
        page.refreshFolder()
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

    // Grouped into cards, two to a row on a wide window, one on a narrow one
    // (the Steam Deck in portrait, a half-screen window).
    readonly property int columns: page.availableWidth > Kirigami.Units.gridUnit * 52 ? 2 : 1

    GridLayout {
        width: page.availableWidth
        columns: page.columns
        columnSpacing: Kirigami.Units.largeSpacing * 2
        rowSpacing: Kirigami.Units.largeSpacing * 2

        // ---- AniList --------------------------------------------------------
        SettingsCard {
            title: "AniList"
            iconName: "im-user-symbolic"

            Controls.Label {
                text: page.loggedIn ? ("Logged in as " + page.viewerName) : "Not logged in"
                font.bold: true
            }
            RowLayout {
                visible: page.loggedIn
                Controls.Button {
                    // The QQC2 desktop style sets Kirigami.Theme.inherit = false on its
                    // controls, which stops the app's accent reaching them -- measured
                    // live: a page themed red still drew Breeze-blue Sub/Dub buttons.
                    // Turning inheritance back on is what makes one accent value reach
                    // every control in the app. See AppTheming.qml.
                    Kirigami.Theme.inherit: true
                    text: "Refresh lists"
                    icon.name: "view-refresh-symbolic"
                    onClicked: backend.refreshAnilistList()
                }
                Controls.Button {
                    Kirigami.Theme.inherit: true
                    text: "Log out"
                    onClicked: backend.logoutAnilist()
                }
            }
            ColumnLayout {
                visible: !page.loggedIn
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing
                AppButton {
                    text: "1. Log in with AniList"
                    icon.name: "im-user-symbolic"
                    accented: true
                    onClicked: backend.startAnilistLogin()
                }
                Hint { text: "Opens AniList in your browser. Approve, and it shows you a token." }
                RowLayout {
                    Layout.fillWidth: true
                    Controls.TextField {
                        Kirigami.Theme.inherit: true
                        id: tokenField
                        Layout.fillWidth: true
                        placeholderText: "2. Paste the token here"
                        onAccepted: backend.confirmAnilistLogin(tokenField.text)
                        echoMode: TextInput.Password
                    }
                    Controls.Button {
                        Kirigami.Theme.inherit: true
                        text: "Log in"
                        enabled: tokenField.text.trim() !== ""
                        onClicked: backend.confirmAnilistLogin(tokenField.text)
                    }
                }
                // For anyone who'd rather log in through their own AniList
                // API client than the built-in one.
                Controls.CheckBox {
                    id: ownClientToggle
                    Kirigami.Theme.inherit: true
                    text: "Use my own AniList API client"
                    checked: clientIdField.text !== "" && clientIdField.text !== page.builtInClientId
                    onToggled: if (!checked) { clientIdField.text = ""; backend.setAnilistClientId("") }
                }
                Controls.TextField {
                    Kirigami.Theme.inherit: true
                    id: clientIdField
                    visible: ownClientToggle.checked
                    Layout.fillWidth: true
                    placeholderText: "Client ID, e.g. 12345 (redirect URL: https://anilist.co/api/v2/oauth/pin)"
                    onEditingFinished: backend.setAnilistClientId(text)
                }
            }
        }

        // ---- Appearance -----------------------------------------------------
        // The swatches are AniList's own profile colours, and the default is
        // its blue, so the app and the site it syncs with read as the same
        // product. Light/dark follows the desktop -- see AppTheming.qml.
        SettingsCard {
            title: "Appearance"
            iconName: "preferences-desktop-color-symbolic"

            Controls.Label { text: "Accent colour" }
            Flow {
                Layout.fillWidth: true
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
            AppCheckBox {
                text: "Pure black background (for OLED screens)"
                checked: backend.theme.oled
                onToggled: backend.setThemeOled(checked)
            }
            AppCheckBox {
                id: previewToggle
                text: "Show details when the pointer rests on a poster"
                onToggled: {
                    backend.setHoverPreviewEnabled(checked)
                    applicationWindow().previewsOn = checked
                }
            }
        }

        // ---- Playback -------------------------------------------------------
        SettingsCard {
            title: "Playback"
            iconName: "media-playback-start-symbolic"

            AppCheckBox {
                id: autoSkipToggle
                text: "Auto-skip intro/outro"
                onToggled: backend.setAutoSkipEnabled(checked)
            }
            AppCheckBox {
                id: skipFinalToggle
                text: "Also auto-skip on the last episode"
                onToggled: backend.setSkipFinalEpisodeEnabled(checked)
            }
            AppCheckBox {
                id: autoNextToggle
                text: "Auto-play next episode"
                onToggled: backend.setAutoNextEnabled(checked)
            }
            AppCheckBox {
                id: autoFullscreenToggle
                text: "Go fullscreen when an episode starts"
                onToggled: backend.setAutoFullscreenEnabled(checked)
            }
            AppCheckBox {
                id: dubEnglishToggle
                text: "English subtitles on dubs"
                onToggled: backend.setDubEnglishEnabled(checked)
            }
            GridLayout {
                Layout.fillWidth: true
                columns: 3
                columnSpacing: Kirigami.Units.largeSpacing
                Controls.Label { text: "Subtitle size" }
                Controls.Slider {
                    id: subScaleSlider
                    Kirigami.Theme.inherit: true
                    Layout.fillWidth: true
                    from: 0.5; to: 2.0; stepSize: 0.05; value: 1.0
                    onMoved: backend.setSubtitleStyle(value, subPosSlider.value)
                }
                Controls.Label {
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 4
                    text: Math.round(subScaleSlider.value * 100) + "%"
                }
                Controls.Label { text: "Subtitle height" }
                Controls.Slider {
                    id: subPosSlider
                    Kirigami.Theme.inherit: true
                    Layout.fillWidth: true
                    from: 60; to: 100; stepSize: 1; value: 100
                    onMoved: backend.setSubtitleStyle(subScaleSlider.value, value)
                }
                Controls.Label {
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 4
                    text: subPosSlider.value >= 100 ? "bottom" : (100 - subPosSlider.value) + "% up"
                }
            }
        }

        // ---- Downloads ------------------------------------------------------
        SettingsCard {
            title: "Downloads"
            iconName: "download-symbolic"

            Hint {
                text: !page.canDownload
                    ? "ffmpeg isn't installed, so episodes can't be saved for offline watching."
                    : page.downloadBytes > 0
                      ? page.formatSize(page.downloadBytes) + " saved on disk"
                      : "Nothing saved right now."
            }
            AppCheckBox {
                id: deleteWatchedToggle
                enabled: page.canDownload
                text: "Clear saved episodes as I watch (keeps the one before)"
                onToggled: backend.setDeleteAfterWatchingEnabled(checked)
            }
            RowLayout {
                Layout.fillWidth: true
                enabled: page.canDownload
                spacing: Kirigami.Units.smallSpacing
                Controls.Label { text: "Save to" }
                Controls.Label {
                    Layout.fillWidth: true
                    elide: Text.ElideMiddle
                    text: page.downloadFolder
                    opacity: 0.8
                    Controls.ToolTip.visible: folderHover.hovered && truncated
                    Controls.ToolTip.text: page.downloadFolder
                    HoverHandler { id: folderHover }
                }
            }
            Flow {
                Layout.fillWidth: true
                enabled: page.canDownload
                spacing: Kirigami.Units.smallSpacing
                Controls.Button {
                    Kirigami.Theme.inherit: true
                    text: "Change..."
                    icon.name: "document-open-folder-symbolic"
                    onClicked: folderDialog.open()
                }
                Controls.Button {
                    Kirigami.Theme.inherit: true
                    text: "Open"
                    icon.name: "folder-open-symbolic"
                    onClicked: backend.openDownloadFolder()
                }
                Controls.Button {
                    Kirigami.Theme.inherit: true
                    visible: !page.defaultFolder
                    text: "Default"
                    onClicked: page.chooseFolder("")
                }
                Controls.Button {
                    Kirigami.Theme.inherit: true
                    text: "Delete all downloads"
                    enabled: page.downloadBytes > 0
                    icon.name: "edit-delete-symbolic"
                    onClicked: clearDownloadsPrompt.open()
                }
            }
            Hint {
                id: folderStatus
                visible: text !== ""
            }
        }

        // ---- Notifications & Discord ---------------------------------------
        SettingsCard {
            title: "Notifications & Discord"
            iconName: "notifications-symbolic"

            AppCheckBox {
                id: newEpisodeToggle
                text: "Tell me when a show I'm watching gets a new episode"
                onToggled: backend.setNewEpisodeAlertsEnabled(checked)
            }
            Hint {
                text: "Checked every half hour while the app is open, for everything in "
                    + "Continue Watching. Uses AniList's airing schedule, which is for the sub."
            }
            AppCheckBox {
                id: discordToggle
                visible: backend.discordAvailable()
                text: "Show what I'm watching on my Discord profile"
                onToggled: backend.setDiscordEnabled(checked)
            }
            Hint {
                visible: backend.discordAvailable()
                text: "Title, episode and time left, while an episode plays and Discord is open on this PC."
            }
        }

        // ---- Phone remote ---------------------------------------------------
        SettingsCard {
            title: "Phone remote"
            iconName: "phone-symbolic"

            RowLayout {
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
            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.largeSpacing * 2
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop
                    spacing: Kirigami.Units.smallSpacing
                    visible: page.remoteRunning
                    Hint { text: "On your phone (same Wi-Fi), open:" }
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
                    Hint {
                        text: "Scan the code with your phone's camera to install the Android remote app, "
                            + "then enter the address and PIN."
                    }
                }
                Image {
                    id: qrImage
                    Layout.alignment: Qt.AlignTop
                    sourceSize.width: 160
                    sourceSize.height: 160
                    smooth: false // keep QR modules crisp, no blur filtering
                }
            }
        }

        // ---- Learn Japanese -------------------------------------------------
        // Off unless switched on (see backend.learnFeatures): the player's あ
        // button, the Words page and what's below only exist with it on.
        SettingsCard {
            title: "Learn Japanese"
            iconName: "education-language-symbolic"

            AppCheckBox {
                text: "Learn Japanese while watching"
                checked: backend.learnFeatures
                onToggled: backend.setLearnFeatures(checked)
            }
            Hint {
                visible: !backend.learnFeatures
                text: "Japanese subtitles you can hover for meanings, furigana and romaji, "
                    + "saved words and Anki export. Adds a \u3042 button to the player and a Words page."
            }
            // Japanese subtitles come from Jimaku, which needs a free
            // account's API key; the dictionary is JMdict, downloaded once.
            ColumnLayout {
                visible: backend.learnFeatures
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing
                RowLayout {
                    Layout.fillWidth: true
                    Controls.TextField {
                        id: jimakuField
                        Kirigami.Theme.inherit: true
                        Layout.fillWidth: true
                        echoMode: TextInput.Password
                        placeholderText: page.hasJimakuKey ? "Jimaku key saved \u2014 paste a new one to replace it"
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
                Hint {
                    textFormat: Text.StyledText
                    onLinkActivated: (link) => Qt.openUrlExternally(link)
                    text: (page.hasJimakuKey ? "Key saved. " : "")
                        + "Japanese subtitles come from <a href=\"https://jimaku.cc\">jimaku.cc</a>: "
                        + "make a free account, then generate a key on its <a href=\"https://jimaku.cc/account\">account page</a>."
                    HoverHandler { cursorShape: parent.hoveredLink ? Qt.PointingHandCursor : Qt.ArrowCursor }
                }
                RowLayout {
                    Controls.Label {
                        text: "Dictionary: " + (page.dictionaryState === "ready" ? "ready (works offline)"
                            : page.dictionaryState === "building"
                              ? (page.dictionaryProgress >= 1 ? "building\u2026"
                                 : "downloading " + Math.round(page.dictionaryProgress * 100) + "%")
                              : "not set up yet (10 MB, one-time)")
                    }
                    Controls.Button {
                        Kirigami.Theme.inherit: true
                        visible: page.dictionaryState === "missing"
                        text: "Set up now"
                        onClicked: { page.dictionaryState = "building"; backend.prepareDictionary() }
                    }
                }
                Hint { text: "JMdict, from the Electronic Dictionary Research and Development Group (CC BY-SA 4.0)." }
            }
        }

        // ---- About & updates ------------------------------------------------
        SettingsCard {
            title: "About & updates"
            iconName: "help-about-symbolic"

            RowLayout {
                spacing: Kirigami.Units.largeSpacing
                Controls.Label { text: "Version " + backend.appVersion() }
                Controls.Button {
                    Kirigami.Theme.inherit: true
                    text: "Check now"
                    icon.name: "view-refresh-symbolic"
                    onClicked: {
                        updateStatusLabel.text = "Checking..."
                        backend.checkForUpdates(true)
                    }
                }
            }
            AppCheckBox {
                id: updateChecksToggle
                text: "Tell me when a new version is out"
                onToggled: backend.setUpdateChecksEnabled(checked)
            }
            Hint {
                id: updateStatusLabel
                visible: text !== ""
                Connections {
                    target: backend
                    function onUpdateStatus(message) { updateStatusLabel.text = message }
                    function onUpdateAvailable(version) {
                        updateStatusLabel.text = "Version " + version + " is available."
                    }
                }
            }
            Kirigami.Separator { Layout.fillWidth: true }
            RowLayout {
                spacing: Kirigami.Units.smallSpacing
                Controls.Button {
                    Kirigami.Theme.inherit: true
                    text: "Report a problem"
                    icon.name: "tools-report-bug-symbolic"
                    onClicked: Qt.openUrlExternally(backend.problemReportUrl(""))
                }
                Controls.Button {
                    Kirigami.Theme.inherit: true
                    text: "Copy details"
                    icon.name: "edit-copy-symbolic"
                    onClicked: applicationWindow().copyText(backend.problemReport())
                }
            }
            Hint {
                text: "Opens a GitHub issue with your app version and recent errors filled in "
                    + "(needs a GitHub account). No account? Copy the details and send them to the developer."
            }
        }
    }

    // One group of settings: an icon and a heading over its controls.
    component SettingsCard: Rectangle {
        id: card
        property string title: ""
        property string iconName: ""
        default property alias content: cardBody.data
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        Layout.alignment: Qt.AlignTop
        implicitHeight: cardColumn.implicitHeight + Kirigami.Units.largeSpacing * 3
        radius: Kirigami.Units.smallSpacing * 2
        color: Kirigami.Theme.alternateBackgroundColor

        ColumnLayout {
            id: cardColumn
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Kirigami.Units.largeSpacing * 1.5
            spacing: Kirigami.Units.largeSpacing
            RowLayout {
                spacing: Kirigami.Units.smallSpacing
                Kirigami.Icon {
                    source: card.iconName
                    implicitWidth: Kirigami.Units.iconSizes.smallMedium
                    implicitHeight: Kirigami.Units.iconSizes.smallMedium
                    color: Kirigami.Theme.highlightColor
                    isMask: true
                }
                Kirigami.Heading {
                    level: 3
                    text: card.title
                }
            }
            ColumnLayout {
                id: cardBody
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing
            }
        }
    }

    // The grey small print under a setting.
    component Hint: Controls.Label {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        opacity: 0.7
        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
    }
}
