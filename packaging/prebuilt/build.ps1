# Build a real NSIS installer around the official prebuilt Slicer runtime.
# Maintainer-only; requires PowerShell 7 and Python 3.9+, not a Slicer superbuild.
[CmdletBinding()]
param([string]$BuildRoot = 'C:\D\MP', [switch]$TestInstall, [switch]$RunIntegration, [switch]$FastPackage)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT') { throw 'Use a Windows x64 build host for this script.' }
if ($BuildRoot -match ' ') { throw 'Choose a build directory without spaces for build tooling. Installed runtime paths may contain spaces.' }
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Git = (Get-Command git.exe -ErrorAction Stop).Source
$sourceStatus = & $Git -C $Repo status --porcelain --untracked-files=normal
if ($LASTEXITCODE -ne 0 -or $sourceStatus) { throw 'Use a clean recorded source checkout before downloading or packaging.' }
$Lock = Get-Content -Raw (Join-Path $PSScriptRoot 'dependencies.json') | ConvertFrom-Json
$Python = (Get-Command python.exe -ErrorAction Stop).Source
# Keep the maintainer interpreter consistent with the bundled runtime's UTF-8 mode.
$env:PYTHONUTF8 = '1'
function Checked([string]$Exe, [string[]]$Arguments) {
  & $Exe @Arguments
  if ($LASTEXITCODE -ne 0) { throw "$Exe failed with exit $LASTEXITCODE" }
}
function Download-Locked($Item, [string]$File, [string]$Algorithm = 'SHA256') {
  $expected = if ($Algorithm -eq 'SHA512') { $Item.sha512 } else { $Item.sha256 }
  if ((Test-Path $File) -and (Get-FileHash $File -Algorithm $Algorithm).Hash.ToLower() -eq $expected) { return }
  $urls = @($Item.url)
  if ($Item.PSObject.Properties.Name -contains 'fallback_urls') { $urls += $Item.fallback_urls }
  $Curl = (Get-Command curl.exe -ErrorAction Stop).Source
  foreach ($url in $urls) {
    $pending = "$File.pending"
    & $Curl --fail --location --silent --show-error --retry 3 --connect-timeout 30 --max-time 300 --output $pending --url $url
    $downloadExit = $LASTEXITCODE
    $actual = if (Test-Path $pending) { (Get-FileHash $pending -Algorithm $Algorithm).Hash.ToLower() } else { 'no-file' }
    $bytes = if (Test-Path $pending) { (Get-Item $pending).Length } else { 0 }
    $accepted = $downloadExit -eq 0 -and $actual -eq $expected
    $record = [ordered]@{file=(Split-Path -Leaf $File);url=$url;exit=$downloadExit;bytes=$bytes;algorithm=$Algorithm;actual=$actual;expected=$expected;accepted=$accepted}
    Add-Content -Encoding UTF8 -Path (Join-Path $BuildRoot 'download-receipts.jsonl') -Value ($record | ConvertTo-Json -Compress)
    if ($accepted) { Move-Item -Force $pending $File; return }
    Write-Warning "Rejected dependency $(Split-Path -Leaf $File): bytes=$bytes, actual=$actual; expected=$expected. Trying the next locked source, if available."
    if (Test-Path $pending) { Remove-Item -LiteralPath $pending }
  }
  throw "No verified download obtained for $(Split-Path -Leaf $File). Check download-receipts.jsonl; the hash requirement was not relaxed."
}
if (Test-Path (Join-Path $BuildRoot 'Payload')) { throw 'Choose a fresh build folder; existing payloads are preserved.' }
New-Item -ItemType Directory -Force $BuildRoot | Out-Null
$Downloads = Join-Path $BuildRoot 'downloads'
New-Item -ItemType Directory -Force $Downloads | Out-Null
$SlicerInstaller = Join-Path $Downloads 'Slicer-5.12.4-win-amd64.exe'
$SevenInstaller = Join-Path $Downloads '7z2605-x64.exe'
$NsisZip = Join-Path $Downloads 'nsis-3.13.zip'
Download-Locked $Lock.slicer $SlicerInstaller SHA512
Download-Locked $Lock.sevenzip $SevenInstaller
Download-Locked $Lock.nsis $NsisZip
$SevenRoot = Join-Path $BuildRoot '7zip'
$SevenProcess = Start-Process -FilePath $SevenInstaller -ArgumentList @('/S',"/D=$SevenRoot") -Wait -PassThru
if ($SevenProcess.ExitCode -ne 0) { throw 'Pinned 7-Zip tooling installation failed.' }
$Seven = Join-Path $SevenRoot '7z.exe'
$Extracted = Join-Path $BuildRoot 'extracted'
Checked $Seven @('x','-y',"-o$Extracted",$SlicerInstaller)
Expand-Archive -Path $NsisZip -DestinationPath (Join-Path $BuildRoot 'tools') -Force
$Nsis = Join-Path $BuildRoot 'tools\nsis-3.13\makensis.exe'
$Payload = Join-Path $BuildRoot 'Payload'
Checked $Python @((Join-Path $PSScriptRoot 'prepare.py'),'--runtime-extracted',$Extracted,
  '--installer',$SlicerInstaller,'--output',$Payload,'--cache',$Downloads)
