// Kirigami.FormLayout: fields in a column, each with its label (from
// Kirigami.FormData.label) right-aligned to its left, the whole form
// centred in the space it's given.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as K

Item {
    id: form
    default property alias formData: holder.data
    property bool wideMode: true

    implicitWidth: grid.implicitWidth
    implicitHeight: grid.implicitHeight
    Layout.preferredHeight: grid.implicitHeight

    Item { id: holder; visible: false }

    GridLayout {
        id: grid
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(implicitWidth, form.width)
        columns: 2
        columnSpacing: K.Units.largeSpacing
        rowSpacing: K.Units.smallSpacing
    }

    Component {
        id: labelComponent
        QQC2.Label {
            property Item field
            text: field ? field.K.FormData.label : ""
            visible: field ? field.visible && text.trim() !== "" : false
            Layout.alignment: Qt.AlignRight | (field && field.implicitHeight > K.Units.gridUnit * 2.5
                                               ? Qt.AlignTop : Qt.AlignVCenter)
            Layout.topMargin: field && field.implicitHeight > K.Units.gridUnit * 2.5 ? K.Units.smallSpacing : 0
            horizontalAlignment: Text.AlignRight
        }
    }
    Component { id: spacerComponent; Item { property Item field; visible: field ? field.visible : false } }

    Component.onCompleted: {
        let kids = []
        for (let i = 0; i < holder.children.length; i++) kids.push(holder.children[i])
        for (let i = 0; i < kids.length; i++) {
            let field = kids[i]
            let label = field.K.FormData.label
            if (label !== "" && label.trim() === "") {
                spacerComponent.createObject(grid, { field: field })
            } else if (label !== "") {
                labelComponent.createObject(grid, { field: field })
            } else {
                spacerComponent.createObject(grid, { field: field })
            }
            field.parent = grid
            field.Layout.alignment = Qt.AlignLeft | Qt.AlignVCenter
        }
    }
}
