; Synclayer Windows installer (Inno Setup 6). Build: iscc /DAppVersion=0.1.1 packaging\windows\synclayer.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6A3E0C52-7B1D-4F6B-9C3E-5E2A1D8F7B10}
AppName=Synclayer
AppVersion={#AppVersion}
AppPublisher=Synclayer
DefaultDirName={autopf}\Synclayer
DefaultGroupName=Synclayer
UninstallDisplayIcon={app}\synclayer-gui.exe
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\dist
OutputBaseFilename=synclayer-{#AppVersion}-windows-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\..\build\synclayer.ico
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "startup"; Description: "Start Synclayer when I sign in"

[Files]
Source: "..\..\dist\synclayer-gui.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\synclayer.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\Synclayer"; Filename: "{app}\synclayer-gui.exe"
Name: "{autodesktop}\Synclayer"; Filename: "{app}\synclayer-gui.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Synclayer"; \
  ValueData: """{app}\synclayer-gui.exe"" tray --minimized"; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\synclayer-gui.exe"; Description: "Start Synclayer"; Flags: nowait postinstall skipifsilent
