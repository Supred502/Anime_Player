// "Learn Japanese" on top of the video: the Japanese line split into words,
// with furigana over the kanji and romaji underneath. The English stays where
// mpv draws it, below. Hover a word for its meaning; click it to save it.
//
// Built for someone who can't read Japanese yet:
// - everything is readable without kanji: furigana, and romaji for all of it
// - hovering pauses (optional), so reading a definition doesn't cost the line
// - "pause after each line" gives time to read before the next one starts
// - R replays the line; the timing can be nudged, because subtitles made for
//   another release of the same episode are often a second or two off
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Item {
    id: overlay

    // The MpvVideoItem.
    property var video: null
    property var cues: []
    property string status: ""          // loading / error text; "" when showing lines
    property bool showRomaji: true
    property bool showFurigana: true
    property bool pauseEachLine: false
    property bool pauseOnHover: true
    property real offset: 0             // seconds added to the video time before matching lines

    property int cueIndex: -1
    readonly property var cue: cueIndex >= 0 && cueIndex < cues.length ? cues[cueIndex] : null
    // The last line "pause after each line" stopped on, so resuming doesn't
    // immediately pause again on the same line.
    property int pausedAfter: -1
    property bool pausedByHover: false

    signal wordSaved(string word)

    onCuesChanged: { cueIndex = -1; pausedAfter = -1 }

    // Called on every position tick. Checks the current and next line first
    // -- nearly always one of them -- before searching.
    function update(position) {
        if (!cues.length) return
        let t = position + offset
        let current = cueIndex >= 0 ? cues[cueIndex] : null
        if (overlay.pauseEachLine && current && overlay.pausedAfter !== cueIndex
                && t >= current.end - 0.05 && t < current.end + 1.0) {
            overlay.pausedAfter = cueIndex
            video.setPaused(true)
            return
        }
        if (current && t >= current.start && t < current.end) return
        let next = cueIndex + 1
        if (next < cues.length && t >= cues[next].start && t < cues[next].end) { cueIndex = next; return }
        let lo = 0, hi = cues.length - 1, found = -1
        while (lo <= hi) {
            let mid = (lo + hi) >> 1
            if (cues[mid].end <= t) lo = mid + 1
            else if (cues[mid].start > t) hi = mid - 1
            else { found = mid; break }
        }
        // Between lines, keep the last one up rather than flashing empty:
        // a beginner is often still reading it.
        if (found >= 0) cueIndex = found
        else if (cueIndex >= 0 && t > (cues[cueIndex].end + 4)) cueIndex = -1
    }

    function replayLine() {
        if (!overlay.cue) return
        overlay.pausedAfter = -1
        video.seekAbsolute(Math.max(0, overlay.cue.start - overlay.offset - 0.2))
        video.setPaused(false)
    }

    // Shows the definition card for a word in the current line, as if it
    // were pointed at. Used by the live test driver.
    function lookupAt(index) {
        let item = wordRepeater.itemAt(index)
        if (item && overlay.cue) definition.show(item, overlay.cue.tokens[index])
    }

    // Saves a word of the current line, as a click on it would. Also used
    // by the live test driver.
    function saveAt(index) {
        if (overlay.cue) definition.save(overlay.cue.tokens[index])
    }

    function previousLine() {
        if (overlay.cueIndex > 0) {
            overlay.cueIndex -= 1
            overlay.replayLine()
        }
    }

    // -- The line --------------------------------------------------------------
    Rectangle {
        id: panel
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        // Above mpv's English subtitles and the control bar.
        anchors.bottomMargin: parent.height * 0.2
        width: Math.min(parent.width - Kirigami.Units.gridUnit * 4,
                        lineColumn.implicitWidth + Kirigami.Units.gridUnit * 2)
        height: lineColumn.implicitHeight + Kirigami.Units.largeSpacing * 2
        radius: Kirigami.Units.smallSpacing * 2
        color: Qt.rgba(0, 0, 0, 0.62)
        visible: overlay.cue !== null || overlay.status !== ""

        HoverHandler {
            id: panelHover
            onHoveredChanged: {
                if (!overlay.pauseOnHover || !overlay.video) return
                if (hovered && !overlay.video.paused) {
                    overlay.pausedByHover = true
                    overlay.video.setPaused(true)
                } else if (!hovered && overlay.pausedByHover) {
                    overlay.pausedByHover = false
                    overlay.video.setPaused(false)
                }
            }
        }

        ColumnLayout {
            id: lineColumn
            anchors.centerIn: parent
            width: Math.min(implicitWidth, overlay.width - Kirigami.Units.gridUnit * 6)
            spacing: Kirigami.Units.smallSpacing

            Controls.Label {
                Layout.alignment: Qt.AlignHCenter
                visible: overlay.status !== ""
                text: overlay.status
                color: "white"
                wrapMode: Text.WordWrap
                Layout.maximumWidth: overlay.width * 0.7
                horizontalAlignment: Text.AlignHCenter
            }

            // Who's speaking, when the subtitle says -- small, above the line.
            Controls.Label {
                Layout.alignment: Qt.AlignHCenter
                visible: overlay.status === "" && overlay.cue !== null && (overlay.cue.speaker || "") !== ""
                text: overlay.cue ? overlay.cue.speaker || "" : ""
                color: "#9fd0ff"
                font.pixelSize: Math.max(12, Math.round(overlay.height * 0.018))
            }

            Flow {
                id: words
                // A sound description ("(groaning)") rather than speech:
                // still readable, but visibly not dialogue.
                opacity: overlay.cue && overlay.cue.caption ? 0.6 : 1
                Layout.alignment: Qt.AlignHCenter
                Layout.maximumWidth: overlay.width - Kirigami.Units.gridUnit * 6
                Layout.preferredWidth: Math.min(implicitWidth, overlay.width - Kirigami.Units.gridUnit * 6)
                visible: overlay.cue !== null && overlay.status === ""
                spacing: 2

                Repeater {
                    id: wordRepeater
                    model: overlay.cue ? overlay.cue.tokens : []

                    // A line break in the subtitle ends the row.
                    delegate: Item {
                        id: word
                        required property var modelData
                        readonly property bool newline: modelData.surface.indexOf("\n") >= 0
                        width: newline ? words.width : column.implicitWidth
                        height: newline ? 0 : column.implicitHeight

                        Rectangle {
                            anchors.fill: parent
                            anchors.margins: -2
                            radius: 4
                            color: Kirigami.Theme.highlightColor
                            opacity: wordHover.hovered && word.modelData.lookup ? 0.45 : 0
                        }
                        Column {
                            id: column
                            visible: !word.newline
                            Controls.Label {
                                anchors.horizontalCenter: parent.horizontalCenter
                                // Reserved even when empty, so words with and
                                // without furigana sit on one baseline.
                                text: overlay.showFurigana && word.modelData.furigana ? word.modelData.reading : " "
                                color: "#ffe9a8"
                                font.pixelSize: Math.round(jpText.font.pixelSize * 0.45)
                            }
                            Text {
                                id: jpText
                                text: word.modelData.surface
                                color: "white"
                                font.pixelSize: Math.max(22, Math.round(overlay.height * 0.045))
                                font.family: "Noto Sans CJK JP"
                                style: Text.Outline
                                styleColor: "black"
                            }
                        }

                        HoverHandler {
                            id: wordHover
                            cursorShape: word.modelData.lookup ? Qt.PointingHandCursor : Qt.ArrowCursor
                            onHoveredChanged: {
                                if (hovered && word.modelData.lookup) definition.show(word, word.modelData)
                                else if (!hovered && definition.target === word) definition.hide()
                            }
                        }
                        TapHandler {
                            enabled: word.modelData.lookup
                            onTapped: definition.save(word.modelData)
                        }
                    }
                }
            }

            Controls.Label {
                Layout.alignment: Qt.AlignHCenter
                Layout.maximumWidth: overlay.width - Kirigami.Units.gridUnit * 6
                visible: overlay.showRomaji && overlay.cue !== null && overlay.status === ""
                text: overlay.cue ? overlay.cue.romaji : ""
                color: "#cfd8ff"
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: Math.max(14, Math.round(overlay.height * 0.022))
                font.italic: true
            }
        }
    }

    // -- The definition card ---------------------------------------------------
    Rectangle {
        id: definition
        property var target: null
        property var token: null
        property var entries: []

        function show(item, token) {
            definition.target = item
            definition.token = token
            definition.entries = backend.lookupWord(token.lemma, token.surface, token.reading)
            // Above the whole line rather than the word, so it never covers
            // the speaker's name or the furigana it is explaining.
            let p = item.mapToItem(overlay, item.width / 2, 0)
            definition.x = Math.max(8, Math.min(overlay.width - width - 8, p.x - width / 2))
            definition.visible = true
        }
        function hide() { definition.visible = false; definition.target = null }
        function save(token) {
            let best = definition.entries.length ? definition.entries[0] : null
            backend.saveWord({
                word: best ? best.word : token.lemma,
                reading: best ? best.reading : token.reading,
                meaning: best && best.senses.length ? best.senses[0].glosses : "",
                pos: token.pos,
                sentence: overlay.cue ? overlay.cue.text : "",
                translation: overlay.video ? overlay.video.currentSubtitleText() : "",
                position: overlay.cue ? overlay.cue.start - overlay.offset : 0
            })
            overlay.wordSaved(best ? best.word : token.lemma)
        }

        visible: false
        z: 10
        // A binding, not set once in show(): the card's height is only known
        // after its new entries are laid out, and a y worked out from the
        // previous word's height put it on top of the line.
        y: Math.max(8, panel.y - height - 10)
        width: Math.min(Kirigami.Units.gridUnit * 22, overlay.width - 16)
        height: defColumn.implicitHeight + Kirigami.Units.largeSpacing * 2
        radius: Kirigami.Units.smallSpacing * 2
        color: Qt.rgba(0.08, 0.08, 0.1, 0.96)
        border.color: Kirigami.Theme.highlightColor
        border.width: 1

        ColumnLayout {
            id: defColumn
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.smallSpacing

            Controls.Label {
                visible: definition.entries.length === 0
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: "white"
                text: definition.token
                    ? (backend.dictionaryState() === "ready"
                       ? "\u201c" + definition.token.surface + "\u201d isn't in the dictionary -- often a name."
                       : "The dictionary is still being set up.")
                    : ""
            }

            Repeater {
                model: definition.entries
                ColumnLayout {
                    required property var modelData
                    required property int index
                    Layout.fillWidth: true
                    spacing: 2
                    RowLayout {
                        spacing: Kirigami.Units.smallSpacing
                        Controls.Label {
                            text: modelData.word
                            color: "white"
                            font.pixelSize: Kirigami.Units.gridUnit * 1.3
                            font.bold: index === 0
                        }
                        Controls.Label {
                            visible: modelData.reading !== modelData.word
                            text: modelData.reading
                            color: "#ffe9a8"
                        }
                        Controls.Label {
                            visible: modelData.common
                            text: "common"
                            color: Kirigami.Theme.positiveTextColor
                            font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                        }
                    }
                    Repeater {
                        model: modelData.senses
                        Controls.Label {
                            required property var modelData
                            required property int index
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            color: "white"
                            text: (index + 1) + ". " + modelData.glosses
                                + (modelData.pos ? "  <i>(" + modelData.pos + ")</i>" : "")
                            textFormat: Text.StyledText
                        }
                    }
                }
            }

            Controls.Label {
                Layout.fillWidth: true
                text: "Click to save  \u00b7  Dictionary: JMdict (EDRDG, CC BY-SA 4.0)"
                color: "white"
                opacity: 0.5
                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
            }
        }
    }
}
