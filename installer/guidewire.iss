; Inno Setup script for GuideWire.   Build:  python installer/build_windows.py --installer     (needs dist\GuideWire from PyInstaller first)
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef DistDir
  #define DistDir "..\dist"
#endif

[Setup]
AppId={{6B1C2E4A-7D53-4F0B-9A2E-3C8F5D1E7A42}
AppName=GuideWire
AppVersion={#AppVersion}
AppVerName=GuideWire {#AppVersion}
AppPublisher=GuideWire (FAST-NUCES Karachi, final year project)
; Per-user install by default (no administrator rights, works on shared lab PCs); the wizard offers "for all users" when run as administrator.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\GuideWire
DefaultGroupName=GuideWire
DisableProgramGroupPage=yes
OutputDir={#DistDir}
OutputBaseFilename=GuideWire-Setup-{#AppVersion}
Compression=lzma2/ultra
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
WizardStyle=modern
UninstallDisplayName=GuideWire {#AppVersion}
UninstallDisplayIcon={app}\GuideWire.exe
CloseApplications=yes
RestartApplications=no
InfoAfterFile=README-integrations.txt
SetupIconFile=guidewire.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#DistDir}\GuideWire\*"; DestDir: "{app}"; Excludes: "__pycache__,*.pyc"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\GuideWire"; Filename: "{app}\GuideWire.exe"
Name: "{group}\GuideWire integrations (Blender, Maya, Houdini)"; Filename: "{app}\_internal\integrations"
Name: "{group}\Uninstall GuideWire"; Filename: "{uninstallexe}"
Name: "{autodesktop}\GuideWire"; Filename: "{app}\GuideWire.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\GuideWire.exe"; Description: "Start GuideWire"; Flags: nowait postinstall skipifsilent

[Code]
// The learner's tutorials, progress, keys and logs live in %LOCALAPPDATA%\GuideWire, outside the install folder. Uninstalling removes the program but
// keeps that folder unless the learner says otherwise, so a reinstall or an upgrade never loses their work. A silent uninstall always keeps it.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\GuideWire');
    if (not UninstallSilent) and DirExists(DataDir) then
      if MsgBox('Also delete your GuideWire data (saved tutorials, progress, API keys, logs)?' + #13#10 + #13#10 + DataDir + #13#10 + #13#10 +
                'Choose No to keep it for a later reinstall.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
