"""The attached properties and singletons of the Kirigami stand-in -- see
kirigami_compat.py. Importing this module registers them as
org.kde.kirigami types, so it is imported only when the stand-in is used.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtQml import QmlAttached, QmlElement, QmlSingleton

from animeplayer.ui.kirigami_compat import PALETTE

QML_IMPORT_NAME = "org.kde.kirigami"
QML_IMPORT_MAJOR_VERSION = 2


class _Colors(QObject):
    """The one shared palette every attached Theme reads."""
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.values = {k: QColor(v) for k, v in PALETTE.items()}

    def set(self, name: str, value) -> None:
        color = QColor(value)
        if self.values.get(name) != color:
            self.values[name] = color
            self.changed.emit()
            if name == "highlightColor":
                # Stock controls (checkboxes, sliders, text selection) draw
                # their accent from the palette, not from Kirigami.Theme.
                palette = QGuiApplication.palette()
                palette.setColor(QPalette.ColorRole.Highlight, color)
                palette.setColor(QPalette.ColorRole.Accent, color)
                QGuiApplication.setPalette(palette)


_colors = _Colors()


def _font(point_size: float) -> QFont:
    font = QFont(QGuiApplication.font())
    font.setPointSizeF(point_size)
    return font


class ThemeAttached(QObject):
    changed = Signal()
    inheritChanged = Signal()

    # Kirigami.Theme.ColorSet values. Accepted and remembered, not acted on:
    # everything in this app draws from the Window set anyway.
    View, Window, Button, Selection, Tooltip, Complementary, Header = range(7)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._inherit = True
        self._color_set = self.Window
        try:
            _colors.changed.connect(self.changed)
        except RuntimeError:
            pass  # during shutdown, after the palette object is gone

    def _get_inherit(self) -> bool:
        return self._inherit

    def _set_inherit(self, value: bool) -> None:
        if value != self._inherit:
            self._inherit = value
            self.inheritChanged.emit()

    inherit = Property(bool, _get_inherit, _set_inherit, notify=inheritChanged)

    def _get_color_set(self) -> int:
        return self._color_set

    def _set_color_set(self, value: int) -> None:
        self._color_set = value

    colorSet = Property(int, _get_color_set, _set_color_set, notify=inheritChanged)
    colorGroup = Property(int, lambda self: 0, lambda self, value: None, notify=inheritChanged)

    defaultFont = Property(QFont, lambda self: _font(QGuiApplication.font().pointSizeF()), notify=changed)
    smallFont = Property(QFont, lambda self: _font(max(1.0, QGuiApplication.font().pointSizeF() - 2)),
                         notify=changed)

    for _name in PALETTE:
        locals()[_name] = Property(
            QColor,
            lambda self, n=_name: _colors.values[n],
            lambda self, value, n=_name: _colors.set(n, value),
            notify=changed)
    del _name


@QmlElement
@QmlAttached(ThemeAttached)
class Theme(QObject):
    @staticmethod
    def qmlAttachedProperties(_cls, owner: QObject) -> ThemeAttached:
        return ThemeAttached(owner)


class _IconSizes(QObject):
    _sizes = {"small": 16, "smallMedium": 22, "medium": 32, "large": 48, "huge": 64, "enormous": 128}
    for _name, _value in _sizes.items():
        locals()[_name] = Property(int, lambda self, v=_value: v, constant=True)
    del _name, _value

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)


@QmlElement
@QmlSingleton
class Units(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._icon_sizes = _IconSizes(self)

    gridUnit = Property(int, lambda self: 18, constant=True)
    smallSpacing = Property(int, lambda self: 4, constant=True)
    mediumSpacing = Property(int, lambda self: 6, constant=True)
    largeSpacing = Property(int, lambda self: 8, constant=True)
    veryShortDuration = Property(int, lambda self: 50, constant=True)
    shortDuration = Property(int, lambda self: 100, constant=True)
    longDuration = Property(int, lambda self: 200, constant=True)
    veryLongDuration = Property(int, lambda self: 400, constant=True)
    humanMoment = Property(int, lambda self: 2000, constant=True)
    toolTipDelay = Property(int, lambda self: 700, constant=True)
    iconSizes = Property(QObject, lambda self: self._icon_sizes, constant=True)


class FormDataAttached(QObject):
    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._label = ""
        self._is_section = False

    def _get_label(self) -> str:
        return self._label

    def _set_label(self, value: str) -> None:
        if value != self._label:
            self._label = value
            self.changed.emit()

    label = Property(str, _get_label, _set_label, notify=changed)

    def _get_is_section(self) -> bool:
        return self._is_section

    def _set_is_section(self, value: bool) -> None:
        if value != self._is_section:
            self._is_section = value
            self.changed.emit()

    isSection = Property(bool, _get_is_section, _set_is_section, notify=changed)


@QmlElement
@QmlAttached(FormDataAttached)
class FormData(QObject):
    @staticmethod
    def qmlAttachedProperties(_cls, owner: QObject) -> FormDataAttached:
        return FormDataAttached(owner)
