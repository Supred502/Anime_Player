import QtQuick
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root
    title: "Anime Player"
    width: 1280
    height: 800

    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")
    // This app is a linear Search -> Detail -> Player stack, not a master-detail
    // browser, so force single-column navigation. Without this, Kirigami's
    // PageRow keeps previous pages visible side-by-side as "columns" once the
    // window is wide enough (its default adaptive behavior), which reads as a
    // stray sidebar here.
    pageStack.columnView.columnResizeMode: Kirigami.ColumnView.SingleColumn

    // Translates phone-remote "open this anime" browse selections into the
    // exact same backend calls a card click already makes -- whichever page
    // is currently showing (Home/Search) already has its own
    // onAnilistAnimeResolved handler to actually push DetailPage, so this
    // deliberately does NOT duplicate that navigation itself (that would
    // double-push if a page-level handler is also listening).
    Connections {
        target: backend
        function onRemoteCommand(cmd, args) {
            if (cmd === "open_anime") backend.openAnilistAnime(args.id, args.title)
            else if (cmd === "open_continue_watching") backend.openContinueWatching(args)
        }
    }

    globalDrawer: Kirigami.GlobalDrawer {
        title: "Anime Player"
        titleIcon: "video-television"
        actions: [
            Kirigami.Action {
                text: "Home"
                icon.name: "go-home-symbolic"
                onTriggered: root.pageStack.replace(Qt.resolvedUrl("HomePage.qml"))
            },
            Kirigami.Action {
                text: "Search"
                icon.name: "edit-find-symbolic"
                onTriggered: root.pageStack.replace(Qt.resolvedUrl("SearchPage.qml"))
            },
            Kirigami.Action {
                text: "Settings"
                icon.name: "configure-symbolic"
                onTriggered: root.pageStack.replace(Qt.resolvedUrl("SettingsPage.qml"))
            }
        ]
    }
}
