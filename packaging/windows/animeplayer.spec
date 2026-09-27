# PyInstaller spec for the Windows build: `pyinstaller packaging/windows/animeplayer.spec`
# from the repository root, after vendor/ has been filled with libmpv-2.dll,
# ffmpeg.exe, ffprobe.exe and AP.ico (the GitHub workflow does all of this --
# see .github/workflows/release.yml).
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]
VENDOR = ROOT / "vendor"
UI = ROOT / "animeplayer" / "ui"

datas = [
    (str(UI / "qml"), "animeplayer/ui/qml"),
    (str(UI / "qml_compat"), "animeplayer/ui/qml_compat"),
    (str(UI / "assets"), "animeplayer/ui/assets"),
]
datas += collect_data_files("unidic_lite")
datas += collect_data_files("cutlet")
datas += collect_data_files("fugashi")
datas += collect_data_files("genanki")

binaries = [
    (str(VENDOR / "libmpv-2.dll"), "."),
    (str(VENDOR / "ffmpeg.exe"), "."),
    (str(VENDOR / "ffprobe.exe"), "."),
]
binaries += collect_dynamic_libs("fugashi")
binaries += collect_dynamic_libs("sdl2dll")
datas += collect_data_files("sdl2dll")

a = Analysis(
    [str(ROOT / "packaging" / "windows" / "launch.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        *collect_submodules("animeplayer"),
        *collect_submodules("keyring.backends"),
        "win32ctypes.core",
        # Loaded by name at runtime (fugashi finds its dictionary by
        # importing unidic_lite), so the analysis doesn't see them.
        "unidic_lite",
        "fugashi",
        *collect_submodules("cutlet"),
        *collect_submodules("genanki"),
        *collect_submodules("sdl2"),
        "sdl2dll",
    ],
    excludes=["tkinter", "pytest", "respx"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AnimePlayer",
    icon=str(VENDOR / "AP.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="AnimePlayer", upx=False)
