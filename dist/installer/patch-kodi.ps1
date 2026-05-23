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
  [Parameter(Mandatory=$true)][string]$BuildZip
)
$ErrorActionPreference = 'Stop'

Write-Host "KodiData   = $KodiData"
Write-Host "KodiSystem = $KodiSystem"

# 1. Make sure the data dir exists. Kodi normally creates it on first
#    launch; we pre-create so we can drop the build into it now.
New-Item -ItemType Directory -Force -Path $KodiData            | Out-Null
New-Item -ItemType Directory -Force -Path "$KodiData\addons"   | Out-Null
New-Item -ItemType Directory -Force -Path "$KodiData\userdata" | Out-Null

# 2. Lay down the full FENtastic build first so all the supporting
#    addons (POV, FENtastic, script.module.* deps) and the seeded
#    userdata land in place. The build zip includes its own copy of
#    the wizard under addons/ -- that copy may be older than the
#    standalone wizard zip we ship next, so order matters.
Write-Host "Extracting full build zip into Kodi data..."
Expand-Archive -LiteralPath $BuildZip -DestinationPath $KodiData -Force

# 3. Overlay the standalone wizard zip (always the latest version)
#    on top of the build's internal copy so we don't ship a stale
#    wizard.
Write-Host "Overlaying standalone wizard..."
Expand-Archive -LiteralPath $WizardZip -DestinationPath "$KodiData\addons" -Force

# 4. Register the wizard + its runtime imports (requests stack) as
#    system addons. Without this Kodi treats them as disabled user
#    addons and the wizard's xbmc.service never runs at boot.
$manifestPath = Join-Path $KodiSystem 'addon-manifest.xml'
if (-not (Test-Path $manifestPath)) {
  throw "addon-manifest.xml not found at $manifestPath. Did Kodi install correctly?"
}
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

Write-Host "Done. Kodi POV IL is ready to launch."
