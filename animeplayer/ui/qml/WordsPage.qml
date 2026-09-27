// Japanese you've picked up while watching: every word clicked in the
// Learn Japanese overlay, with the line and moment it came from -- plus the
// kana chart, which is where every beginner starts.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import QtQuick.Dialogs
import QtCore
import org.kde.kirigami as Kirigami

Kirigami.ScrollablePage {
    id: page

    AppTheming {}
    title: "Words"

    property var words: []
    property int tab: 0   // 0 = saved words, 1 = kana

    Component.onCompleted: page.words = backend.savedWords()

    // ---- Anki export -----------------------------------------------------
    property bool exporting: false
    property string exportStatus: ""
    Controls.Dialog {
        id: ankiDialog
        Kirigami.Theme.inherit: true
        parent: Controls.Overlay.overlay
        anchors.centerIn: parent
        modal: true
        width: Math.min(parent ? parent.width - Kirigami.Units.gridUnit * 2 : 500, Kirigami.Units.gridUnit * 26)
        title: "Export to Anki"
        standardButtons: Controls.Dialog.Cancel
        ColumnLayout {
            width: parent.width
            spacing: Kirigami.Units.largeSpacing
            Controls.Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: page.words.length + (page.words.length === 1 ? " word" : " words")
                    + " become flashcards: the word and its line on the front; the reading, meaning "
                    + "and the English on the back. Open the file with Anki on your PC, or AnkiDroid "
                    + "or AnkiMobile on your phone. Exporting again later updates the same cards."
            }
            AppCheckBox {
                id: ankiAudio
                checked: true
                text: "Include the audio of each line"
            }
            Controls.Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                opacity: 0.7
                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                text: "Cut from the episode: quick for episodes saved offline, a few seconds per episode otherwise."
            }
            AppButton {
                Layout.alignment: Qt.AlignRight
                text: "Choose where to save..."
                accented: true
                onClicked: { ankiDialog.close(); ankiFile.open() }
            }
        }
    }
    FileDialog {
        id: ankiFile
        title: "Save Anki deck"
        fileMode: FileDialog.SaveFile
        nameFilters: ["Anki deck (*.apkg)"]
        defaultSuffix: "apkg"
        // A save dialog can't be handed a file that doesn't exist yet, so
        // it opens on Documents; the name typed gets .apkg if it lacks one.
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: {
            page.exporting = true
            page.exportStatus = "Making your deck..."
            backend.exportAnki(selectedFile.toString(), ankiAudio.checked)
        }
    }
    Connections {
        target: backend
        function onAnkiProgress(done, total) { page.exportStatus = "Cutting audio: " + done + " of " + total }
        function onAnkiExported(path, count) {
            page.exporting = false
            page.exportStatus = ""
            showPassiveNotification("Saved " + count + " cards to " + path + " -- open it with Anki", "long")
        }
        function onAnkiFailed(message) {
            page.exporting = false
            page.exportStatus = ""
            showPassiveNotification("Couldn't export: " + message, "long")
        }
    }

    Connections {
        target: backend
        function onSavedWordsChanged() { page.words = backend.savedWords() }
    }

    actions: [
        Kirigami.Action {
            text: "My words"
            icon.name: "bookmarks-symbolic"
            checkable: true
            checked: page.tab === 0
            onTriggered: page.tab = 0
        },
        Kirigami.Action {
            text: "Export to Anki"
            icon.name: "document-export-symbolic"
            enabled: page.words.length > 0 && !page.exporting
            tooltip: "Turn your saved words into flashcards for Anki (PC, AnkiDroid, iPhone)"
            onTriggered: ankiDialog.open()
        },
        Kirigami.Action {
            text: "Kana chart"
            icon.name: "character-set-symbolic"
            checkable: true
            checked: page.tab === 1
            onTriggered: page.tab = 1
        }
    ]

    // Opens the episode a word came from, a couple of seconds before its line.
    function watchMoment(entry) {
        if (!entry.slug_id) return
        let anime = { slug_id: entry.slug_id, numeric_id: entry.slug_id.split("-").pop(),
                      title: entry.title, poster_url: "", kind: "", rating: "" }
        applicationWindow().openAt(anime, entry.episode, Math.max(0, entry.position - 2))
    }

    ColumnLayout {
        width: page.availableWidth
        spacing: Kirigami.Units.largeSpacing

        // ================= Saved words =================
        Kirigami.PlaceholderMessage {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.gridUnit * 3
            visible: page.tab === 0 && page.words.length === 0
            icon.name: "bookmarks-symbolic"
            text: "No saved words yet"
            explanation: "In the player, press あ (or L) to turn on Learn Japanese. "
                       + "Point at a word to see what it means, and click it to save it here."
        }

        Controls.Label {
            visible: page.tab === 0 && page.words.length > 0
            text: page.words.length + (page.words.length === 1 ? " word" : " words")
                  + (page.exportStatus !== "" ? "  ·  " + page.exportStatus : "")
            opacity: 0.7
        }

        Repeater {
            model: page.tab === 0 ? page.words : []

            Rectangle {
                id: wordCard
                required property var modelData
                Layout.fillWidth: true
                implicitHeight: cardRow.implicitHeight + Kirigami.Units.largeSpacing * 2
                radius: Kirigami.Units.smallSpacing * 2
                color: Kirigami.Theme.alternateBackgroundColor

                RowLayout {
                    id: cardRow
                    anchors.fill: parent
                    anchors.margins: Kirigami.Units.largeSpacing
                    spacing: Kirigami.Units.gridUnit

                    ColumnLayout {
                        // Pinned, so the meanings line up down the page.
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 9
                        Layout.minimumWidth: Kirigami.Units.gridUnit * 9
                        Layout.maximumWidth: Kirigami.Units.gridUnit * 9
                        Layout.alignment: Qt.AlignTop
                        spacing: 0
                        Controls.Label {
                            text: wordCard.modelData.reading !== wordCard.modelData.word ? wordCard.modelData.reading : ""
                            visible: text !== ""
                            opacity: 0.75
                        }
                        SelectableText {
                            Layout.fillWidth: true
                            text: wordCard.modelData.word
                            font.pixelSize: Kirigami.Units.gridUnit * 1.8
                        }
                        Controls.Label {
                            text: wordCard.modelData.pos
                            visible: text !== ""
                            opacity: 0.6
                            font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        spacing: Kirigami.Units.smallSpacing
                        SelectableText {
                            Layout.fillWidth: true
                            text: wordCard.modelData.meaning || "(no dictionary entry)"
                            font.bold: true
                        }
                        SelectableText {
                            Layout.fillWidth: true
                            text: wordCard.modelData.sentence
                            opacity: 0.9
                        }
                        SelectableText {
                            Layout.fillWidth: true
                            visible: wordCard.modelData.translation !== ""
                            text: wordCard.modelData.translation
                            opacity: 0.6
                        }
                        Controls.Label {
                            text: wordCard.modelData.title
                                + (wordCard.modelData.episode ? " · episode " + wordCard.modelData.episode : "")
                            opacity: 0.5
                            font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                        }
                    }

                    ColumnLayout {
                        Layout.alignment: Qt.AlignTop
                        AppButton {
                            text: "Watch the line"
                            icon.name: "media-playback-start-symbolic"
                            visible: wordCard.modelData.slug_id !== ""
                            onClicked: page.watchMoment(wordCard.modelData)
                        }
                        Controls.ToolButton {
                            Kirigami.Theme.inherit: true
                            icon.name: "edit-delete-symbolic"
                            text: "Remove"
                            display: Controls.AbstractButton.TextBesideIcon
                            onClicked: backend.removeSavedWord(wordCard.modelData.id)
                        }
                    }
                }
            }
        }

        // ================= Kana =================
        Controls.Label {
            visible: page.tab === 1
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: "Japanese is written with two sets of sound characters (plus kanji). "
                + "Hiragana is used for Japanese words and grammar; katakana for foreign words "
                + "and names. Learning both is the first step -- most people manage it in one "
                + "or two weeks. The furigana above kanji in Learn Japanese is hiragana."
            opacity: 0.8
        }

        Repeater {
            model: page.tab === 1 ? [
                { title: "Hiragana", offset: 0 },
                { title: "Katakana", offset: 0x60 }
            ] : []

            ColumnLayout {
                id: kanaSection
                required property var modelData
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Heading { level: 3; text: kanaSection.modelData.title }

                GridLayout {
                    columns: 5
                    columnSpacing: Kirigami.Units.smallSpacing
                    rowSpacing: Kirigami.Units.smallSpacing
                    Repeater {
                        model: kana.table
                        Rectangle {
                            required property var modelData
                            readonly property int kanaOffset: kanaSection.modelData.offset
                            visible: modelData[0] !== ""
                            Layout.preferredWidth: Kirigami.Units.gridUnit * 4
                            Layout.preferredHeight: Kirigami.Units.gridUnit * 3.6
                            radius: Kirigami.Units.smallSpacing
                            color: Kirigami.Theme.alternateBackgroundColor
                            opacity: modelData[0] === "" ? 0 : 1
                            Column {
                                anchors.centerIn: parent
                                SelectableText {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: implicitWidth
                                    text: kana.shift(modelData[0], kanaOffset)
                                    font.pixelSize: Kirigami.Units.gridUnit * 1.6
                                }
                                Controls.Label {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: modelData[1]
                                    opacity: 0.7
                                }
                            }
                        }
                    }
                }
            }
        }

        QtObject {
            id: kana
            // The gojūon table, a-i-u-e-o across. Empty cells keep the grid
            // aligned where a sound doesn't exist (yi, ye, wu...).
            readonly property var table: [
                ["あ","a"],["い","i"],["う","u"],["え","e"],["お","o"],
                ["か","ka"],["き","ki"],["く","ku"],["け","ke"],["こ","ko"],
                ["さ","sa"],["し","shi"],["す","su"],["せ","se"],["そ","so"],
                ["た","ta"],["ち","chi"],["つ","tsu"],["て","te"],["と","to"],
                ["な","na"],["に","ni"],["ぬ","nu"],["ね","ne"],["の","no"],
                ["は","ha"],["ひ","hi"],["ふ","fu"],["へ","he"],["ほ","ho"],
                ["ま","ma"],["み","mi"],["む","mu"],["め","me"],["も","mo"],
                ["や","ya"],["",""],["ゆ","yu"],["",""],["よ","yo"],
                ["ら","ra"],["り","ri"],["る","ru"],["れ","re"],["ろ","ro"],
                ["わ","wa"],["",""],["",""],["",""],["を","wo (o)"],
                ["ん","n"],["",""],["",""],["",""],["",""]
            ]
            // Katakana sits exactly 0x60 above hiragana in Unicode.
            function shift(text, offset) {
                return text === "" ? "" : String.fromCharCode(text.charCodeAt(0) + offset)
            }
        }
    }
}
