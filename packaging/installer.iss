#ifndef AppVersion
  #error Pass /DAppVersion=<version> to ISCC.
#endif

[Setup]
AppId={{D35D11A6-0F6A-4EA4-B2A9-ED7B11F8D9DC}
AppName=ZomboidSorter
AppVersion={#AppVersion}
AppPublisher=ZomboidSorter contributors
AppPublisherURL=https://github.com/LookImEcho-Rick/ZomboidSorter
DefaultDirName={localappdata}\Programs\ZomboidSorter
DefaultGroupName=ZomboidSorter
PrivilegesRequired=lowest
UsePreviousAppDir=yes
UsePreviousSetupType=yes
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
InfoBeforeFile=SOURCE_OFFER.md
SetupIconFile=..\assets\zomboidsorter.ico
OutputDir=..\dist\installer
OutputBaseFilename=ZomboidSorter-{#AppVersion}-windows-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\ZomboidSorter.exe

[Types]
Name: "standard"; Description: "Standard installation"
Name: "portable"; Description: "Portable installation (keeps Mod Packs and settings beside the app)"

[Components]
Name: "application"; Description: "ZomboidSorter"; Types: standard portable; Flags: fixed

[Tasks]
Name: "startmenuicon"; Description: "Create a Start menu shortcut"; GroupDescription: "Shortcuts:"; Components: application
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked; Components: application

[InstallDelete]
Type: files; Name: "{app}\portable.flag"; Check: IsStandardInstall

[Files]
Source: "..\dist\ZomboidSorter\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\build\installer_payload\licenses\*"; DestDir: "{app}\licenses"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "portable.flag"; DestDir: "{app}"; Flags: ignoreversion; Check: IsPortableInstall
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "SOURCE_OFFER.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\ZomboidSorter"; Filename: "{app}\ZomboidSorter.exe"; Tasks: startmenuicon
Name: "{group}\Uninstall ZomboidSorter"; Filename: "{uninstallexe}"; Tasks: startmenuicon
Name: "{autodesktop}\ZomboidSorter"; Filename: "{app}\ZomboidSorter.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ZomboidSorter.exe"; Description: "Launch ZomboidSorter"; Flags: nowait postinstall skipifsilent

[Code]
function IsPortableInstall: Boolean;
begin
  Result := CompareText(WizardSetupType(False), 'portable') = 0;
end;

function IsStandardInstall: Boolean;
begin
  Result := not IsPortableInstall;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExistingPortable: Boolean;
begin
  Result := '';
  if not FileExists(ExpandConstant('{app}\ZomboidSorter.exe')) then
    Exit;

  ExistingPortable := FileExists(ExpandConstant('{app}\portable.flag'));
  if ExistingPortable = IsPortableInstall then
    Exit;

  if WizardSilent then
  begin
    Result := 'Switching between standard and portable mode requires an interactive install. Existing app data stays in its current location.';
    Exit;
  end;

  if SuppressibleMsgBox(
    'You are changing the app data mode. Existing settings and Mod Packs will stay in their current location, and the selected mode will use a separate data location. Export or import Mod Packs if you want to move them. Continue?',
    mbConfirmation, MB_YESNO, IDNO) <> IDYES then
    Result := 'Choose the installed mode to keep using its existing settings and Mod Packs.';
end;
