// Frame times on Home: while it loads, while it scrolls down and back up,
// and while a shelf scrolls sideways. Reports the typical and worst frames.
import QtQuick
AppWindow {
    id: root
    width: 1600; height: 1000
    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    property var frames: []
    property string phase: "load"
    property real last: 0
    function log(m) { console.warn("[test] " + m) }
    property var track: []
    property bool tracking: false
    FrameAnimation {
        running: true
        onTriggered: {
            if (root.tracking) root.track.push(Math.round(root.flick().contentY))
            let now = Date.now()
            if (root.last) root.frames.push(now - root.last)
            root.last = now
        }
    }
    function report() {
        let f = root.frames.slice().sort((a, b) => a - b)
        if (!f.length) { log(root.phase + ": no frames"); return }
        let pct = (p) => f[Math.min(f.length - 1, Math.floor(f.length * p))]
        let over = f.filter((x) => x > 20).length
        log(root.phase + ": " + f.length + " frames, median " + pct(0.5) + "ms, p95 " + pct(0.95)
            + "ms, worst " + f[f.length - 1] + "ms, " + over + " over 20ms")
        root.frames = []
        root.last = 0
    }
    function flick() { return root.pageStack.currentItem.flickable }
    property var ys: []
    // The pointer across the first shelf and back, as a person looking for
    // something to watch does.
    Timer { id: sweep; property real x: 0; interval: 16; repeat: true
        onTriggered: { x = (x + 12) % root.width; windowChrome.hover(root, x, 520) } }
    // A notch of the mouse wheel every 150ms, downwards.
    Timer { id: wheel; property int n: 0; interval: 150; repeat: true
        onTriggered: { windowChrome.testWheel(root, 800, 600, -120); root.ys.push(Math.round(root.flick().contentY)) } }
    NumberAnimation { id: scrollDown; target: root.flick(); property: "contentY"; duration: 2500 }
    Timer {
        interval: 1000; running: true; repeat: true
        property int t: 0
        onTriggered: {
            t++
            if (t === 12) { root.report(); root.phase = "scroll down"
                scrollDown.target = root.flick(); scrollDown.from = 0
                scrollDown.to = Math.max(0, root.flick().contentHeight - root.flick().height); scrollDown.start() }
            if (t === 15) { root.report(); root.phase = "scroll up"
                scrollDown.from = scrollDown.to; scrollDown.to = 0; scrollDown.start() }
            if (t === 18) { root.report(); root.phase = "idle"; }
            if (t === 21) { root.report(); root.phase = "hover sweep"; sweep.x = 0; sweep.start() }
            if (t === 25) { sweep.stop(); root.report(); root.phase = "wheel"; root.ys = []; wheel.n = 0; wheel.start() }
            if (t === 29) { wheel.stop(); root.report()
                root.track = []; root.tracking = true; windowChrome.testWheel(root, 800, 600, -120) }
            if (t === 30) { root.tracking = false; log("one notch, contentY per frame: " + JSON.stringify(root.track.slice(0, 20))) }
            if (t === 31) {
                log("wheel: contentY per notch " + JSON.stringify(root.ys.slice(0, 12)))
                Qt.quit() }
        }
    }
}
