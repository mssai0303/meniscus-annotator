# Maintainer-only graphics selection. Nothing here changes the installer payload.
Set-StrictMode -Version Latest

function Enter-InstalledGraphicsMode {
  param([Parameter(Mandatory)][string]$Installed, [Parameter(Mandatory)][string]$Mode)
  if ($Mode -notin @('system','qt-software','bundled-mesa-alias')) { throw 'Unknown graphics probe mode.' }
  $Context = [ordered]@{ mode=$Mode; saved_environment=@{}; alias_path=$null; alias_sha256=$null }
  foreach ($Name in @('QT_OPENGL','QT_OPENGL_DLL','LIBGL_ALWAYS_SOFTWARE','MESA_GL_VERSION_OVERRIDE','MESA_GLSL_VERSION_OVERRIDE')) {
    $Context.saved_environment[$Name] = [Environment]::GetEnvironmentVariable($Name,'Process')
    [Environment]::SetEnvironmentVariable($Name,$null,'Process')
  }
  try {
    if ($Mode -ne 'system') { $env:QT_OPENGL = 'software' }
    if ($Mode -eq 'bundled-mesa-alias') {
      $Source = Join-Path $Installed 'bin\opengl32sw.dll'
      $Distribution = Get-Content -Raw (Join-Path $Installed 'distribution.json') | ConvertFrom-Json
      $Expected = $Distribution.files_sha256.'bin/opengl32sw.dll'
      $Actual = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash.ToLower()
      if ($Actual -ne $Expected) { throw 'Bundled software renderer differs from verified payload.' }
      $Alias = Join-Path $Installed 'bin\opengl32.dll'
      if (Test-Path -LiteralPath $Alias) { throw 'An OpenGL DLL already exists; no file was overwritten.' }
      Copy-Item -LiteralPath $Source -Destination $Alias
      $Context.alias_path = $Alias
      $Context.alias_sha256 = $Actual
      if ((Get-FileHash -LiteralPath $Alias -Algorithm SHA256).Hash.ToLower() -ne $Actual) { throw 'Ephemeral renderer alias checksum differs.' }
      $env:QT_OPENGL_DLL = 'opengl32.dll'
    }
    return $Context
  } catch {
    Exit-InstalledGraphicsMode -Context $Context
    throw
  }
}

function Exit-InstalledGraphicsMode {
  param([Parameter(Mandatory)]$Context)
  try {
    if ($Context.alias_path -and (Test-Path -LiteralPath $Context.alias_path)) {
      if ((Get-FileHash -LiteralPath $Context.alias_path -Algorithm SHA256).Hash.ToLower() -ne $Context.alias_sha256) {
        throw 'Unexpected renderer alias change; refusing to delete an unknown file.'
      }
      Remove-Item -LiteralPath $Context.alias_path
    }
  } finally {
    foreach ($Name in $Context.saved_environment.Keys) {
      [Environment]::SetEnvironmentVariable($Name,$Context.saved_environment[$Name],'Process')
    }
  }
}

function Test-InstalledGraphics {
  param([Parameter(Mandatory)][string]$Installed, [Parameter(Mandatory)][string]$Evidence,
        [int]$TimeoutSeconds=45)
  New-Item -ItemType Directory -Force $Evidence | Out-Null
  $Results = @()
  $Selected = $null
  $OriginalProbeOutput = $env:MENISCUS_GRAPHICS_PROBE_OUTPUT
  $OriginalProbeMode = $env:MENISCUS_GRAPHICS_PROBE_MODE
  try {
    foreach ($Mode in @('system','qt-software','bundled-mesa-alias')) {
      $Context = Enter-InstalledGraphicsMode -Installed $Installed -Mode $Mode
      $Result = [ordered]@{ mode=$Mode; passed=$false; ephemeral_alias=$Context.alias_path; alias_sha256=$Context.alias_sha256 }
      try {
        $env:MENISCUS_GRAPHICS_PROBE_OUTPUT = Join-Path $Evidence "$Mode.json"
        $env:MENISCUS_GRAPHICS_PROBE_MODE = $Mode
        $Script = Join-Path $PSScriptRoot 'RenderingProbe.py'
        $Process = Start-Process -FilePath (Join-Path $Installed 'MeniscusAnnotatorTest.exe') `
          -ArgumentList @('--no-splash','--testing','--ignore-slicerrc','--disable-message-handlers','--python-script',('"' + $Script + '"')) `
          -WorkingDirectory $Installed -RedirectStandardOutput (Join-Path $Evidence "$Mode.stdout.txt") `
          -RedirectStandardError (Join-Path $Evidence "$Mode.stderr.txt") -PassThru
        $Exited = $Process.WaitForExit($TimeoutSeconds * 1000)
        if (-not $Exited) { $Process.Kill($true); $Process.WaitForExit() }
        $Result['exited'] = $Exited
        $Result['exit_code'] = $Process.ExitCode
        if (Test-Path -LiteralPath $env:MENISCUS_GRAPHICS_PROBE_OUTPUT) {
          $Probe = Get-Content -Raw $env:MENISCUS_GRAPHICS_PROBE_OUTPUT | ConvertFrom-Json
          $Result['probe'] = $Probe
          $Result.passed = $Exited -and $Process.ExitCode -eq 0 -and $Probe.passed
        }
      } finally {
        Exit-InstalledGraphicsMode -Context $Context
        $Result['ephemeral_alias_removed'] = -not $Context.alias_path -or -not (Test-Path -LiteralPath $Context.alias_path)
      }
      $Results += $Result
      if ($Result.passed) { $Selected=$Mode; break }
    }
  } finally {
    [Environment]::SetEnvironmentVariable('MENISCUS_GRAPHICS_PROBE_OUTPUT',$OriginalProbeOutput,'Process')
    [Environment]::SetEnvironmentVariable('MENISCUS_GRAPHICS_PROBE_MODE',$OriginalProbeMode,'Process')
  }
  $Summary = [ordered]@{
    schema_version='meniscus_installed_graphics_selection/1'; passed=($null -ne $Selected)
    selected_mode=$Selected; attempts=$Results
    scope='Synthetic hosted rendering only; no installer payload changes or human Windows acceptance'
    capability_overrides_used=$false; installer_payload_modified=$false
  }
  $Summary | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 (Join-Path $Evidence 'graphics-selection.json')
  return $Summary
}
