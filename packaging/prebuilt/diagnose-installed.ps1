# Diagnostic only: install the already built, verified candidate unchanged.
[CmdletBinding()]
param([string]$Root = 'C:\D\Diagnostic', [switch]$RepairTestLauncher, [switch]$DiagnosticTestHomeModule)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$DiagnosticStarted = Get-Date
$Evidence = Join-Path $Root 'evidence'
New-Item -ItemType Directory -Force $Evidence | Out-Null
$Installer = Join-Path $Root 'download\MeniscusAnnotator-0.1.0-Windows-x64.exe'
$Expected = '370b1a146633016b8196ef3c5ef3f9476073a24f0815f02443e5725a5447e5cc'
if ((Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLower() -ne $Expected) { throw 'Candidate checksum differs; nothing was installed.' }
$Installed = Join-Path $Root 'Installed with spaces'
$Install = Start-Process -FilePath $Installer -ArgumentList @('/S',"/D=$Installed") -Wait -PassThru
if ($Install.ExitCode -ne 0) { throw 'Candidate installation failed.' }
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
python (Join-Path $PSScriptRoot 'verify-installed.py') $Installed
if ($LASTEXITCODE -ne 0) { throw 'Installed byte verification failed.' }
Copy-Item (Join-Path $Installed 'BUILD-IDENTITY.json') $Evidence
Copy-Item (Join-Path $Installed 'bin\MeniscusAnnotatorExamplesLauncherSettings.ini') $Evidence
if ($RepairTestLauncher) {
  # Diagnostic addition only. No existing installed byte is modified. The
  # future assembler creates this canonical pair alongside the action aliases.
  Copy-Item (Join-Path $Installed 'MeniscusAnnotatorChecks.exe') (Join-Path $Installed 'MeniscusAnnotatorTest.exe')
  $CanonicalTestIni = (Get-Content -Raw (Join-Path $Installed 'bin\MeniscusAnnotatorChecksLauncherSettings.ini')) -replace '(?m)^MENISCUS_TEST_ACTION=.*\r?\n', ''
  $CanonicalTestIni | Set-Content -Encoding UTF8 (Join-Path $Installed 'bin\MeniscusAnnotatorTestLauncherSettings.ini')
  [ordered]@{scope='Ephemeral diagnostic additions; original candidate installer is NOT repaired';added_files=@('MeniscusAnnotatorTest.exe','bin/MeniscusAnnotatorTestLauncherSettings.ini')} | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $Evidence 'diagnostic-repair.json')
}
if ($DiagnosticTestHomeModule) {
  # A single explicitly recorded ephemeral variation; application/executable
  # bytes stay unchanged. Keep the separate MeniscusAnnotatorTest profile.
  $TestDefaults = Join-Path $Installed 'share\Slicer-5.12\MeniscusAnnotatorTestDefaultSettings.ini'
  $BeforeHomeHash = (Get-FileHash -LiteralPath $TestDefaults -Algorithm SHA256).Hash.ToLower()
  $DefaultsText = Get-Content -Raw $TestDefaults
  if ($DefaultsText -notmatch '(?m)^HomeModule=\r?$') { throw 'Unexpected starting Test HomeModule setting; no variation applied.' }
  $DefaultsText = $DefaultsText -replace '(?m)^HomeModule=\r?$', 'HomeModule=MeniscusAnnotator'
  [IO.File]::WriteAllText($TestDefaults, $DefaultsText, [Text.UTF8Encoding]::new($false))
  $AfterHomeHash = (Get-FileHash -LiteralPath $TestDefaults -Algorithm SHA256).Hash.ToLower()
  [ordered]@{scope='Ephemeral diagnostic hypothesis only; original candidate installer and application source are unchanged';relative_file='share/Slicer-5.12/MeniscusAnnotatorTestDefaultSettings.ini';original_sha256=$BeforeHomeHash;modified_sha256=$AfterHomeHash;setting='HomeModule';before='';after='MeniscusAnnotator';settings_profile='MeniscusAnnotatorTest'} | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $Evidence 'diagnostic-test-home-module.json')
  Copy-Item -LiteralPath $TestDefaults -Destination $Evidence
}
$env:MENISCUS_TEST_AUTOCLOSE = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$Results = @()
$Locations = if ($RepairTestLauncher) { @('installed') } else { @('repository','installed') }
foreach ($Where in $Locations) {
  $Working = if ($Where -eq 'repository') { $Repo } else { $Installed }
  $env:MENISCUS_TEST_RUN_ID = [Guid]::NewGuid().ToString('N')
  $Out = Join-Path $Evidence "create-$Where.stdout.txt"
  $Err = Join-Path $Evidence "create-$Where.stderr.txt"
  $Child = Start-Process -FilePath (Join-Path $Installed 'MeniscusAnnotatorExamples.exe') -WorkingDirectory $Working -RedirectStandardOutput $Out -RedirectStandardError $Err -PassThru
  $Exited = $Child.WaitForExit(45000)
  if (-not $Exited) { $Child.Kill($true); $Child.WaitForExit() }
  $Results += [ordered]@{action='original_create';working_directory=$Where;run_id=$env:MENISCUS_TEST_RUN_ID;exited=$Exited;exit_code=$Child.ExitCode}
}
# Probe the same executable/profile with a separate diagnostic script. The
# installed application/TestKit files are never replaced or changed.
$Probe = Join-Path $Evidence 'runtime-probe.py'
@'
import os
from pathlib import Path
output = Path(os.environ['MENISCUS_DIAGNOSTIC_OUTPUT'])
output.with_suffix('.started.txt').write_text('Python entry reached\n', encoding='utf-8')
import importlib, json, sys, traceback
result = {}
try:
    import qt, slicer
    result = {'application_name': str(slicer.app.applicationName),
              'generic_data': qt.QStandardPaths.writableLocation(qt.QStandardPaths.GenericDataLocation),
              'local_app_data_env': os.environ.get('LOCALAPPDATA'),
              'slicerrc': os.environ.get('SLICERRC'), 'action': os.environ.get('MENISCUS_TEST_ACTION'), 'cwd': str(Path.cwd()),
              'sys_path': [str(p) for p in sys.path], 'imports': {},
              'settings_file': str(slicer.app.userSettings().fileName()),
              'temporary_path': str(slicer.app.temporaryPath),
              'runtime_environment': {k: os.environ.get(k) for k in ('PATH','PYTHONPATH','PYTHONHOME','QT_PLUGIN_PATH','SLICER_HOME','ITK_AUTOLOAD_PATH','SSL_CERT_FILE','PYTHONNOUSERSITE','PYTHONUTF8','SLICERRC')}}
    for name in ('MeniscusAnnotator', 'MeniscusAnnotatorLib'):
        try:
            module = importlib.import_module(name)
            result['imports'][name] = {'path': module.__file__, 'source_identity': getattr(module, 'SOURCE_IDENTITY', None)}
        except Exception:
            result['imports'][name] = {'error': traceback.format_exc()}
    try:
        model = slicer.app.errorLogModel()
        result['error_log_file'] = str(model.filePath) if hasattr(model, 'filePath') else None
    except Exception:
        result['error_log_error'] = traceback.format_exc()
