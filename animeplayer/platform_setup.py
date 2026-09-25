"""What the app needs from the operating system before Qt and mpv start.

Nothing here does anything on Linux. On Windows, the installed app is a
PyInstaller bundle carrying its own libmpv-2.dll and ffmpeg.exe (see
packaging/windows), and those have to be findable before `import mpv` and
before the first download.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# The Start-menu shortcut the installer makes carries the same id, which is
# what lets Windows show this app's name on its notifications and group its
# taskbar button (see packaging/windows/installer.iss).
APP_USER_MODEL_ID = "Supred.AnimePlayer"

# Keeps ffmpeg and friends from flashing a console window on Windows.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def bundle_dir() -> Path | None:
    """The folder PyInstaller unpacked the app's files into, if frozen."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else None


def before_imports() -> None:
    if sys.platform != "win32":
        return
    folders = [p for p in (bundle_dir(), Path(sys.executable).parent) if p]
    os.environ["PATH"] = os.pathsep.join([*map(str, folders), os.environ.get("PATH", "")])
    for folder in folders:
        try:
            os.add_dll_directory(str(folder))
        except OSError:
            pass
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass


def before_app() -> None:
    """Before QGuiApplication. mpv renders into an OpenGL framebuffer (see
    player/mpv_video_item.py); Qt Quick on Windows defaults to Direct3D,
    where there's no OpenGL context for it to draw into."""
    if sys.platform != "win32":
        return
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)


def notify(title: str, body: str) -> bool:
    """A Windows toast notification, through PowerShell's access to the
    WinRT notification API -- there's no Python binding for it in the
    standard library. Returns False where that isn't possible."""
    if sys.platform != "win32":
        return False

    def xml(text: str) -> str:
        return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;").replace("'", "''"))

    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null;"
        "$x = New-Object Windows.Data.Xml.Dom.XmlDocument;"
        f"$x.LoadXml('<toast><visual><binding template=\"ToastGeneric\"><text>{xml(title)}</text>"
        f"<text>{xml(body)}</text></binding></visual></toast>');"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{APP_USER_MODEL_ID}')"
        ".Show([Windows.UI.Notifications.ToastNotification]::new($x))"
    )
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    except OSError:
        return False
    return True
