#define MyAppName "Flow"
#define MyAppVersion "1.0.1"
#define MyAppPublisher "Woodyhere1991"
#define MyAppURL "https://github.com/Woodyhere1991/Flow"

[Setup]
AppId={{7D8AC564-AC04-4D70-8C06-FDB76CF63E66}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Flow\app
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=Flow-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
CloseApplications=yes
RestartApplications=no

[Files]
Source: "app.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "hotkey.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "overlay.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "transcribe.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "ui.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "wintext.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "make_icon.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "prepare_offline.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "constraints.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "setup.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion; AfterInstall: InstallDependencies

[Icons]
Name: "{autodesktop}\Flow"; Filename: "{app}\venv\Scripts\pythonw.exe"; Parameters: """{app}\hotkey.py"""; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure InstallDependencies;
var
  ResultCode: Integer;
  CommandLine: String;
begin
  WizardForm.StatusLabel.Caption :=
    'Downloading everything Flow needs for offline use...';
  CommandLine := '/D /C ""' + ExpandConstant('{app}\setup.bat') +
    '" --installed"';
  if not Exec(ExpandConstant('{cmd}'), CommandLine, ExpandConstant('{app}'),
    SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode) then
    RaiseException('Flow setup could not start: ' + SysErrorMessage(ResultCode));
  if ResultCode <> 0 then
    RaiseException(
      'Flow setup did not finish. Check your internet connection and try again.');
end;
