; Inno Setup 6 Script for Egyptian Pharma Procurement Optimizer
#define MyAppName "Egyptian Pharma Procurement Optimizer"
#define MyAppArabicName "نظام المشتريات الصيدلانية"
#define MyAppVersion "2.7.1"
#ifndef AppBuildDir
  #define AppBuildDir "dist\EgyptianPharmaOptimizer"
#endif
#ifndef SetupCompression
  #define SetupCompression "lzma2/ultra64"
#endif
#define MyAppPublisher "Pharma Tech Solutions"
#define MyAppExeName "EgyptianPharmaOptimizer.exe"

[Setup]
AppId={{D3E4F5A6-1234-4567-89AB-CDEF01234567}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\EgyptianPharmaOptimizer
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=dist_installer
OutputBaseFilename=EgyptianPharmaOptimizer_Setup_v{#MyAppVersion}
SetupIconFile=assets\app.ico
Compression={#SetupCompression}
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
RestartApplications=yes
DisableProgramGroupPage=yes
UsePreviousAppDir=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#AppBuildDir}\*"; DestDir: "{app}"; Excludes: "*.bak,*.db-wal,*.db-shm"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\*"; DestDir: "{app}\assets"; Excludes: "*.bak"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "data\*"; DestDir: "{app}\data"; Excludes: "*.bak,*.db-wal,*.db-shm"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\app.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\assets\app.ico"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall
