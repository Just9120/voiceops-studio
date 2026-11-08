#define FfmpegArchive "ffmpeg-8.1.2-full_build.zip"
#define FfmpegDirectory "ffmpeg-8.1.2-full_build"
#define FfmpegSHA256 "b8cdefab5f50590a076c27c2b56b0294a0e6154faded28ba1ba05ebc4f801f57"
#define FfmpegSource "https://github.com/GyanD/codexffmpeg/releases/download/8.1.2/" + FfmpegArchive

[Setup]
#ifdef SmokeBuild
AppId={{4C0D3DAD-8A21-44E3-BA05-117A9BA1359C}
AppName=VoiceOps Studio Companion Smoke
CreateUninstallRegKey=no
Uninstallable=no
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
ArchiveExtraction=full
OutputDir={#OutputRoot}
OutputBaseFilename=VoiceOpsCompanion-Setup

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Files]
Source: "{#BundleRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{tmp}\{#FfmpegDirectory}\bin\ffmpeg.exe"; DestDir: "{app}\_internal\voiceops-tools"; ExternalSize: 242496512; Flags: external ignoreversion
Source: "{tmp}\{#FfmpegDirectory}\bin\ffprobe.exe"; DestDir: "{app}\_internal\voiceops-tools"; ExternalSize: 242291712; Flags: external ignoreversion
Source: "{tmp}\{#FfmpegDirectory}\LICENSE"; DestDir: "{app}\_internal\voiceops-tools"; DestName: "FFmpeg-LICENSE.txt"; ExternalSize: 35147; Flags: external ignoreversion
Source: "{tmp}\{#FfmpegDirectory}\README.txt"; DestDir: "{app}\_internal\voiceops-tools"; DestName: "FFmpeg-README.txt"; ExternalSize: 45280; Flags: external ignoreversion

#ifndef SmokeBuild
[Icons]
Name: "{autoprograms}\VoiceOps Studio Companion"; Filename: "{app}\VoiceOpsCompanion.exe"

[Run]
Filename: "{app}\VoiceOpsCompanion.exe"; Description: "Запустить локальный обработчик"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\VoiceOpsCompanion.exe"; Parameters: "--disable-autostart"; Flags: runhidden; RunOnceId: "DisableVoiceOpsAutostart"
#endif

[Code]
var
  DownloadPage: TDownloadWizardPage;
  ExtractionPage: TExtractionWizardPage;
  FfmpegPrepared: Boolean;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage('Загрузка FFmpeg',
    'Установщик скачивает FFmpeg с GitHub дистрибьютора Gyan и проверяет контрольную сумму.', nil);
  DownloadPage.ShowBaseNameInsteadOfUrl := True;
  ExtractionPage := CreateExtractionPage('Подготовка FFmpeg', 'Распаковываем проверенный архив.', nil);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if FfmpegPrepared then
    Exit;
  try
    DownloadPage.Clear;
    DownloadPage.Add('{#FfmpegSource}', '{#FfmpegArchive}', '{#FfmpegSHA256}');
    DownloadPage.Show;
    try
      DownloadPage.Download;
    finally
      DownloadPage.Hide;
    end;
    ExtractionPage.Clear;
    ExtractionPage.Add(ExpandConstant('{tmp}\{#FfmpegArchive}'), ExpandConstant('{tmp}'), True);
    ExtractionPage.Show;
    try
      ExtractionPage.Extract;
    finally
      ExtractionPage.Hide;
    end;
    FfmpegPrepared := True;
  except
    Log('FFmpeg preparation failed: ' + GetExceptionMessage);
    Result := 'Не удалось подготовить FFmpeg. Проверьте доступ к GitHub и свободное место, затем повторите установку.';
  end;
end;
