[Setup]
#ifdef SmokeBuild
AppId={{4C0D3DAD-8A21-44E3-BA05-117A9BA1359C}
AppName=VoiceOps Studio Companion Smoke
CreateUninstallRegKey=no
#else
AppId={{6C6529E1-5923-44BF-95AB-03E70857674F}
AppName=VoiceOps Studio Companion
#endif
AppVersion={#AppVersion}
AppPublisher=VoiceOps Studio
DefaultDirName={localappdata}\Programs\VoiceOps Studio Companion
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
AppMutex=Local\VoiceOpsStudioCompanion
CloseApplications=no
Compression=lzma2
SolidCompression=yes
OutputDir={#OutputRoot}
OutputBaseFilename=VoiceOpsCompanion-Setup

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Files]
Source: "{#BundleRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\VoiceOps Studio Companion"; Filename: "{app}\VoiceOpsCompanion.exe"

[Run]
Filename: "{app}\VoiceOpsCompanion.exe"; Description: "Запустить локальный обработчик"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\VoiceOpsCompanion.exe"; Parameters: "--disable-autostart"; Flags: runhidden; RunOnceId: "DisableVoiceOpsAutostart"
