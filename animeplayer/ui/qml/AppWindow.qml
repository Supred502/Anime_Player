// The application window.
//
// Exists so that Main.qml and the live E2E drivers (_Test*Real.qml) all open
// the same window, rather than each growing its own copy of the settings
// below. The colour scheme is applied per page -- see AppTheming.qml for why.
import QtQuick
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root
    title: "Anime Player"
    width: 1280
    height: 800

    // This app is a linear Home -> Detail -> Player stack, not a master-detail
    // browser, so force single-column navigation. Without this, Kirigami's
    // PageRow keeps previous pages visible side-by-side as "columns" once the
    // window is wide enough (its default adaptive behavior), which reads as a
    // stray sidebar here.
    pageStack.columnView.columnResizeMode: Kirigami.ColumnView.SingleColumn
}
