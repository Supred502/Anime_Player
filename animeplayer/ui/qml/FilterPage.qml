import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

// A real page instead of a Kirigami.OverlaySheet -- the sheet fought back on
// every attempt to bound its height correctly (see the extensive comment
// history that used to live in SearchPage.qml): Apply/Clear kept landing
// under the taskbar regardless of what height was requested, worse in
// windowed mode. A plain page uses the exact same ScrollablePage scrolling
// every other page in this app already relies on without issue, and can
// never render outside the window's own content area the way a popup could.
// Apply/Clear are pinned as header actions (always visible, no scrolling
// needed to reach them) rather than living at the bottom of the content.
Kirigami.ScrollablePage {
    id: filterPage
    title: "Filter by genre / tags"

    // The SearchPage instance that pushed this page -- all the actual filter
    // state (models, cycle functions, tagStates) lives there and is reused
    // as-is; this page is purely presentation over it.
    property var owner: null

    actions: [
        Kirigami.Action {
            text: "Clear all"
            icon.name: "edit-clear-all-symbolic"
            onTriggered: {
                let o = filterPage.owner
                for (let i = 0; i < o.genreModel.count; i++) o.genreModel.setProperty(i, "state", 0)
                for (let i = 0; i < o.tagModel.count; i++) o.tagModel.setProperty(i, "state", 0)
                for (let i = 0; i < o.statusModel.count; i++) o.statusModel.setProperty(i, "state", 0)
                for (let i = 0; i < o.formatModel.count; i++) o.formatModel.setProperty(i, "state", 0)
                o.tagStates = ({})
            }
        },
        Kirigami.Action {
            text: "Apply"
            icon.name: "dialog-ok-apply-symbolic"
            onTriggered: {
                applicationWindow().pageStack.pop()
                filterPage.owner.doSearch()
            }
        }
    ]

    ColumnLayout {
        width: filterPage.width
        spacing: Kirigami.Units.largeSpacing

        Controls.Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            opacity: 0.7
            text: "Click once to require a genre/tag, click again to exclude it, click a third time to clear it."
        }

        Kirigami.Heading {
            level: 3
            text: "Genres"
        }
        Flow {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            Repeater {
                model: filterPage.owner.genreModel
                delegate: FilterChip {
                    required property int index
                    required property var model
                    text: model.name
                    state3: model.state
                    onClicked: filterPage.owner.cycleGenre(index)
                }
            }
        }

        Kirigami.Heading {
            level: 3
            text: "Format"
        }
        Flow {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            Repeater {
                model: filterPage.owner.formatModel
                delegate: FilterChip {
                    required property int index
                    required property var model
                    text: model.name
                    state3: model.state
                    onClicked: filterPage.owner.cycleFormat(index)
                }
            }
        }

        Kirigami.Heading {
            level: 3
            text: "My List"
        }
        Controls.Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            opacity: 0.7
            text: "Include to show only that status, exclude to hide it -- e.g. exclude Completed, or include only Planning."
        }
        Flow {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            Repeater {
                model: filterPage.owner.statusModel
                delegate: FilterChip {
                    required property int index
                    required property var model
                    text: model.name
                    state3: model.state
                    onClicked: filterPage.owner.cycleStatus(index)
                }
            }
        }

        Kirigami.Heading {
            level: 3
            text: "Tags"
        }
        Controls.TextField {
            Layout.fillWidth: true
            placeholderText: "Filter tags (e.g. \"Time Skip\", \"Isekai\")..."
            onTextChanged: filterPage.owner.applyTagFilterText(text)
        }
        // Plain Flow, not wrapped in its own fixed-height ScrollView: the
        // whole page already scrolls (that's the point of using
        // ScrollablePage), so there's no need for a second, nested scroll
        // region here the way the old sheet needed one to stay bounded.
        Flow {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            Repeater {
                model: filterPage.owner.tagModel
                delegate: FilterChip {
                    required property int index
                    required property var model
                    text: model.name
                    state3: model.state
                    onClicked: filterPage.owner.cycleTag(index)
                }
            }
        }
    }

    // A tri-state chip: neutral (outline) -> include (green, check) -> exclude
    // (red, cross) -> back to neutral. Plain Controls.CheckBox only has two
    // states, so this is a small custom button instead.
    component FilterChip: Controls.Button {
        id: chip
        property int state3: 0 // 0 neutral, 1 include, 2 exclude
        Layout.alignment: Qt.AlignVCenter
        background: Rectangle {
            radius: height / 2
            border.width: 1
            border.color: chip.state3 === 1 ? Kirigami.Theme.positiveTextColor
                : chip.state3 === 2 ? Kirigami.Theme.negativeTextColor
                : Kirigami.Theme.disabledTextColor
            color: chip.state3 === 1 ? Qt.rgba(Kirigami.Theme.positiveTextColor.r, Kirigami.Theme.positiveTextColor.g, Kirigami.Theme.positiveTextColor.b, 0.18)
                : chip.state3 === 2 ? Qt.rgba(Kirigami.Theme.negativeTextColor.r, Kirigami.Theme.negativeTextColor.g, Kirigami.Theme.negativeTextColor.b, 0.18)
                : "transparent"
        }
        contentItem: RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Kirigami.Icon {
                visible: chip.state3 !== 0
                source: chip.state3 === 1 ? "dialog-ok-apply-symbolic" : (chip.state3 === 2 ? "dialog-cancel-symbolic" : "")
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: Kirigami.Units.iconSizes.small
                color: chip.state3 === 1 ? Kirigami.Theme.positiveTextColor : Kirigami.Theme.negativeTextColor
            }
            Controls.Label {
                text: chip.text
                color: chip.state3 === 1 ? Kirigami.Theme.positiveTextColor
                    : chip.state3 === 2 ? Kirigami.Theme.negativeTextColor
                    : Kirigami.Theme.textColor
            }
        }
    }
}
