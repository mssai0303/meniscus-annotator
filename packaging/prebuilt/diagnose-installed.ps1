# Diagnostic only: install the already built, verified candidate unchanged.
[CmdletBinding()]
param([string]$Root = 'C:\D\Diagnostic')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
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
$env:MENISCUS_TEST_AUTOCLOSE = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$Results = @()
foreach ($Where in @('repository','installed')) {
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
import importlib, json, os, sys, traceback
from pathlib import Path
import qt, slicer
result = {'application_name': str(slicer.app.applicationName),
          'generic_data': qt.QStandardPaths.writableLocation(qt.QStandardPaths.GenericDataLocation),
          'local_app_data_env': os.environ.get('LOCALAPPDATA'),
          'slicerrc': os.environ.get('SLICERRC'), 'cwd': str(Path.cwd()),
          'sys_path': [str(p) for p in sys.path], 'imports': {}}
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
Path(os.environ['MENISCUS_DIAGNOSTIC_OUTPUT']).write_text(json.dumps(result, indent=2), encoding='utf-8')
slicer.app.exit(0)
'@ | Set-Content -Encoding UTF8 $Probe
$env:MENISCUS_DIAGNOSTIC_OUTPUT = Join-Path $Evidence 'runtime-probe.json'
$ProbeProcess = Start-Process -FilePath (Join-Path $Installed 'MeniscusAnnotatorExamples.exe') -ArgumentList @('--ignore-slicerrc','--python-script',"`"$Probe`"") -WorkingDirectory $Installed -RedirectStandardOutput (Join-Path $Evidence 'probe.stdout.txt') -RedirectStandardError (Join-Path $Evidence 'probe.stderr.txt') -PassThru
$ProbeExited = $ProbeProcess.WaitForExit(45000)
if (-not $ProbeExited) { $ProbeProcess.Kill($true); $ProbeProcess.WaitForExit() }
$Results += [ordered]@{action='diagnostic_probe';exited=$ProbeExited;exit_code=$ProbeProcess.ExitCode}
$Results | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 (Join-Path $Evidence 'processes.json')
$PossibleRoots = @((Join-Path $env:LOCALAPPDATA 'Meniscus Annotator synthetic tests'))
if (Test-Path $env:MENISCUS_DIAGNOSTIC_OUTPUT) {
  $ProbeData = Get-Content -Raw $env:MENISCUS_DIAGNOSTIC_OUTPUT | ConvertFrom-Json
  $PossibleRoots += (Join-Path $ProbeData.generic_data 'Meniscus Annotator synthetic tests')
  if (($ProbeData.PSObject.Properties.Name -contains 'error_log_file') -and $ProbeData.error_log_file -and (Test-Path -LiteralPath $ProbeData.error_log_file)) { Copy-Item -LiteralPath $ProbeData.error_log_file -Destination (Join-Path $Evidence 'probe-application-log.txt') }
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
