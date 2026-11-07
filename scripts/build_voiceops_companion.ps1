param(
    [Parameter(Mandatory)] [string] $NemoArchive,
    [Parameter(Mandatory)] [string] $PystraySourceArchive,
    [Parameter(Mandatory)] [string] $Iscc,
    [Parameter(Mandatory)] [string] $OutputDirectory,
    [Parameter(Mandatory)] [ValidatePattern('^\d+\.\d+\.\d+$')] [string] $Version,
    [string] $PythonExe = 'python',
    [switch] $SmokeBuild
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$nemoHash = 'A43F373BD78B2B4AB90167BC838C6C4C7F1A0AE526BFB3BC237E46B01165C8DE'
$pystrayRevision = '1907f8681d6d421517c63d94f425f9cdd74d0034'
# Original pystray 0.19.5 source: https://codeload.github.com/moses-palmer/pystray/zip/1907f8681d6d421517c63d94f425f9cdd74d0034
$pystraySourceHash = '4751562BA90301E054C87606079C1599301D84E7D1E4074B12AF4F54A80A4768'
if ((Get-FileHash -LiteralPath $NemoArchive -Algorithm SHA256).Hash -ne $nemoHash) { throw 'Unexpected NeMo archive' }
if ((Get-FileHash -LiteralPath $PystraySourceArchive -Algorithm SHA256).Hash -ne $pystraySourceHash) { throw 'Unexpected pystray source archive' }
if (Test-Path -LiteralPath $OutputDirectory) { throw 'Use a new output directory' }
$output = (New-Item -ItemType Directory -Path $OutputDirectory).FullName
$work = Join-Path $output 'work'
$assets = Join-Path $work 'assets'
New-Item -ItemType Directory -Path $assets | Out-Null
Expand-Archive -LiteralPath $NemoArchive -DestinationPath (Join-Path $work 'nemo')
Expand-Archive -LiteralPath $PystraySourceArchive -DestinationPath (Join-Path $work 'pystray')
$nemoRoot = Join-Path $work 'nemo/nemo-speech-nightly-windows-x86_64-cpu'
$pystrayRoot = Join-Path $work "pystray/pystray-$pystrayRevision"
Copy-Item -LiteralPath (Join-Path $nemoRoot 'bin') -Destination (Join-Path $assets 'nemo') -Recurse
Copy-Item -LiteralPath (Join-Path $nemoRoot 'share') -Destination (Join-Path $assets 'nemo-notices') -Recurse
Add-Type -AssemblyName System.Speech
$voice = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
    $voice.SetOutputToWaveFile((Join-Path $assets 'probe.wav'))
    $voice.Speak('This is a synthetic Voice Ops Studio recording. The quick brown fox jumps over the lazy dog. The session is ready for transcription.')
} finally {
    $voice.Dispose()
}
$dist = Join-Path $work 'dist'
& $PythonExe -m PyInstaller --noconfirm --onedir --windowed --noupx --name VoiceOpsCompanion --contents-directory _internal --distpath $dist --workpath (Join-Path $work 'build') --specpath $work --exclude-module pystray --hidden-import six --copy-metadata pillow --copy-metadata six --copy-metadata pyinstaller (Join-Path $PSScriptRoot 'voiceops_companion.py')
if ($LASTEXITCODE -ne 0) { throw 'Python application packaging failed' }
$bundle = Join-Path $dist 'VoiceOpsCompanion'
$internal = Join-Path $bundle '_internal'
Copy-Item -LiteralPath $assets -Destination (Join-Path $internal 'voiceops-tools') -Recurse
# Keep the unmodified library replaceable by the installed user, outside the frozen archive.
Copy-Item -LiteralPath (Join-Path $pystrayRoot 'lib/pystray') -Destination $internal -Recurse
$notices = New-Item -ItemType Directory -Path (Join-Path $internal 'licenses')
Copy-Item -LiteralPath $PystraySourceArchive -Destination (Join-Path $notices.FullName 'pystray-0.19.5-source.zip')
Copy-Item -LiteralPath (Join-Path $pystrayRoot 'COPYING') -Destination (Join-Path $notices.FullName 'pystray-GPL.txt')
Copy-Item -LiteralPath (Join-Path $pystrayRoot 'COPYING.LGPL') -Destination (Join-Path $notices.FullName 'pystray-LGPL.txt')
$pythonHome = & $PythonExe -c 'import sys; print(sys.base_prefix)'
if ($LASTEXITCODE -ne 0) { throw 'Could not locate the CPython license' }
Copy-Item -LiteralPath (Join-Path $pythonHome 'LICENSE.txt') -Destination (Join-Path $notices.FullName 'CPython-LICENSE.txt')
$compilerArgs = @("/DBundleRoot=$bundle", "/DOutputRoot=$output", "/DAppVersion=$Version")
if ($SmokeBuild) { $compilerArgs += '/DSmokeBuild=1' }
& $Iscc @compilerArgs (Join-Path $root 'deploy/companion/voiceops-companion.iss')
if ($LASTEXITCODE -ne 0) { throw 'Setup build failed' }
$setup = Get-Item -LiteralPath (Join-Path $output 'VoiceOpsCompanion-Setup.exe')
$commit = git -C $root rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'Could not identify source revision' }
[ordered]@{version=$Version; source_commit=$commit; source_dirty=[bool](git -C $root status --porcelain); smoke=[bool]$SmokeBuild; file=$setup.Name; bytes=$setup.Length; sha256=(Get-FileHash -LiteralPath $setup.FullName -Algorithm SHA256).Hash.ToLowerInvariant()} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output 'installer.json') -Encoding utf8
Write-Output $setup.FullName
