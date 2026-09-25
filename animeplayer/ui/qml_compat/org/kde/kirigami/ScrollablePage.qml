// Kirigami.ScrollablePage: the page scrolls as a whole.
//
// As in Kirigami: if the page's content is itself a scrolling view (a
// GridView, a ListView) it fills the page and scrolls on its own; anything
// else is put in a Flickable, padded by the page's padding, with the
// scrollbar at the page's edge rather than inside the padding.
import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as K

K.Page {
    id: page
    default property alias scrollablePageData: holder.data
    flickable: ownFlickable
    property int verticalScrollBarPolicy: QQC2.ScrollBar.AsNeeded
    property int horizontalScrollBarPolicy: QQC2.ScrollBar.AlwaysOff
    property bool supportsRefreshing: false
    property bool refreshing: false

    // Laid out by hand below, so the Page's own contentItem stays empty.
    contentItem: Item {}

    // Where the scrolling area goes: between the page's header and footer.
    // Parented to the page itself: a child declared here would otherwise
    // land in the Page's contentItem, which is already inset by the padding.
    Item {
        id: area
        parent: page
        x: 0
        y: page.header && page.header.visible ? page.header.height : 0
        width: page.width
        height: page.height - y - (page.footer && page.footer.visible ? page.footer.height : 0)
        clip: true

        // Declared children land here first and are sorted out once built.
        Item { id: holder }

        Flickable {
            id: ownFlickable
            anchors.fill: parent
            contentWidth: width
            contentHeight: content.height + page.topPadding + page.bottomPadding
            boundsBehavior: Flickable.StopAtBounds
            QQC2.ScrollBar.vertical: QQC2.ScrollBar { policy: page.verticalScrollBarPolicy }

            Item {
                id: content
                x: page.leftPadding
                y: page.topPadding
                width: page.availableWidth
                height: childrenRect.height
            }
        }
    }

    Component.onCompleted: {
        let kids = []
        for (let i = 0; i < holder.data.length; i++) kids.push(holder.data[i])
        for (let i = 0; i < kids.length; i++) {
            let child = kids[i]
            if (child instanceof Flickable) {
                // A scrolling view of its own: it is the page's scroller.
                ownFlickable.visible = false
                page.flickable = child
                child.parent = area
                child.anchors.fill = area
                if (!child.QQC2.ScrollBar.vertical) {
                    child.QQC2.ScrollBar.vertical = scrollBar.createObject(child)
                }
                page.background.color = Qt.binding(() => viewBackground)
            } else if (child instanceof Item) {
                child.parent = content
            }
            // Popups, timers, models and the like stay in `holder`, which
            // is where the page declared them as far as they can tell.
        }
    }
    // A scrolling view is drawn on Breeze's darker View background, as on KDE.
    readonly property color viewBackground: "#141618"
    Component { id: scrollBar; QQC2.ScrollBar { policy: page.verticalScrollBarPolicy } }
}
