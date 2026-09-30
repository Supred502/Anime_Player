// "This season | This week" at the top of the Seasonal section: the season's
// shows (SeasonalPage) and what airs in the next seven days (SchedulePage)
// are one nav entry with two tabs. The last one used is where the nav entry
// opens (AppWindow.goSeasonal).
import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

RowLayout {
    id: tabs
    required property string current      // "season" or "week"
    spacing: Kirigami.Units.smallSpacing

    AppButton {
        text: "This season"
        icon.name: "view-calendar-month-symbolic"
        checkable: true
        checked: tabs.current === "season"
        onClicked: if (tabs.current !== "season") applicationWindow().goSeasonal("season")
    }
    AppButton {
        text: "This week"
        icon.name: "view-calendar-week-symbolic"
        checkable: true
        checked: tabs.current === "week"
        onClicked: if (tabs.current !== "week") applicationWindow().goSeasonal("week")
    }
}
