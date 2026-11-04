// The Japanese line with a fake two-line cue, then a short one, grabbed to PNGs.
import QtQuick
AppWindow {
    id: root
    width: 1600; height: 900
    function tok(s, r) { return { surface: s, reading: r || "", furigana: !!r, lookup: !!r, lemma: s } }
    LearnOverlay {
        id: o
        anchors.fill: parent
        cues: [
            { start: 0, end: 5, text: "", romaji: "kyou wa ii tenki desu ne / sou desu ne",
              tokens: [root.tok("今日", "きょう"), root.tok("は"), root.tok("いい"), root.tok("天気", "てんき"), root.tok("です"), root.tok("ね"),
                       root.tok("\n"), root.tok("そう"), root.tok("です"), root.tok("ね")] },
            { start: 6, end: 9, text: "", romaji: "un", tokens: [root.tok("うん")] },
            { start: 10, end: 14, text: "", romaji: "", tokens: [root.tok("行こう", "いこう"), root.tok("か"), root.tok("！")] }
        ]
    }
    property int step: 0
    Timer {
        interval: 1200; running: true; repeat: true
        onTriggered: {
            let at = [1, 7, 11][root.step]
            if (at === undefined) { Qt.quit(); return }
            o.update(at)
            let n = root.step++
            Qt.callLater(() => o.grabToImage((r) => r.saveToFile(Qt.application.arguments[Qt.application.arguments.length - 1] + "/line" + n + ".png")))
        }
    }
}