$Distribution = Get-Content -Raw (Join-Path $Payload 'distribution.json') | ConvertFrom-Json
if ($Distribution.application_source_dirty -or $Distribution.application_commit -eq 'unrecorded-local-source') {
  throw 'Installer builds require a clean recorded source commit. Commit the reviewed source before packaging.'
}
$Output = Join-Path $BuildRoot 'MeniscusAnnotator-0.1.0-Windows-x64.exe'
$NsisArguments = @('/V2',"/DPAYLOAD=$Payload","/DOUTPUT=$Output",
  "/DUNINSTALL_FILES=$(Join-Path $BuildRoot 'uninstall-files.nsh')",
  "/DLICENSE_FILE=$(Join-Path $Repo 'LICENSE')")
if ($FastPackage) { $NsisArguments += '/DFAST_PACKAGE' }
$NsisArguments += (Join-Path $PSScriptRoot 'installer.nsi')
Checked $Nsis $NsisArguments
$receipt = [ordered]@{
  schema_version='meniscus_installer_build/1'; route=$Lock.route; app_version='0.1.0'
  runner_os=[Environment]::OSVersion.VersionString; runner_image=$env:ImageVersion
  runtime_download_sha512=$Lock.slicer.sha512
  application_commit=$Distribution.application_commit
  application_source_sha256=$Distribution.application_source_sha256
  application_source_dirty=$Distribution.application_source_dirty
  compression_mode=$(if ($FastPackage) { 'zlib-development-fast' } else { 'solid-lzma' })
  installer_filename=(Split-Path -Leaf $Output); installer_bytes=(Get-Item $Output).Length
  installer_sha256=(Get-FileHash $Output -Algorithm SHA256).Hash.ToLower()
  nsis='3.13'; sevenzip='26.05'; install_test='NOT RUN'; runtime_import_test='NOT RUN'
  synthetic_desktop_test='NOT RUN'; synthetic_correction_test='NOT RUN'; synthetic_correction_resume_test='NOT RUN'
  Windows11_interactive_acceptance='NOT RUN'; Horizon_Windows10_19045_acceptance='NOT RUN'
}
try {
if ($TestInstall) {
  # Private ephemeral build host only. No MRI data enter this workflow.
  $Installed = Join-Path $BuildRoot 'Installed with spaces'
  $process = Start-Process -FilePath $Output -ArgumentList @('/S',"/D=$Installed") -Wait -PassThru
  if ($process.ExitCode -ne 0) { throw 'Installer execution failed.' }
  Checked $Python @((Join-Path $PSScriptRoot 'verify-installed.py'),$Installed)
  $receipt['install_test']='PASSED: installed bytes match the complete payload manifest'
  $SecondInstalled = Join-Path $BuildRoot 'Duplicate installation attempt'
  $second = Start-Process -FilePath $Output -ArgumentList @('/S',"/D=$SecondInstalled") -Wait -PassThru
  if (Test-Path (Join-Path $SecondInstalled 'MeniscusAnnotator.exe')) { throw 'A duplicate fixed-version installation was incorrectly accepted.' }
  Checked $Python @((Join-Path $PSScriptRoot 'verify-installed.py'),$Installed)
  $receipt['duplicate_install_test']='PASSED: second registered installation rejected; original installed files retained'
  $env:MENISCUS_PACKAGE_CHECK = Join-Path $BuildRoot 'installed-runtime-check.json'
  $env:PYTHONDONTWRITEBYTECODE = '1'
  $app = Start-Process -FilePath (Join-Path $Installed 'MeniscusAnnotator.exe') -ArgumentList @('--no-main-window') -PassThru
  if (-not $app.WaitForExit(120000)) { $app.Kill($true); throw 'Installed runtime import check exceeded 120 seconds; its process tree was stopped.' }
  if ($app.ExitCode -ne 0 -or -not (Test-Path $env:MENISCUS_PACKAGE_CHECK)) { throw 'Installed runtime failed to start or produce its import-check receipt.' }
  $health = Get-Content -Raw $env:MENISCUS_PACKAGE_CHECK | ConvertFrom-Json
  if (-not $health.passed) { throw 'Installed runtime import/identity check failed.' }
  $receipt['runtime_import_test']=$health
  Remove-Item Env:\MENISCUS_PACKAGE_CHECK
  $TestBase = Join-Path $env:LOCALAPPDATA 'Meniscus Annotator synthetic tests'
  $env:MENISCUS_TEST_AUTOCLOSE = '1'
  $env:MENISCUS_TEST_RUN_ID = [Guid]::NewGuid().ToString('N')
  $GenerationEvidence = Join-Path $BuildRoot 'synthetic-generation'
  New-Item -ItemType Directory -Force $GenerationEvidence | Out-Null
  $examples = Start-Process -FilePath (Join-Path $Installed 'MeniscusAnnotatorExamples.exe') -RedirectStandardOutput (Join-Path $GenerationEvidence 'stdout.txt') -RedirectStandardError (Join-Path $GenerationEvidence 'stderr.txt') -PassThru
  if (-not $examples.WaitForExit(120000)) { $examples.Kill($true); throw 'Installed synthetic generator exceeded 120 seconds.' }
  $createdReport = Join-Path (Join-Path $TestBase $env:MENISCUS_TEST_RUN_ID) 'installed-tests.json'
  if (Test-Path $createdReport) { Copy-Item $createdReport $GenerationEvidence }
  if ($examples.ExitCode -ne 0 -or -not (Test-Path $createdReport)) { throw 'Installed synthetic generator did not complete.' }
  $created = Get-Content -Raw $createdReport | ConvertFrom-Json
  if (-not $created.passed -or $created.folder_layout -ne 'flat' -or $created.annotation_mode -ne 'correction') { throw 'Installed synthetic correction package validation failed.' }
  $receipt['installed_synthetic_generation_test']=$created
  if ($RunIntegration) {
    # Run the actual packaged correction route first, including visible Export
    # OK/Cancel buttons and a separate-process restore. Synthetic inputs only.
    foreach ($action in @('correction','correction-resume')) {
      $env:MENISCUS_TEST_RUN_ID = [Guid]::NewGuid().ToString('N')
      $correctionRoot = Join-Path $TestBase $env:MENISCUS_TEST_RUN_ID
      $correctionEvidence = Join-Path $BuildRoot "synthetic-$action"
      New-Item -ItemType Directory -Force $correctionEvidence | Out-Null
      $entry = if ($action -eq 'correction') { 'MeniscusAnnotatorCorrectionChecks.exe' } else { 'MeniscusAnnotatorCorrectionResumeCheck.exe' }
      $correction = Start-Process -FilePath (Join-Path $Installed $entry) -RedirectStandardOutput (Join-Path $correctionEvidence 'stdout.txt') -RedirectStandardError (Join-Path $correctionEvidence 'stderr.txt') -PassThru
      if (-not $correction.WaitForExit(300000)) { $correction.Kill($true); throw "Installed $action checks exceeded five minutes." }
      if (Test-Path $correctionRoot) {
        Get-ChildItem $correctionRoot -Recurse -File | Where-Object { $_.Name -in @('correction-workflow.json','installed-tests.json') -or $_.Extension -eq '.png' } | Copy-Item -Destination $correctionEvidence
      }
      if ($correction.ExitCode -ne 0) { throw "Installed $action integration failed; inspect its reports." }
      $correctionReport = Get-Content -Raw (Join-Path $correctionRoot 'installed-tests.json') | ConvertFrom-Json
      if (-not $correctionReport.passed -or $correctionReport.application_source_sha256 -ne $Distribution.application_source_sha256) { throw "Installed $action result or source identity failed." }
      $receiptKey = if ($action -eq 'correction') { 'synthetic_correction_test' } else { 'synthetic_correction_resume_test' }
      $receipt[$receiptKey]=$correctionReport
    }
    # Exercise only the installed TestKit. No source checkout can shadow the app.
    $env:MENISCUS_TEST_RUN_ID = [Guid]::NewGuid().ToString('N')
    $fullRoot = Join-Path $TestBase $env:MENISCUS_TEST_RUN_ID
    $test = Start-Process -FilePath (Join-Path $Installed 'MeniscusAnnotatorChecks.exe') -PassThru
    if (-not $test.WaitForExit(600000)) { $test.Kill($true); throw 'Installed synthetic desktop checks exceeded ten minutes.' }
    $evidence = Join-Path $BuildRoot 'synthetic-integration'
    New-Item -ItemType Directory -Force $evidence | Out-Null
    Get-ChildItem $fullRoot -File | Where-Object { $_.Name -in @('slicer-workflow.json','installed-tests.json') -or $_.Extension -eq '.png' } | Copy-Item -Destination $evidence
    if ($test.ExitCode -ne 0) { throw 'Installed synthetic desktop integration failed; inspect its reports.' }
    $report = Get-Content -Raw (Join-Path $fullRoot 'installed-tests.json') | ConvertFrom-Json
    if (-not $report.passed) { throw 'Installed synthetic desktop integration reported failure.' }
    $receipt['synthetic_desktop_test']=$report
    $env:MENISCUS_TEST_RUN_ID = [Guid]::NewGuid().ToString('N')
    $resumeRoot = Join-Path $TestBase $env:MENISCUS_TEST_RUN_ID
    $resume = Start-Process -FilePath (Join-Path $Installed 'MeniscusAnnotatorResumeCheck.exe') -PassThru
    if (-not $resume.WaitForExit(180000)) { $resume.Kill($true); throw 'Installed synthetic resume check exceeded three minutes.' }
    $resumeEvidence = Join-Path $BuildRoot 'synthetic-resume'
    New-Item -ItemType Directory -Force $resumeEvidence | Out-Null
    Get-ChildItem $resumeRoot -File | Where-Object { $_.Name -in @('slicer-workflow.json','installed-tests.json') } | Copy-Item -Destination $resumeEvidence
    if ($resume.ExitCode -ne 0) { throw 'Installed fresh-process synthetic resume failed.' }
    $resumeReport = Get-Content -Raw (Join-Path $resumeRoot 'installed-tests.json') | ConvertFrom-Json
    if (-not $resumeReport.passed) { throw 'Installed synthetic resume reported failure.' }
    $receipt['synthetic_resume_test']=$resumeReport
  }
  Remove-Item Env:\MENISCUS_TEST_AUTOCLOSE
  Remove-Item Env:\MENISCUS_TEST_RUN_ID
  # Simulate a runtime dependency still held open; uninstall must fail before deletion.
  $HeldRuntime = [IO.File]::Open((Join-Path $Installed 'bin\python312.dll'), [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
  try {
    $locked = Start-Process -FilePath (Join-Path $Installed 'Uninstall.exe') -ArgumentList @('/S') -Wait -PassThru
    Checked $Python @((Join-Path $PSScriptRoot 'verify-installed.py'),$Installed)
    $receipt['locked_runtime_uninstall_test']='PASSED: locked runtime prevented all known-file deletion'
  } finally { $HeldRuntime.Dispose() }
  # Verify uninstall only removes known installed files, preserving unrelated files.
  $Sentinel = Join-Path $Installed 'unrelated-synthetic-sentinel.txt'
  'Keep this unrelated file' | Set-Content $Sentinel
  $uninstall = Start-Process -FilePath (Join-Path $Installed 'Uninstall.exe') -ArgumentList @('/S') -Wait -PassThru
  if ($uninstall.ExitCode -ne 0) { throw 'Uninstall failed.' }
  # NSIS uninstaller can use a temporary child; give it a bounded completion period.
  $limit = [DateTime]::UtcNow.AddSeconds(30)
  while ((Test-Path (Join-Path $Installed 'MeniscusAnnotator.exe')) -and [DateTime]::UtcNow -lt $limit) { Start-Sleep -Milliseconds 250 }
  if ((Test-Path (Join-Path $Installed 'MeniscusAnnotator.exe')) -or -not (Test-Path $Sentinel)) { throw 'Uninstall completion/preservation check failed.' }
  $receipt['uninstall_test']='PASSED: known executable removed; unrelated synthetic sentinel preserved'
}
} catch {
  $receipt['failure'] = $_.Exception.Message
  throw
} finally {
  $receipt | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $BuildRoot 'installer-build.json')
}
Write-Output "Windows installer: $Output"
Write-Output 'Windows11 mouse/keyboard/high-DPI/offline interactive acceptance remains required.'
