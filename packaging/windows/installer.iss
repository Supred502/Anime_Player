; Inno Setup script for the Windows installer. Built by the GitHub workflow:
;   iscc /DAppVersion=1.2.3 packaging\windows\installer.iss
;
; Installs per user (no admin prompt), which is also what lets the app update
; itself: it downloads the next installer and runs it with /SILENT, which
; closes the running copy, replaces the files and starts the new one (the
; [Run] entry below is not skipped in silent mode).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6B0E8F3C-2A51-4E47-9C1D-5F2B7A9E4D10}
AppName=Anime Player
AppVersion={#AppVersion}
AppPublisher=Supred502
AppPublisherURL=https://github.com/Supred502/Anime_Player
DefaultDirName={localappdata}\Programs\Anime Player
DefaultGroupName=Anime Player
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist\installer
OutputBaseFilename=AnimePlayer-{#AppVersion}-Setup
SetupIconFile=..\..\vendor\AP.ico
UninstallDisplayIcon={app}\AnimePlayer.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[InstallDelete]
; The previous version's files: a library that a new version no longer ships
; must not linger and get loaded instead of the new one.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\..\dist\AnimePlayer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Anime Player"; Filename: "{app}\AnimePlayer.exe"; AppUserModelID: "Supred.AnimePlayer"
Name: "{userdesktop}\Anime Player"; Filename: "{app}\AnimePlayer.exe"; AppUserModelID: "Supred.AnimePlayer"; Tasks: desktopicon

[Run]
Filename: "{app}\AnimePlayer.exe"; Description: "Start Anime Player"; Flags: nowait postinstall
