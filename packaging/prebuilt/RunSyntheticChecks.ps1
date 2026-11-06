# Optional maintainer convenience. No admin, execution-policy changes or downloads.
[CmdletBinding()]
param([ValidateSet('create','workflow','resume')][string]$Action = 'workflow')
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Names = @{create='MeniscusAnnotatorExamples.exe';workflow='MeniscusAnnotatorChecks.exe';resume='MeniscusAnnotatorResumeCheck.exe'}
$App = Join-Path $Root $Names[$Action]
if (-not (Test-Path -LiteralPath $App)) { throw 'The installed synthetic test launcher is missing. Reinstall the fixed application version.' }
$Process = Start-Process -FilePath $App -PassThru -Wait
if ($Process.ExitCode -ne 0) { throw 'Synthetic check did not complete. Inspect the result folder shown by the application.' }
