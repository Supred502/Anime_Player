import QtQuick
import org.kde.kirigami as Kirigami

AppWindow {
    id: root

    pageStack.initialPage: Qt.resolvedUrl("HomePage.qml")

    // Translates phone-remote "open this anime" browse selections into the
    // exact same backend calls a card click already makes -- whichever page
    // is currently showing (Home/Browse) already has its own
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
}
