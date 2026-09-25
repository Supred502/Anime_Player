// Kirigami.Page: a Controls Page with the extras the global toolbar reads
// (title and actions are drawn by PageRow, above the page, as Kirigami does).
import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as K

QQC2.Page {
    id: page
    property list<QtObject> actions
    property int globalToolBarStyle: K.ApplicationHeaderStyle.ToolBar
    property Flickable flickable: null
    readonly property bool isCurrentPage: QQC2.StackView.status === QQC2.StackView.Active

    signal backRequested(var event)

    padding: K.Units.gridUnit
    background: Rectangle { color: K.Theme.backgroundColor }
}
