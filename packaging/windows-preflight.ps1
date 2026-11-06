# Maintainer-only local environment/persistence check. No admin or policy changes.
[CmdletBinding()]
param([string]$OutputDirectory = '', [string]$VerifyProbe = '',
  [ValidateSet('baseline','disconnect-reconnect','logoff-new-session')][string]$Phase = 'baseline')
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'This environment receipt is for the authorised Windows test session.' }
if ($VerifyProbe) {
  if ($Phase -eq 'baseline') { throw 'Choose -Phase disconnect-reconnect or logoff-new-session when verifying a saved probe.' }
  if (-not (Test-Path -LiteralPath $VerifyProbe)) { throw 'Persistence probe did not survive or this is a different session/profile. Do not rely on this location for annotation work yet.' }
  $value = Get-Content -Raw -LiteralPath $VerifyProbe | ConvertFrom-Json
  $actual = (Get-FileHash -LiteralPath $VerifyProbe -Algorithm SHA256).Hash.ToLower()
  [pscustomobject]@{probe_found=$true;phase=$Phase;created_utc=$value.created_utc;sha256=$actual;scope='Compare SHA256 with the original receipt after reconnect/logoff. Recomposition persistence still requires the VDI owner to confirm.'} | ConvertTo-Json
  return
}
if (-not $OutputDirectory) { $OutputDirectory = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Meniscus_annotation_work\environment-check' }
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$receipt = [ordered]@{created_utc=[DateTime]::UtcNow.ToString('o');platform_verification='NOT VERIFIED';permission='Install/run permission must be confirmed with the VDI owner';persistence='Immediate write only; reconnect/logoff and VDI profile-reset behaviour remain unverified';session_name=$env:SESSIONNAME;display_and_OpenGL='Must inspect actual Slicer synthetic rendering in this Horizon session'}
try { $os = Get-CimInstance Win32_OperatingSystem; $receipt['os'] = @{caption=$os.Caption;version=$os.Version;build=$os.BuildNumber;architecture=$os.OSArchitecture;free_memory_kib=$os.FreePhysicalMemory} } catch { $receipt['os_error']=$_.Exception.Message }
try { $receipt['graphics'] = @(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,VideoModeDescription) } catch { $receipt['graphics_error']=$_.Exception.Message }
try { $receipt['disks'] = @(Get-CimInstance Win32_LogicalDisk | Select-Object DeviceID,DriveType,Size,FreeSpace) } catch { $receipt['disk_error']=$_.Exception.Message }
function Describe-Location([string]$Path) {
  $result = [ordered]@{path=$Path;profile_container_persistence='UNKNOWN: a local drive can still be a disposable VDI profile/container; ask IT';is_unc=$Path.StartsWith('\\')}
  try { $result['resolved_path']=(Resolve-Path -LiteralPath $Path).Path; $result['attributes']=(Get-Item -LiteralPath $Path).Attributes.ToString() } catch { $result['resolution_error']=$_.Exception.Message }
  try {
    $root=[IO.Path]::GetPathRoot($Path)
    $result['drive_root']=$root
    if ($root -match '^[A-Za-z]:') {
      $device=$root.Substring(0,2)
      $disk=Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$device'"
      $result['drive_type']=$disk.DriveType
      $result['network_provider']=$disk.ProviderName
      $result['free_bytes']=$disk.FreeSpace
    }
  } catch { $result['drive_error']=$_.Exception.Message }
  return $result
}
$receipt['Documents']=Describe-Location ([Environment]::GetFolderPath('MyDocuments'))
$receipt['LOCALAPPDATA']=Describe-Location $env:LOCALAPPDATA
$receipt['USERPROFILE']=Describe-Location $env:USERPROFILE
$receipt['persistence_required']='Verify the same probe separately after disconnect/reconnect AND logoff/new session; ask IT about recomposition, profile reset and FSLogix/profile-container persistence. If disposable, choose approved persistent active-work storage and backup before annotation. Dropbox cannot be the only active copy.'
$probe = Join-Path $OutputDirectory ('persistence-' + [Guid]::NewGuid().ToString('N') + '.json')
@{created_utc=$receipt.created_utc;nonce=[Guid]::NewGuid().ToString('N')} | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath $probe
$receipt['probe_file']=$probe
$receipt['probe_sha256']=(Get-FileHash -LiteralPath $probe -Algorithm SHA256).Hash.ToLower()
$report = Join-Path $OutputDirectory 'windows-environment.json'
$receipt | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -LiteralPath $report
Write-Output "Environment receipt: $report"
Write-Output "Reconnect/logoff as authorised, then check the same probe: $probe"
Write-Output 'No MRI files were read. Do not treat this receipt as graphics, installer or annotation-workflow acceptance.'
