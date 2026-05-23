# Kodi POV IL -- post-install Windows setup. Called by the NSIS
# installer once Kodi itself is in place.
#
# Lays out our build + wizard inside %APPDATA%\Kodi and registers the
# wizard in addon-manifest.xml so it boots as a system addon. After
# Kodi launches the wizard's startup.py opens its Builds menu, which
# lets the user kick off Fresh Install -- same first-launch path as
# the Android APK.

param(
  [Parameter(Mandatory=$true)][string]$KodiData,
  [Parameter(Mandatory=$true)][string]$KodiSystem,
  [Parameter(Mandatory=$true)][string]$WizardZip,
  [Parameter(Mandatory=$true)][string]$BuildZip,
  [string]$LogPath = ""
)

# Always emit a log so we can diagnose remote failures. NSIS passes
# -LogPath; if absent, fall back to %TEMP%.
if ([string]::IsNullOrWhiteSpace($LogPath)) {
  $LogPath = Join-Path $env:TEMP "kodi-pov-il-setup.log"
}
try { Start-Transcript -Path $LogPath -Force | Out-Null } catch { }

$ErrorActionPreference = 'Stop'

function Fail([string]$msg) {
  Write-Host "ERROR: $msg"
  try { Stop-Transcript | Out-Null } catch { }
  exit 1
}

try {
  Write-Host "Kodi POV IL setup starting at $(Get-Date -Format o)"
  Write-Host "KodiData   = $KodiData"
  Write-Host "KodiSystem = $KodiSystem"
  Write-Host "WizardZip  = $WizardZip"
  Write-Host "BuildZip   = $BuildZip"
  Write-Host "PSVersion  = $($PSVersionTable.PSVersion)"

  if (-not (Test-Path $WizardZip)) { Fail "WizardZip not found at $WizardZip" }
  if (-not (Test-Path $BuildZip))  { Fail "BuildZip not found at $BuildZip" }

  # Make sure the data dir exists. Kodi normally creates it on first
  # launch; we pre-create so we can drop the build into it now.
  New-Item -ItemType Directory -Force -Path $KodiData            | Out-Null
  New-Item -ItemType Directory -Force -Path "$KodiData\addons"   | Out-Null
  New-Item -ItemType Directory -Force -Path "$KodiData\userdata" | Out-Null

  # Use .NET's ZipFile API directly -- Expand-Archive on Windows
  # PowerShell 5.1 has issues with overwriting existing files and with
  # archives that contain many long paths. ZipFile.ExtractToDirectory
  # with the 4-arg overload (added in .NET 4.7.2 / PowerShell 5.1 on
  # Windows 10+) handles overwrites cleanly.
  Add-Type -AssemblyName System.IO.Compression.FileSystem

  function Expand-ZipOverwrite([string]$Zip, [string]$Dest) {
    Write-Host "Extracting $Zip -> $Dest"
    if (-not (Test-Path $Dest)) {
      New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    }
    # 4-arg overload exists on Windows 10 1809+ / .NET 4.7.2+. Fall
    # back to per-entry extraction if the runtime is older.
    $hasOverwriteOverload = $false
    try {
      $hasOverwriteOverload = [bool]([System.IO.Compression.ZipFile].GetMethod(
        'ExtractToDirectory',
        [type[]]@([string],[string],[System.Text.Encoding],[bool])))
    } catch { }
    if ($hasOverwriteOverload) {
      [System.IO.Compression.ZipFile]::ExtractToDirectory(
        $Zip, $Dest, [System.Text.Encoding]::UTF8, $true)
    } else {
      $archive = [System.IO.Compression.ZipFile]::OpenRead($Zip)
      try {
        foreach ($entry in $archive.Entries) {
          $target = Join-Path $Dest $entry.FullName
          if ($entry.FullName.EndsWith('/')) {
            New-Item -ItemType Directory -Force -Path $target | Out-Null
            continue
          }
          $parent = Split-Path -Parent $target
          if ($parent -and -not (Test-Path $parent)) {
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
          }
          [System.IO.Compression.ZipFileExtensions]::ExtractToFile(
            $entry, $target, $true)
        }
      } finally {
        $archive.Dispose()
      }
    }
  }

  # 1. Lay down the full FENtastic build first so all the supporting
  #    addons (POV, FENtastic, script.module.* deps) and the seeded
  #    userdata land in place. The build zip includes its own copy of
  #    the wizard under addons/ -- that copy may be older than the
  #    standalone wizard zip we ship next, so order matters.
  Expand-ZipOverwrite -Zip $BuildZip -Dest $KodiData

  # 2. Overlay the standalone wizard zip (always the latest version)
  #    on top of the build's internal copy so we don't ship a stale
  #    wizard.
  Expand-ZipOverwrite -Zip $WizardZip -Dest "$KodiData\addons"

  # 3. Register the wizard + its runtime imports (requests stack) as
  #    system addons. Without this Kodi treats them as disabled user
  #    addons and the wizard's xbmc.service never runs at boot.
  #    If the manifest path doesn't exist (Kodi installed somewhere
  #    unexpected), warn but don't fail -- the wizard will still
  #    appear under Add-ons and the user can enable it manually.
  $manifestPath = Join-Path $KodiSystem 'addon-manifest.xml'
  if (-not (Test-Path $manifestPath)) {
    Write-Host "WARNING: addon-manifest.xml not found at $manifestPath"
    Write-Host "Skipping system-addon registration. The wizard will be available"
    Write-Host "under Settings > Add-ons after the user enables it manually."
  } else {
    Write-Host "Registering system addons in $manifestPath"
    $xml = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8
    $systemAddons = @(
      'plugin.program.kodipovilwizard',
      'script.module.requests',
      'script.module.six',
      'script.module.certifi',
      'script.module.urllib3',
      'script.module.chardet',
      'script.module.idna'
    )
    foreach ($a in $systemAddons) {
      $needle = [regex]::Escape("<addon>$a</addon>")
      if ($xml -notmatch $needle) {
        $xml = $xml -replace '</addons>', "  <addon>$a</addon>`r`n</addons>"
        Write-Host "  + $a"
      } else {
        Write-Host "  = $a (already in manifest)"
      }
    }
    Set-Content -LiteralPath $manifestPath -Value $xml -Encoding UTF8 -NoNewline
  }

  Write-Host "Done. Kodi POV IL is ready to launch."
  try { Stop-Transcript | Out-Null } catch { }
  exit 0
}
catch {
  Write-Host "FATAL: $($_.Exception.Message)"
  Write-Host $_.ScriptStackTrace
  try { Stop-Transcript | Out-Null } catch { }
  exit 1
}
