; thinkNXG Support Agent - Windows installer (Inno Setup 6). Built by .github/workflows/agent-app.yml:
;   iscc /DAppVersion=1.9.0 /DSourceDir=..\build\windows\x64\runner\Release installer\thinknxg_agent.iss
#ifndef AppVersion
  #define AppVersion "1.9.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\build\windows\x64\runner\Release"
#endif

[Setup]
AppId={{6F1B7F6E-1A1D-4B7A-9F53-0D3C2E9A4B21}
AppName=thinkNXG Support Agent
AppVersion={#AppVersion}
AppPublisher=Kreatao
AppPublisherURL=https://thinknxg.com/thinkdesk
DefaultDirName={autopf}\thinkNXG Support Agent
DefaultGroupName=thinkNXG Support Agent
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\build\installer
OutputBaseFilename=thinkNXG-Support-Agent-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\thinknxg_agent.exe
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "Start with Windows, in the background (so alerts reach you without opening the app)"; GroupDescription: "Options:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\thinkNXG Support Agent"; Filename: "{app}\thinknxg_agent.exe"
Name: "{autodesktop}\thinkNXG Support Agent"; Filename: "{app}\thinknxg_agent.exe"; Tasks: desktopicon

[Registry]
; Start at sign-in, hidden in the system tray. The app's Alerts tab switches the same value on and off.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "thinkNXG Support Agent"; ValueData: """{app}\thinknxg_agent.exe"" --hidden"; Tasks: startup; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "thinkNXG Support Agent"; Flags: uninsdeletevalue dontcreatekey

[InstallDelete]
; 1.14 and earlier used a Startup-folder shortcut (which opened the window)
Type: files; Name: "{userstartup}\thinkNXG Support Agent.lnk"

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM thinknxg_agent.exe /F"; Flags: runhidden; RunOnceId: "StopAgent"

[Run]
Filename: "{app}\thinknxg_agent.exe"; Description: "{cm:LaunchProgram,thinkNXG Support Agent}"; Flags: nowait postinstall skipifsilent
