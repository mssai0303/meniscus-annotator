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
$Output = Join-Path $BuildRoot 'MeniscusAnnotator-0.2.0-Windows-x64.exe'
$NsisArguments = @('/V2',"/DPAYLOAD=$Payload","/DOUTPUT=$Output",
  "/DUNINSTALL_FILES=$(Join-Path $BuildRoot 'uninstall-files.nsh')",
  "/DLICENSE_FILE=$(Join-Path $Repo 'LICENSE')")
if ($FastPackage) { $NsisArguments += '/DFAST_PACKAGE' }
$NsisArguments += (Join-Path $PSScriptRoot 'installer.nsi')
Checked $Nsis $NsisArguments
$receipt = [ordered]@{
  schema_version='meniscus_installer_build/1'; route=$Lock.route; app_version='0.2.0'
  runner_os=[Environment]::OSVersion.VersionString; runner_image=$env:ImageVersion
  runtime_download_sha512=$Lock.slicer.sha512
  application_commit=$Distribution.application_commit
  application_source_sha256=$Distribution.application_source_sha256
  application_source_dirty=$Distribution.application_source_dirty
  compression_mode=$(if ($FastPackage) { 'zlib-development-fast' } else { 'solid-lzma' })
  installer_filename=(Split-Path -Leaf $Output); installer_bytes=(Get-Item $Output).Length
  installer_sha256=(Get-FileHash $Output -Algorithm SHA256).Hash.ToLower()
  nsis='3.13'; sevenzip='26.05'; install_test='NOT RUN'; runtime_import_test='NOT RUN'
  synthetic_desktop_test='NOT RUN'; synthetic_resume_test='NOT RUN'; synthetic_correction_test='NOT RUN'; synthetic_correction_resume_test='NOT RUN'
  synthetic_draw_test='NOT RUN'; synthetic_draw_resume_test='NOT RUN'; synthetic_draw_layout_tests='NOT RUN'
  synthetic_regional_test='NOT RUN'; synthetic_regional_resume_test='NOT RUN'; synthetic_regional_legacy_test='NOT RUN'
  ordinary_reader_workflow_test='NOT RUN'; ordinary_reader_resume_test='NOT RUN'
  headless_technical_persistence_test='NOT RUN'
  regional_reader_example_import_test='NOT RUN'
  installed_graphics_probe='NOT RUN'; installed_graphics_mode='system'
  offline_runtime_import_test='NOT RUN'; process_network_block='NOT RUN'
  Windows11_interactive_acceptance='NOT RUN'; Horizon_Windows10_19045_acceptance='NOT RUN'
}
$NetworkRules = @()
try {
if ($TestInstall) {
  # Private ephemeral build host only. No MRI data enter this workflow.
  $LegacyKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\MeniscusAnnotator-0.1.0'
  if (Test-Path $LegacyKey) { throw 'Use a clean host for the legacy-registration guard test.' }
  $GuardTarget = Join-Path $BuildRoot 'Legacy upgrade refusal'
  try {
    New-Item -Path $LegacyKey -Force | Out-Null
    New-ItemProperty -Path $LegacyKey -Name InstallLocation -Value 'C:\Synthetic legacy registration only' -PropertyType String | Out-Null
    $Guarded = Start-Process -FilePath $Output -ArgumentList @('/S',"/D=$GuardTarget") -Wait -PassThru
    if (Test-Path (Join-Path $GuardTarget 'MeniscusAnnotator.exe')) { throw 'Legacy upgrade guard allowed mixed versions.' }
    $receipt['legacy_registration_guard']='PASSED: simulated 0.1 registration rejected; actual old-binary upgrade not claimed'
  } finally { Remove-Item -Path $LegacyKey -Force -ErrorAction SilentlyContinue }
  $WorkSentinel = Join-Path $BuildRoot 'Synthetic work outside installation.txt'
  'Preserve existing reader work' | Set-Content $WorkSentinel
  $WorkSentinelHash = (Get-FileHash $WorkSentinel -Algorithm SHA256).Hash
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
  if ($env:GITHUB_ACTIONS -eq 'true') {
    # Ephemeral hosted CI only, never a reader installation prerequisite. Deny
    # egress for the two native runtimes without affecting the runner/build tools.
    try {
      if ((Get-Service -Name MpsSvc -ErrorAction Stop).Status -ne 'Running' -or
          @(Get-NetFirewallProfile -ErrorAction Stop | Where-Object { [string]$_.Enabled -ne 'True' }).Count -gt 0) {
        throw 'Host firewall is not active for every profile; process isolation cannot be claimed.'
      }
      foreach ($NativeName in @('MeniscusAnnotatorApp-real.exe','MeniscusAnnotatorTestApp-real.exe')) {
        $RuleName = 'MeniscusSynthetic-' + [Guid]::NewGuid().ToString('N')
        New-NetFirewallRule -Name $RuleName -DisplayName $RuleName -Direction Outbound -Action Block `
          -Program (Join-Path $Installed ('bin\' + $NativeName)) -Profile Any -ErrorAction Stop | Out-Null
        $NetworkRules += $RuleName
        $ActiveRule = Get-NetFirewallRule -Name $RuleName -PolicyStore ActiveStore -ErrorAction Stop
        if ([string]$ActiveRule.EnforcementStatus -ne 'Full') { throw 'Host policy does not fully enforce the temporary outbound rule.' }
      }
      $receipt['process_network_block']='APPLIED: temporary outbound deny for normal/test native runtime executables; build and artifact tools are unaffected'
    } catch {
      $receipt['process_network_block']='NOT AVAILABLE: ' + $_.Exception.Message
      foreach ($RuleName in $NetworkRules) { Remove-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue }
      $NetworkRules = @()
    }
  }
  $env:MENISCUS_PACKAGE_CHECK = Join-Path $BuildRoot 'installed-runtime-check.json'
  $env:PYTHONDONTWRITEBYTECODE = '1'
  $app = Start-Process -FilePath (Join-Path $Installed 'MeniscusAnnotator.exe') -ArgumentList @('--no-main-window') -PassThru
  if (-not $app.WaitForExit(120000)) { $app.Kill($true); throw 'Installed runtime import check exceeded 120 seconds; its process tree was stopped.' }
  if ($app.ExitCode -ne 0 -or -not (Test-Path $env:MENISCUS_PACKAGE_CHECK)) { throw 'Installed runtime failed to start or produce its import-check receipt.' }
  $health = Get-Content -Raw $env:MENISCUS_PACKAGE_CHECK | ConvertFrom-Json
  if (-not $health.passed) { throw 'Installed runtime import/identity check failed.' }
  $receipt['runtime_import_test']=$health
  if ($NetworkRules.Count -eq 2) { $receipt['offline_runtime_import_test']='PASSED: installed normal runtime imports/identity completed while its native process had outbound network denied' }
  Remove-Item Env:\MENISCUS_PACKAGE_CHECK
  $RegionalExample = Join-Path $Installed 'Examples\read_regional_annotation.py'
  if (Test-Path -LiteralPath $RegionalExample) {
    $ReaderEvidence = Join-Path $BuildRoot 'regional-reader-check'
    New-Item -ItemType Directory -Force $ReaderEvidence | Out-Null
    $ReaderProcess = Start-Process -FilePath (Join-Path $Installed 'bin\PythonSlicer.exe') `
      -ArgumentList @(('"' + $RegionalExample + '"'),'--help') -WorkingDirectory $Installed `
      -RedirectStandardOutput (Join-Path $ReaderEvidence 'stdout.txt') `
      -RedirectStandardError (Join-Path $ReaderEvidence 'stderr.txt') -PassThru
    if (-not $ReaderProcess.WaitForExit(60000)) { $ReaderProcess.Kill($true); throw 'Installed optional regional reader import exceeded one minute.' }
    $ReaderHelp = Get-Content -Raw (Join-Path $ReaderEvidence 'stdout.txt')
    if ($ReaderProcess.ExitCode -ne 0 -or $ReaderHelp -notmatch '--case-key' -or $ReaderHelp -notmatch '--source-image') { throw 'Installed optional regional reader failed to import through the bundled runtime.' }
    $receipt['regional_reader_example_import_test']='PASSED: optional example loads installed application helpers via bundled Python; no annotation input read, edited or approved'
  }
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
  # The storage/core path can run without a render context. Use actual installed
  # Slicer segmentation storage and an independent NIfTI reader. This is separate
  # evidence from GUI Draw/Erase/Export-dialog acceptance below the graphics gate.
  $CoreEvidence = Join-Path $BuildRoot 'headless-persistence'
  New-Item -ItemType Directory -Force $CoreEvidence | Out-Null
  $env:MENISCUS_CORE_CHECK_OUTPUT = Join-Path $CoreEvidence 'Synthetic work'
  $CoreProcess = Start-Process -FilePath (Join-Path $Installed 'MeniscusAnnotator.exe') `
    -ArgumentList @('--no-main-window','--testing','--ignore-slicerrc','--python-script',('"' + (Join-Path $Installed 'TestKit\CorePersistenceCheck.py') + '"')) `
    -RedirectStandardOutput (Join-Path $CoreEvidence 'stdout.txt') `
    -RedirectStandardError (Join-Path $CoreEvidence 'stderr.txt') -PassThru
  if (-not $CoreProcess.WaitForExit(120000)) { $CoreProcess.Kill($true); throw 'Installed headless persistence check exceeded two minutes.' }
  $CoreReportPath = Join-Path $CoreEvidence 'headless-persistence-check.json'
  if ($CoreProcess.ExitCode -ne 0 -or -not (Test-Path $CoreReportPath)) { throw 'Installed headless persistence check failed; inspect its dedicated evidence.' }
  $CoreReport = Get-Content -Raw $CoreReportPath | ConvertFrom-Json
  if (-not $CoreReport.passed -or $CoreReport.application_source_sha256 -ne $Distribution.application_source_sha256) { throw 'Installed headless persistence result or source identity failed.' }
  $receipt['headless_technical_persistence_test']=$CoreReport
  Remove-Item Env:\MENISCUS_CORE_CHECK_OUTPUT
  if ($RunIntegration) {
    # Hosted runners may have no usable WGL pixel format. One bounded fresh
    # system-renderer probe records the actual capability. Do not repeatedly
    # retry the known hosted OpenGL limitation or spoof a required version.
    . (Join-Path $PSScriptRoot 'InstalledGraphics.ps1')
    $Graphics = Test-InstalledGraphics -Installed $Installed -Evidence (Join-Path $BuildRoot 'graphics-probe')
    $receipt['installed_graphics_probe']=$Graphics
    if ($Graphics.passed) {
    $receipt['installed_graphics_mode']=$Graphics.selected_mode
    $GraphicsContext = Enter-InstalledGraphicsMode -Installed $Installed -Mode $Graphics.selected_mode
    try {
    foreach ($ReviewAction in @(@{name='review';entry='MeniscusAnnotatorReviewChecks.exe'},@{name='review-resume';entry='MeniscusAnnotatorReviewResumeCheck.exe'})) {
      $env:MENISCUS_TEST_RUN_ID = [Guid]::NewGuid().ToString('N')
      $ReviewRoot = Join-Path $TestBase $env:MENISCUS_TEST_RUN_ID
      $ReviewEvidence = Join-Path $BuildRoot $ReviewAction.name
      New-Item -ItemType Directory -Force $ReviewEvidence | Out-Null
      $ReviewProcess = Start-Process -FilePath (Join-Path $Installed $ReviewAction.entry) `
        -RedirectStandardOutput (Join-Path $ReviewEvidence 'stdout.txt') `
        -RedirectStandardError (Join-Path $ReviewEvidence 'stderr.txt') -PassThru
      if (-not $ReviewProcess.WaitForExit(300000)) { $ReviewProcess.Kill($true); throw 'Ordinary reader check exceeded five minutes.' }
      if (Test-Path $ReviewRoot) { Get-ChildItem $ReviewRoot -Recurse -File | Where-Object { $_.Extension -in @('.json','.png') } | Copy-Item -Destination $ReviewEvidence }
      if ($ReviewProcess.ExitCode -ne 0) { throw 'Ordinary reader UI checks failed.' }
      $ReviewReport = Get-Content -Raw (Join-Path $ReviewRoot 'installed-tests.json') | ConvertFrom-Json
      if (-not $ReviewReport.passed) { throw 'Ordinary reader workflow reported failure.' }
      $Key = if ($ReviewAction.name -eq 'review') { 'ordinary_reader_workflow_test' } else { 'ordinary_reader_resume_test' }
      $receipt[$Key]=$ReviewReport
    }
    # Optional regional draft workflow uses separate synthetic state, preserves
    # whole labels, and never treats protocol-pending regions as research labels.
    foreach ($Action in @('regions','regions-resume','regions-legacy')) {
      $env:MENISCUS_TEST_RUN_ID = [Guid]::NewGuid().ToString('N')
      $RegionalRoot = Join-Path $TestBase $env:MENISCUS_TEST_RUN_ID
      $RegionalEvidence = Join-Path $BuildRoot ('synthetic-' + $Action)
      New-Item -ItemType Directory -Force $RegionalEvidence | Out-Null
      $Entry = switch ($Action) {
        'regions' { 'MeniscusAnnotatorRegionsChecks.exe' }
        'regions-resume' { 'MeniscusAnnotatorRegionsResumeCheck.exe' }
        'regions-legacy' { 'MeniscusAnnotatorRegionsLegacyCheck.exe' }
      }
      $RegionalProcess = Start-Process -FilePath (Join-Path $Installed $Entry) `
        -RedirectStandardOutput (Join-Path $RegionalEvidence 'stdout.txt') `
        -RedirectStandardError (Join-Path $RegionalEvidence 'stderr.txt') -PassThru
      if (-not $RegionalProcess.WaitForExit(300000)) { $RegionalProcess.Kill($true); throw "Installed $Action checks exceeded five minutes." }
      if (Test-Path -LiteralPath $RegionalRoot) {
        Get-ChildItem -LiteralPath $RegionalRoot -Recurse -File | Where-Object { $_.Extension -in @('.json','.png') } | Copy-Item -Destination $RegionalEvidence
      }
      if ($RegionalProcess.ExitCode -ne 0) { throw "Installed $Action failed; inspect its reports." }
      $RegionalReport = Get-Content -Raw (Join-Path $RegionalRoot 'installed-tests.json') | ConvertFrom-Json
      if (-not $RegionalReport.passed -or $RegionalReport.application_source_sha256 -ne $Distribution.application_source_sha256) { throw "Installed $Action result or source identity failed." }
      $Key = switch ($Action) {
        'regions' { 'synthetic_regional_test' }
        'regions-resume' { 'synthetic_regional_resume_test' }
        'regions-legacy' { 'synthetic_regional_legacy_test' }
      }
      $receipt[$Key]=$RegionalReport
    }
    # New Draw/Erase interaction and the eight known-geometry combinations.
    # Layout passes simulate Qt scale factors; they are not physical display-DPI
    # or human interaction acceptance on Windows 10/11.
    $SavedQtScale = $env:QT_SCALE_FACTOR
    $SavedDrawScale = $env:MENISCUS_DRAW_SCALE_NAME
    $LayoutReports = @()
    try {
      foreach ($DrawAction in @(
        @{name='draw';entry='MeniscusAnnotatorDrawChecks.exe';scale=$null;factor=$null},
        @{name='draw-resume';entry='MeniscusAnnotatorDrawResumeCheck.exe';scale=$null;factor=$null},
        @{name='draw-layout-100';entry='MeniscusAnnotatorDrawLayoutChecks.exe';scale='100';factor='1'},
        @{name='draw-layout-125';entry='MeniscusAnnotatorDrawLayoutChecks.exe';scale='125';factor='1.25'},
        @{name='draw-layout-150';entry='MeniscusAnnotatorDrawLayoutChecks.exe';scale='150';factor='1.5'},
        @{name='draw-layout-175';entry='MeniscusAnnotatorDrawLayoutChecks.exe';scale='175';factor='1.75'},
        @{name='draw-layout-200';entry='MeniscusAnnotatorDrawLayoutChecks.exe';scale='200';factor='2'})) {
        [Environment]::SetEnvironmentVariable('QT_SCALE_FACTOR',$DrawAction.factor,'Process')
        [Environment]::SetEnvironmentVariable('MENISCUS_DRAW_SCALE_NAME',$DrawAction.scale,'Process')
        $env:MENISCUS_TEST_RUN_ID = [Guid]::NewGuid().ToString('N')
        $DrawRoot = Join-Path $TestBase $env:MENISCUS_TEST_RUN_ID
        $DrawEvidence = Join-Path $BuildRoot ('synthetic-' + $DrawAction.name)
        New-Item -ItemType Directory -Force $DrawEvidence | Out-Null
        $DrawProcess = Start-Process -FilePath (Join-Path $Installed $DrawAction.entry) `
          -RedirectStandardOutput (Join-Path $DrawEvidence 'stdout.txt') `
          -RedirectStandardError (Join-Path $DrawEvidence 'stderr.txt') -PassThru
        if (-not $DrawProcess.WaitForExit(300000)) { $DrawProcess.Kill($true); throw "Installed $($DrawAction.name) checks exceeded five minutes." }
        if (Test-Path -LiteralPath $DrawRoot) {
          Get-ChildItem -LiteralPath $DrawRoot -Recurse -File | Where-Object { $_.Extension -in @('.json','.png') } | Copy-Item -Destination $DrawEvidence
        }
        if ($DrawProcess.ExitCode -ne 0) { throw "Installed $($DrawAction.name) failed; inspect its reports." }
        $DrawReport = Get-Content -Raw (Join-Path $DrawRoot 'installed-tests.json') | ConvertFrom-Json
        if (-not $DrawReport.passed -or $DrawReport.application_source_sha256 -ne $Distribution.application_source_sha256) { throw "Installed $($DrawAction.name) result or source identity failed." }
        if ($DrawAction.name -eq 'draw') { $receipt['synthetic_draw_test']=$DrawReport }
        elseif ($DrawAction.name -eq 'draw-resume') { $receipt['synthetic_draw_resume_test']=$DrawReport }
        else { $LayoutReports += $DrawReport }
      }
      $receipt['synthetic_draw_layout_tests']=$LayoutReports
    } finally {
      [Environment]::SetEnvironmentVariable('QT_SCALE_FACTOR',$SavedQtScale,'Process')
      [Environment]::SetEnvironmentVariable('MENISCUS_DRAW_SCALE_NAME',$SavedDrawScale,'Process')
    }
    # Also run the packaged correction route, including visible Export
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
    } finally {
      Exit-InstalledGraphicsMode -Context $GraphicsContext
      Checked $Python @((Join-Path $PSScriptRoot 'verify-installed.py'),$Installed)
      $receipt['graphics_probe_cleanup']='PASSED: ephemeral renderer alias removed and original installed payload hashes retained'
    }
    } else {
      $Blocked = 'BLOCKED: hosted runner could not render synthetic pixels with actual OpenGL 3.2; inspect graphics-probe evidence. This is not a workflow pass.'
      $receipt['synthetic_desktop_test']=$Blocked
      $receipt['synthetic_resume_test']=$Blocked
      $receipt['synthetic_correction_test']=$Blocked
      $receipt['synthetic_correction_resume_test']=$Blocked
      $receipt['synthetic_draw_test']=$Blocked
      $receipt['synthetic_draw_resume_test']=$Blocked
      $receipt['synthetic_draw_layout_tests']=$Blocked
      $receipt['synthetic_regional_test']=$Blocked
      $receipt['synthetic_regional_resume_test']=$Blocked
      $receipt['synthetic_regional_legacy_test']=$Blocked
      $receipt['ordinary_reader_workflow_test']=$Blocked
      $receipt['ordinary_reader_resume_test']=$Blocked
      $receipt['installed_graphics_mode']=$null
      Checked $Python @((Join-Path $PSScriptRoot 'verify-installed.py'),$Installed)
      $receipt['graphics_probe_cleanup']='PASSED: all probe aliases removed; original installed payload hashes retained'
    }
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
  $CurrentRegistration = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\MeniscusAnnotator-0.2.0'
  while (((Test-Path (Join-Path $Installed 'MeniscusAnnotator.exe')) -or (Test-Path $CurrentRegistration)) -and [DateTime]::UtcNow -lt $limit) { Start-Sleep -Milliseconds 250 }
  if ((Test-Path (Join-Path $Installed 'MeniscusAnnotator.exe')) -or (Test-Path $CurrentRegistration) -or -not (Test-Path $Sentinel)) { throw 'Uninstall completion/preservation check failed.' }
  $receipt['uninstall_test']='PASSED: known executable removed; unrelated synthetic sentinel preserved'
  if ((Get-FileHash $WorkSentinel -Algorithm SHA256).Hash -ne $WorkSentinelHash) { throw 'External synthetic work was altered.' }
  $Reinstalled = Join-Path $BuildRoot 'Reinstalled with spaces'
  $Again = Start-Process -FilePath $Output -ArgumentList @('/S',"/D=$Reinstalled") -Wait -PassThru
  if ($Again.ExitCode -ne 0) { throw 'Reinstallation failed.' }
  Checked $Python @((Join-Path $PSScriptRoot 'verify-installed.py'),$Reinstalled)
  if ((Get-FileHash $WorkSentinel -Algorithm SHA256).Hash -ne $WorkSentinelHash) { throw 'Reinstallation altered external work.' }
  $RemoveAgain = Start-Process -FilePath (Join-Path $Reinstalled 'Uninstall.exe') -ArgumentList @('/S') -Wait -PassThru
  if ($RemoveAgain.ExitCode -ne 0) { throw 'Reinstalled application uninstall failed.' }
  $limit = [DateTime]::UtcNow.AddSeconds(30)
  while (((Test-Path (Join-Path $Reinstalled 'MeniscusAnnotator.exe')) -or (Test-Path $CurrentRegistration)) -and [DateTime]::UtcNow -lt $limit) { Start-Sleep -Milliseconds 250 }
  if ((Test-Path (Join-Path $Reinstalled 'MeniscusAnnotator.exe')) -or (Test-Path $CurrentRegistration)) { throw 'Reinstalled application removal did not complete.' }
  $receipt['reinstall_work_preservation']='PASSED: fresh reinstall bytes verified; external synthetic work retained; application removed normally'
}
} catch {
  $receipt['failure'] = $_.Exception.Message
  throw
} finally {
  foreach ($RuleName in $NetworkRules) { Remove-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue }
  if ($NetworkRules.Count -gt 0) { $receipt['process_network_block_cleanup']='Temporary CI-only firewall rules removed' }
  $receipt | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $BuildRoot 'installer-build.json')
}
Write-Output "Windows installer: $Output"
Write-Output 'Windows 10 x64 Horizon mouse/keyboard/high-DPI/offline interactive acceptance remains pending. Windows 11 is untested.'
