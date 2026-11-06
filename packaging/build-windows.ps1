# Maintainer-only build. Jeff never needs this script or a terminal.
[CmdletBinding()]
param(
  [string]$BuildRoot = 'C:\D\MA',
  [string]$QtRoot = 'C:\Qt\5.15.2\msvc2019_64',
  [int]$Parallel = 8,
  [switch]$SkipPackage,
  [switch]$RunIntegration
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
function Run-Checked([string]$Exe, [string[]]$Arguments) {
  & $Exe @Arguments
  if ($LASTEXITCODE -ne 0) { throw "$Exe failed (exit $LASTEXITCODE). See the build log." }
}
if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) {
  throw 'Use Windows x64 with the pinned Visual Studio 2022 toolchain.'
}
$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($SourceRoot.Length -gt 40 -or $SourceRoot -match ' ') {
  throw 'Use a short source checkout without spaces, e.g. C:\D\M. This is a Slicer build-path constraint.'
}
if ($BuildRoot.Length -gt 32 -or $BuildRoot -match ' ') {
  throw 'Use a short build path without spaces, e.g. C:\D\MA.'
}
$CMake = (Get-Command cmake.exe -ErrorAction Stop).Source
$Git = (Get-Command git.exe -ErrorAction Stop).Source
$gitVersion = & $Git --version
if ($gitVersion -ne 'git version 2.49.0.windows.1') { throw 'Install pinned Git for Windows 2.49.0.windows.1.' }
$cmakeVersion = (& $CMake --version | Select-Object -First 1)
if ($cmakeVersion -ne 'cmake version 3.31.6') { throw 'Install the pinned CMake 3.31.6 for this build.' }
if (-not (Test-Path (Join-Path $QtRoot 'lib\cmake\Qt5\Qt5Config.cmake'))) { throw 'Qt 5.15.2 msvc2019_64 is missing.' }
$qmakeVersion = & (Join-Path $QtRoot 'bin\qmake.exe') -query QT_VERSION
if ($qmakeVersion -ne '5.15.2') { throw 'Qt version must be 5.15.2.' }
$nsis = Join-Path ${env:ProgramFiles(x86)} 'NSIS\makensis.exe'
if (-not (Test-Path $nsis)) { throw 'Install NSIS 3.11 including language packs.' }
$nsisVersion = & $nsis /VERSION
if ($nsisVersion -ne 'v3.11') { throw 'NSIS version must be 3.11.' }
# Avoid accidentally using system Python in Slicer's superbuild.
if ($env:PYTHONHOME -or $env:PYTHONPATH) { throw 'Use a clean build shell without PYTHONHOME or PYTHONPATH.' }
New-Item -ItemType Directory -Force $BuildRoot | Out-Null
$Receipt = Join-Path $BuildRoot 'build-receipt.json'
$AppRevision = (& $Git -C $SourceRoot rev-parse HEAD).Trim()
$Dirty = [bool](& $Git -C $SourceRoot status --porcelain)
if ($Dirty) { throw 'Commit the intended application sources locally before producing a reproducible package.' }
$receiptData = [ordered]@{
  status='building'; app_version='0.1.0'; application_commit=$AppRevision
  slicer_version='5.12.4'; slicer_revision='34645'
  slicer_commit='4e21c19d8360242d88d6ca2490bf52400441b8e1'
  template_commit='1863e64fe2c622a4de8021b145de180a91d8de52'
  cmake=$cmakeVersion; git=$gitVersion; qt=$qmakeVersion; nsis=$nsisVersion
  generator='Visual Studio 17 2022'; toolset='v143,version=14.44.35207'
  windows_sdk='10.0.26100.0'; os=[Environment]::OSVersion.VersionString
  started_utc=[DateTime]::UtcNow.ToString('o'); interactive_windows_tests='NOT RUN'
}
$receiptData | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 $Receipt
Run-Checked $CMake @('-S',$SourceRoot,'-B',$BuildRoot,'-G','Visual Studio 17 2022','-A','x64',
  '-T','v143,version=14.44.35207','-DCMAKE_SYSTEM_VERSION:STRING=10.0.26100.0',
  "-DQt5_DIR:PATH=$QtRoot/lib/cmake/Qt5",'-DCMAKE_CONFIGURATION_TYPES:STRING=Release',
  '-DBUILD_TESTING:BOOL=ON','-DSlicer_USE_SYSTEM_python:BOOL=OFF','-DSlicer_RELEASE_TYPE:STRING=Stable')
Run-Checked $CMake @('--build',$BuildRoot,'--config','Release','--parallel',"$Parallel")
$Inner = Join-Path $BuildRoot 'Slicer-build'
if (-not (Test-Path (Join-Path $Inner 'MeniscusAnnotator.exe'))) {
  throw 'Built launcher missing. Inspect Slicer-build before packaging.'
}
# Use the included runtime for a pre-package import/branding check. No downloads here.
$env:MENISCUS_RUNTIME_RECEIPT = Join-Path $BuildRoot 'runtime-versions.json'
$env:MENISCUS_RUNTIME_ROOT = $Inner
Push-Location $Inner
try {
Run-Checked (Join-Path $Inner 'MeniscusAnnotator.exe') @('--no-main-window','--no-splash',
  '--python-script',(Join-Path $SourceRoot 'packaging\runtime_check.py'))
} finally { Pop-Location }
$RuntimeReceipt = Get-Content -Raw $env:MENISCUS_RUNTIME_RECEIPT | ConvertFrom-Json
if (-not $RuntimeReceipt.passed) { throw 'Bundled runtime health check failed. Inspect runtime-versions.json.' }
$receiptData['runtime_dependency_versions'] = $RuntimeReceipt
if ($RunIntegration) {
  # Requires an interactive desktop; a build-tree test does not verify the installer.
  $env:MENISCUS_TEST_OUTPUT = Join-Path $BuildRoot 'synthetic-integration'
  Run-Checked (Join-Path $Inner 'MeniscusAnnotator.exe') @('--no-splash','--python-script',
    (Join-Path $SourceRoot 'tests\slicer_workflow.py'))
  $TestReport = Join-Path $env:MENISCUS_TEST_OUTPUT 'slicer-workflow.json'
  if (-not (Test-Path $TestReport)) { throw 'Synthetic integration report missing.' }
  $TestResult = Get-Content -Raw $TestReport | ConvertFrom-Json
  if (-not $TestResult.passed) { throw "Synthetic integration failed. See $TestReport" }
  $receiptData['synthetic_build_tree_integration'] = $TestReport
}
if (-not $SkipPackage) {
  Run-Checked $CMake @('--build',$Inner,'--config','Release','--target','PACKAGE')
  $Installers = @(Get-ChildItem $Inner -Filter '*win-amd64.exe' -File)
  if ($Installers.Count -lt 1) { throw 'NSIS package missing; no installer can be handed off.' }
  $receiptData['installers'] = @($Installers | ForEach-Object {
    @{file=$_.Name; sha256=(Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()}
  })
}
$receiptData['status']='build_complete_windows_interaction_unverified'
$receiptData['completed_utc']=[DateTime]::UtcNow.ToString('o')
$receiptData | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 $Receipt
Write-Host "Build receipt: $Receipt"
Write-Host 'Complete the clean-machine acceptance record before calling the installer verified.'
