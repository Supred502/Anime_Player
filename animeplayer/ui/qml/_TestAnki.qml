// Exports the saved words to an Anki deck with audio, as Export to Anki does.
import QtQuick
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("WordsPage.qml")
    function log(m) { console.warn("[test] " + m) }
    Connections {
        target: backend
        function onAnkiProgress(done, total) { log("audio " + done + "/" + total) }
        function onAnkiExported(path, count) { log("exported " + count + " to " + path); Qt.quit() }
        function onAnkiFailed(message) { log("failed " + message); Qt.quit() }
    }
    Timer { interval: 2000; running: true; onTriggered: backend.exportAnki(testShots + "/words", true) }
}
