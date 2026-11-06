; Windows installer for the companion app (Inno Setup 6). Built by .github/workflows/companion.yml:
;   iscc /DAppVersion=4.4.0 installer.iss   (after PyInstaller made dist\valcoach-companion\)
; Installs for the current user only (no admin rights), into %LOCALAPPDATA%\Programs\valcoach companion,
; with a Start menu entry and an uninstaller in Settings › Apps. Updates run this same installer silently.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8C5E0F5B-6E3B-4C59-9E1A-0B7C3E2A4F10}
AppName=valcoach companion
AppVersion={#AppVersion}
AppVerName=valcoach companion {#AppVersion}
AppPublisher=valcoach
AppPublisherURL=https://github.com/ManuelSqp/valcoach
DefaultDirName={localappdata}\Programs\valcoach companion
DefaultGroupName=valcoach companion
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=valcoach-companion-setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\valcoach-companion.exe
UninstallDisplayName=valcoach companion
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

[Files]
Source: "dist\valcoach-companion\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\valcoach companion"; Filename: "{app}\valcoach-companion.exe"
Name: "{autodesktop}\valcoach companion"; Filename: "{app}\valcoach-companion.exe"; Tasks: desktopicon

[Registry]
; "Start with Windows" (set by the app) is removed again when the app is uninstalled
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "valcoach companion"; Flags: uninsdeletevalue dontcreatekey

[Run]
; after a normal install: a checkbox "Launch"; after a silent update: start the app again by itself
Filename: "{app}\valcoach-companion.exe"; Description: "{cm:LaunchProgram,valcoach companion}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\valcoach-companion.exe"; Flags: nowait; Check: WizardSilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM valcoach-companion.exe /F"; Flags: runhidden; RunOnceId: "StopApp"