except Exception:
    result['error'] = traceback.format_exc()
finally:
    output.write_text(json.dumps(result, indent=2), encoding='utf-8')
try:
    slicer.app.exit(1 if 'error' in result else 0)
except Exception:
    output.with_suffix('.exit-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
'@ | Set-Content -Encoding UTF8 $Probe
$ProbeEntries = [ordered]@{normal='MeniscusAnnotator.exe';test_alias='MeniscusAnnotatorExamples.exe'}
if ($RepairTestLauncher) { $ProbeEntries['test_canonical'] = 'MeniscusAnnotatorTest.exe' }
foreach ($Label in $ProbeEntries.Keys) {
  $env:MENISCUS_DIAGNOSTIC_OUTPUT = Join-Path $Evidence "runtime-probe-$Label.json"
  $ProbeArguments = @('--no-main-window','--testing','--disable-message-handlers','--python-script',"`"$Probe`"")
  $ProbeProcess = Start-Process -FilePath (Join-Path $Installed $ProbeEntries[$Label]) -ArgumentList $ProbeArguments -WorkingDirectory $Installed -RedirectStandardOutput (Join-Path $Evidence "probe-$Label.stdout.txt") -RedirectStandardError (Join-Path $Evidence "probe-$Label.stderr.txt") -PassThru
  $ProbeExited = $ProbeProcess.WaitForExit(30000)
  if (-not $ProbeExited) { $ProbeProcess.Kill($true); $ProbeProcess.WaitForExit() }
  $Results += [ordered]@{action="diagnostic_probe_$Label";exited=$ProbeExited;exit_code=$ProbeProcess.ExitCode}
}
# Run the exact same native TestApp-real bytes with the environment produced by
# the known normal launcher. This reveals its native exit code instead of only
# the CTK launcher's generic exit 1. No application or launcher byte is changed.
$NormalProbe = Join-Path $Evidence 'runtime-probe-normal.json'
if ($RepairTestLauncher -and (Test-Path $NormalProbe)) {
  $Normal = Get-Content -Raw $NormalProbe | ConvertFrom-Json
  if (($Normal.PSObject.Properties.Name -contains 'runtime_environment') -and $null -ne $Normal.runtime_environment) {
  $SavedEnvironment = @{}
  try {
    foreach ($Property in $Normal.runtime_environment.PSObject.Properties) {
      $SavedEnvironment[$Property.Name] = [Environment]::GetEnvironmentVariable($Property.Name,'Process')
      [Environment]::SetEnvironmentVariable($Property.Name,$Property.Value,'Process')
    }
    $env:MENISCUS_DIAGNOSTIC_OUTPUT = Join-Path $Evidence 'runtime-probe-test_direct.json'
    $Native = Start-Process -FilePath (Join-Path $Installed 'bin\MeniscusAnnotatorTestApp-real.exe') -ArgumentList @('--no-main-window','--testing','--disable-message-handlers','--python-script',"`"$Probe`"") -WorkingDirectory $Installed -RedirectStandardOutput (Join-Path $Evidence 'probe-test_direct.stdout.txt') -RedirectStandardError (Join-Path $Evidence 'probe-test_direct.stderr.txt') -PassThru
    $Exited = $Native.WaitForExit(30000)
    if (-not $Exited) { $Native.Kill($true); $Native.WaitForExit() }
    $Results += [ordered]@{action='native_test_with_normal_environment';exited=$Exited;exit_code=$Native.ExitCode}
  } finally {
    foreach ($Name in $SavedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($Name,$SavedEnvironment[$Name],'Process') }
  }
  } else {
    $Results += [ordered]@{action='native_test_with_normal_environment';skipped=$true;reason='Normal probe did not reach runtime environment capture; inspect its sentinel and JSON error.'}
  }
}
$CreatedReport = Join-Path (Join-Path (Join-Path $env:LOCALAPPDATA 'Meniscus Annotator synthetic tests') $env:MENISCUS_TEST_RUN_ID) 'installed-tests.json'
$CreatedPassed = (Test-Path $CreatedReport) -and (Get-Content -Raw $CreatedReport | ConvertFrom-Json).passed
if ($RepairTestLauncher -and $CreatedPassed) {
  foreach ($Action in @('correction','correction-resume')) {
    $Entry = if ($Action -eq 'correction') { 'MeniscusAnnotatorCorrectionChecks.exe' } else { 'MeniscusAnnotatorCorrectionResumeCheck.exe' }
    $env:MENISCUS_TEST_RUN_ID = [Guid]::NewGuid().ToString('N')
    $Child = Start-Process -FilePath (Join-Path $Installed $Entry) -WorkingDirectory $Installed -RedirectStandardOutput (Join-Path $Evidence "$Action.stdout.txt") -RedirectStandardError (Join-Path $Evidence "$Action.stderr.txt") -PassThru
    $Exited = $Child.WaitForExit(60000)
    if (-not $Exited) { $Child.Kill($true); $Child.WaitForExit() }
    $Results += [ordered]@{action=$Action;diagnostic_repair=$true;run_id=$env:MENISCUS_TEST_RUN_ID;exited=$Exited;exit_code=$Child.ExitCode}
  }
}
$Results | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 (Join-Path $Evidence 'processes.json')
try {
  Get-WinEvent -FilterHashtable @{LogName='Application';StartTime=$DiagnosticStarted} -ErrorAction Stop |
    Where-Object { $_.ProviderName -in @('Application Error','Windows Error Reporting','.NET Runtime') -and $_.Message -match 'Meniscus|Slicer' } |
    Select-Object TimeCreated,Id,ProviderName,Message |
    ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $Evidence 'windows-application-events.json')
} catch {
  $_.Exception.Message | Set-Content -Encoding UTF8 (Join-Path $Evidence 'windows-events-unavailable.txt')
}
$PossibleRoots = @((Join-Path $env:LOCALAPPDATA 'Meniscus Annotator synthetic tests'))
foreach ($ProbeReceipt in (Get-ChildItem $Evidence -Filter 'runtime-probe-*.json' -File)) {
  $ProbeData = Get-Content -Raw $ProbeReceipt.FullName | ConvertFrom-Json
  if ($ProbeData.PSObject.Properties.Name -contains 'generic_data') { $PossibleRoots += (Join-Path $ProbeData.generic_data 'Meniscus Annotator synthetic tests') }
  if (($ProbeData.PSObject.Properties.Name -contains 'error_log_file') -and $ProbeData.error_log_file -and (Test-Path -LiteralPath $ProbeData.error_log_file)) { Copy-Item -LiteralPath $ProbeData.error_log_file -Destination (Join-Path $Evidence ($ProbeReceipt.BaseName + '-application-log.txt')) }
}
foreach ($Folder in ($PossibleRoots | Select-Object -Unique)) {
  if (Test-Path -LiteralPath $Folder) {
    Get-ChildItem -LiteralPath $Folder -Recurse -File -Filter '*.json' | ForEach-Object {
      $Relative = [IO.Path]::GetRelativePath($Folder, $_.FullName)
      $Destination = Join-Path (Join-Path $Evidence 'synthetic-reports') $Relative
      New-Item -ItemType Directory -Force (Split-Path -Parent $Destination) | Out-Null
      Copy-Item -LiteralPath $_.FullName -Destination $Destination
    }
  }
}
Write-Output 'Diagnostic collection complete. This does not mark any annotation workflow accepted.'
