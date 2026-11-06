; Windows installer for the Nexus app (Inno Setup 6). Built by .github/workflows/desktop.yml:
;   iscc /DAppVersion=4.5.0 installer.iss   (after PyInstaller made dist\nexus\)
; Installs for the current user only (no admin rights), into %LOCALAPPDATA%\Programs\Nexus,
; with a Start menu entry and an uninstaller in Settings › Apps. Updates run this same installer silently.
; Up to 4.4 this was "valcoach companion" (same AppId): an update keeps its folder and removes its old program
; file and shortcuts.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8C5E0F5B-6E3B-4C59-9E1A-0B7C3E2A4F10}
AppName=Nexus
AppVersion={#AppVersion}
AppVerName=Nexus {#AppVersion}
AppPublisher=Nexus
AppPublisherURL=https://github.com/ManuelSqp/valcoach
DefaultDirName={localappdata}\Programs\Nexus
DefaultGroupName=Nexus
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=nexus-setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\nexus.exe
UninstallDisplayName=Nexus
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; the previous version's libraries: a new Python or package version leaves no stale files behind
Type: filesandordirs; Name: "{app}\_internal"
; the companion app before 4.5
Type: files; Name: "{app}\valcoach-companion.exe"
Type: files; Name: "{autoprograms}\valcoach companion.lnk"
Type: files; Name: "{autodesktop}\valcoach companion.lnk"

[Files]
Source: "dist\nexus\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Nexus"; Filename: "{app}\nexus.exe"
Name: "{autodesktop}\Nexus"; Filename: "{app}\nexus.exe"; Tasks: desktopicon

[Registry]
; "Start with Windows" (set by the app) is removed again when the app is uninstalled
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Nexus"; Flags: uninsdeletevalue dontcreatekey

[Run]
; after a normal install: a checkbox "Launch"; after a silent update: start the app again by itself
Filename: "{app}\nexus.exe"; Description: "{cm:LaunchProgram,Nexus}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\nexus.exe"; Flags: nowait; Check: WizardSilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM nexus.exe /IM valcoach-companion.exe /F"; Flags: runhidden; RunOnceId: "StopApp"
