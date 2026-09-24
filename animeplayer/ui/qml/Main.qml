import QtQuick
import org.kde.kirigami as Kirigami

AppWindow {
    id: root

    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")

    // Translates phone-remote "open this anime" browse selections into the
    // exact same backend calls a card click already makes -- whichever page
    // is currently showing (Home/Search) already has its own
    // onAnilistAnimeResolved handler to actually push DetailPage, so this
    // deliberately does NOT duplicate that navigation itself (that would
    // double-push if a page-level handler is also listening).
    Connections {
        target: backend
        function onRemoteServerFailed(message) {
            showPassiveNotification("Phone remote unavailable: " + message)
        }
        function onRemoteCommand(cmd, args) {
            if (cmd === "open_anime") backend.openAnilistAnime(args.id, args.title)
            else if (cmd === "open_continue_watching") backend.openContinueWatching(args)
        }
    }

    globalDrawer: Kirigami.GlobalDrawer {
            titleIcon: "video-television"
        actions: [
            Kirigami.Action {
                text: "Home"
                icon.name: "go-home-symbolic"
                onTriggered: root.pageStack.replace(Qt.resolvedUrl("HomePage.qml"))
            },
            Kirigami.Action {
                text: "Browse"
                icon.name: "view-list-details-symbolic"
                onTriggered: root.pageStack.replace(Qt.resolvedUrl("BrowsePage.qml"))
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
