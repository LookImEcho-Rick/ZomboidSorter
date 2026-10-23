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

[Files]
Source: "..\dist\ZomboidSorter\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "SOURCE_OFFER.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion

[Icons]
Name: "{group}\ZomboidSorter"; Filename: "{app}\ZomboidSorter.exe"
Name: "{group}\Uninstall ZomboidSorter"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\ZomboidSorter.exe"; Description: "Launch ZomboidSorter"; Flags: nowait postinstall skipifsilent
