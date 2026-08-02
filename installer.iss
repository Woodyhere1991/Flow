#define MyAppName "Flow"
#define MyAppVersion "1.1.0"
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
Source: "hardware_profile.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "constraints.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "setup.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion; AfterInstall: InstallDependencies

[Icons]
Name: "{autodesktop}\Flow"; Filename: "{app}\venv\Scripts\pythonw.exe"; Parameters: """{app}\hotkey.py"""; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function RunDependencySetup(ExtraArguments: String;
  var ResultCode: Integer): Boolean;
var
  CommandLine: String;
begin
  CommandLine := '/D /C ""' + ExpandConstant('{app}\setup.bat') +
    '" --installed ' + ExtraArguments + '"';
  Result := Exec(ExpandConstant('{cmd}'), CommandLine, ExpandConstant('{app}'),
    SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode);
end;

procedure InstallDependencies;
var
  ResultCode: Integer;
  Choice: Integer;
begin
  WizardForm.StatusLabel.Caption :=
    'Checking this computer and downloading the best Flow setup...';
  if not RunDependencySetup('', ResultCode) then
    RaiseException('Flow setup could not start: ' + SysErrorMessage(ResultCode));

  if ResultCode = 3 then
  begin
    Choice := MsgBox(
      'This computer has no supported NVIDIA graphics card.' + #13#10 + #13#10 +
      'Flow can install its smallest speech model, but it may still take a ' +
      'long time after every recording. On older computers it may not be ' +
      'useful.' + #13#10 + #13#10 +
      'Do you want to install the slower CPU version?',
      mbConfirmation, MB_YESNO);
    if Choice <> IDYES then
      RaiseException('Installation cancelled because Flow may be too slow on this computer.');
    if not RunDependencySetup('--allow-slow', ResultCode) then
      RaiseException('Flow setup could not restart: ' + SysErrorMessage(ResultCode));
  end;

  if ResultCode = 4 then
    RaiseException(
      'Flow found an NVIDIA graphics card but could not enable it. ' +
      'Setup stopped rather than installing an unexpectedly slow version.');
  if ResultCode <> 0 then
    RaiseException(
      'Flow setup did not finish. Check your internet connection and try again.');
end;
