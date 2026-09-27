"""A stand-in for the parts of KDE's Kirigami this app uses, for Windows.

Kirigami is KDE's QML toolkit. It ships with every Plasma desktop, but not
with PySide6 from pip, and there is no Windows build of it that matches
PySide6's own Qt. So on Windows (and anywhere else it's missing) the app
imports this instead: `import org.kde.kirigami` then resolves to
ui/qml_compat/org/kde/kirigami, whose QML files cover the visual types
(pages, headings, the form layout...) and whose attached properties and
singletons -- things QML files cannot declare -- are registered here.

It covers exactly what the app's QML uses, measured against the real thing
on Plasma 6 (Breeze Dark) so the two builds look the same: the colours
below are Breeze Dark's Window set, which is what Kirigami hands every item
in this app, and the sizes are Kirigami's own at a 10pt font.

The attached Theme is simpler than Kirigami's on purpose. Kirigami gives
every item its own colours, inherited down the item tree; this app only ever
changes the accent, and changes it everywhere at once (AppTheming.qml). So
here every colour is app-wide, and setting the accent on any item sets it
for all of them.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPalette

COMPAT_DIR = Path(__file__).parent / "qml_compat"

# Breeze Dark, Window colour set.
PALETTE = {
    "textColor": "#fcfcfc",
    "disabledTextColor": "#a1a9b1",
    "highlightColor": "#3daee9",
    "highlightedTextColor": "#fcfcfc",
    "backgroundColor": "#202326",
    "alternateBackgroundColor": "#292c30",
    "activeTextColor": "#3daee9",
    "activeBackgroundColor": "#1e5774",
    "linkColor": "#1d99f3",
    "linkBackgroundColor": "#1d99f3",
    "visitedLinkColor": "#9b59b6",
    "visitedLinkBackgroundColor": "#9b59b6",
    "negativeTextColor": "#da4453",
    "negativeBackgroundColor": "#4d1f24",
    "neutralTextColor": "#f67400",
    "neutralBackgroundColor": "#45300f",
    "positiveTextColor": "#27ae60",
    "positiveBackgroundColor": "#113a22",
    "focusColor": "#3daee9",
    "hoverColor": "#3daee9",
}


def needed() -> bool:
    """True when the real Kirigami isn't installed (or ANIMEPLAYER_COMPAT_UI
    asks for the stand-in anyway, to preview the Windows look on Linux)."""
    if os.environ.get("ANIMEPLAYER_COMPAT_UI"):
        return True
    from PySide6.QtCore import QLibraryInfo
    qml_root = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.QmlImportsPath))
    return not (qml_root / "org" / "kde" / "kirigami" / "qmldir").exists()


ICON_DIR = Path(__file__).parent / "assets" / "icons"


def register() -> None:
    """Registers the stand-in's attached properties and singletons. Only
    when the stand-in is used -- where the real Kirigami is, its styles
    would read these instead of its own -- and before QGuiApplication:
    registered any later, stock Qt Quick types started failing to load
    (Fusion's buttons: "Cannot assign object of type QGradient")."""
    from animeplayer.ui import _kirigami_types  # noqa: F401


def install(engine) -> None:
    """Points `engine` at the stand-in, ahead of any real Kirigami, and gives
    stock controls the same look: the Fusion style in Breeze Dark colours,
    and the bundled Breeze icons. The types above registered themselves when
    this module was imported. Call after QGuiApplication, before loading QML."""
    engine.addImportPath(str(COMPAT_DIR))
    # The app is dark whatever the system is set to. On a Windows PC in
    # light mode, text created after a page had loaded (the Schedule's rows)
    # came out black on the dark background: stock controls fall back to the
    # system's light palette wherever the app's own doesn't reach. Saying
    # the app is dark covers that, and the window's palette is also set
    # explicitly (see ApplicationWindow.qml).
    from PySide6.QtCore import Qt
    QGuiApplication.styleHints().setColorScheme(Qt.ColorScheme.Dark)

    QIcon.setThemeSearchPaths([str(ICON_DIR), *QIcon.themeSearchPaths()])
    QIcon.setThemeName("breeze-compat")
    QIcon.setFallbackThemeName("breeze-compat")

    c = {k: QColor(v) for k, v in PALETTE.items()}
    palette = QPalette()
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        palette.setColor(group, QPalette.ColorRole.Window, c["backgroundColor"])
        palette.setColor(group, QPalette.ColorRole.WindowText, c["textColor"])
        palette.setColor(group, QPalette.ColorRole.Base, QColor("#141618"))
        palette.setColor(group, QPalette.ColorRole.AlternateBase, QColor("#1d1f22"))
        palette.setColor(group, QPalette.ColorRole.Text, c["textColor"])
        palette.setColor(group, QPalette.ColorRole.Button, QColor("#292c30"))
        palette.setColor(group, QPalette.ColorRole.ButtonText, c["textColor"])
        palette.setColor(group, QPalette.ColorRole.BrightText, QColor("#ffffff"))
        palette.setColor(group, QPalette.ColorRole.Highlight, c["highlightColor"])
        palette.setColor(group, QPalette.ColorRole.Accent, c["highlightColor"])
        palette.setColor(group, QPalette.ColorRole.HighlightedText, c["highlightedTextColor"])
        palette.setColor(group, QPalette.ColorRole.ToolTipBase, QColor("#292c30"))
        palette.setColor(group, QPalette.ColorRole.ToolTipText, c["textColor"])
        palette.setColor(group, QPalette.ColorRole.PlaceholderText, c["disabledTextColor"])
        palette.setColor(group, QPalette.ColorRole.Link, c["linkColor"])
        palette.setColor(group, QPalette.ColorRole.LinkVisited, c["visitedLinkColor"])
        palette.setColor(group, QPalette.ColorRole.Light, QColor("#3b4045"))
        palette.setColor(group, QPalette.ColorRole.Midlight, QColor("#33373b"))
        palette.setColor(group, QPalette.ColorRole.Mid, QColor("#25282b"))
        palette.setColor(group, QPalette.ColorRole.Dark, QColor("#141618"))
        palette.setColor(group, QPalette.ColorRole.Shadow, QColor("#0a0b0c"))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#6e7175"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Window, c["backgroundColor"])
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor("#141618"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, QColor("#25282b"))
    QGuiApplication.setPalette(palette)
