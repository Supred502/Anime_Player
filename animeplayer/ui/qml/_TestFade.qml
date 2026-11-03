// Pages and popups fade in: samples their opacity just after they appear.
import QtQuick
import QtQuick.Controls as Controls
AppWindow {
    id: root
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    function log(m) { console.warn("[test] " + m) }
    property var samples: []
    property var watched: null
    Controls.Popup { id: probe; parent: root.contentItem; width: 200; height: 100; x: 50; y: 50 }
    Timer { id: sampler; interval: 40; repeat: true
        onTriggered: { root.samples.push(Math.round(root.watched.opacity * 100) / 100); if (root.samples.length >= 8) { stop(); log(root.watched + " " + JSON.stringify(root.samples)); root.samples = [] } } }
    Timer { interval: 4000; running: true; onTriggered: { root.watched = root.goBrowse(); sampler.start(); next.start() } }
    Timer { id: next; interval: 1500; onTriggered: { probe.open(); root.watched = probe; sampler.start(); done.start() } }
    Timer { id: done; interval: 1500; onTriggered: Qt.quit() }
}
