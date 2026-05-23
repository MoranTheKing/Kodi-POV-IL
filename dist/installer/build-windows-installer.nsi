; Kodi POV IL -- Windows installer.
;
; Installs official Kodi silently, copies our wizard + build into
; %APPDATA%\Kodi\, registers the wizard as a system addon in Kodi's
; addon-manifest.xml (so it auto-runs on first launch), then launches
; Kodi. The wizard's startup.py opens its Builds menu immediately, so
; the user lands on the install-build page just like on the APK.
;
; Build: makensis -DVERSION=21.3-povil.6 build-windows-installer.nsi

!define APP_NAME "Kodi POV IL"
!ifndef VERSION
  !define VERSION "0.0.0"
!endif

Name "${APP_NAME} ${VERSION}"
OutFile "Kodi-POV-IL-Setup-${VERSION}.exe"
RequestExecutionLevel admin
SetCompressor /SOLID lzma
Unicode true
ShowInstDetails show

Page instfiles

Section "Install"
  ; Resolve $APPDATA to the *invoking* user's profile, not the
  ; elevated admin's. Without this, $APPDATA under UAC elevation
  ; points at C:\Users\Administrator\AppData\Roaming, which the user
  ; never sees when they later launch Kodi from their own account.
  SetShellVarContext current

  SetOutPath "$PLUGINSDIR"
  File "kodi-setup.exe"
  File "wizard.zip"
  File "build.zip"
  File "patch-kodi.ps1"

  ; PowerShell writes a transcript here so failures are diagnosable.
  StrCpy $1 "$TEMP\kodi-pov-il-setup.log"

  DetailPrint "Installing Kodi..."
  ExecWait '"$PLUGINSDIR\kodi-setup.exe" /S' $0
  StrCmp $0 "0" +3 0
    MessageBox MB_OK|MB_ICONSTOP "Kodi installer failed with exit code $0. Aborting."
    Abort

  DetailPrint "Preparing Kodi POV IL build..."
  ; PowerShell does the heavy lifting: extracts both zips into the
  ; Kodi data dir and patches addon-manifest.xml so the wizard is
  ; auto-enabled on first launch. PowerShell ships with Windows 5.1+
  ; so no extra plugins or downloads are needed.
  ;
  ; Use $PROGRAMFILES64 -- Kodi 21 only ships a 64-bit installer so
  ; it always lands in C:\Program Files\Kodi. NSIS itself is 32-bit
  ; here, so $PROGRAMFILES would wrongly resolve to "Program Files
  ; (x86)" and the manifest patch would fail.
  nsExec::ExecToLog 'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\patch-kodi.ps1" -KodiData "$APPDATA\Kodi" -KodiSystem "$PROGRAMFILES64\Kodi\system" -WizardZip "$PLUGINSDIR\wizard.zip" -BuildZip "$PLUGINSDIR\build.zip" -LogPath "$1"'
  Pop $0
  StrCmp $0 "0" +3 0
    MessageBox MB_OK|MB_ICONSTOP "PowerShell setup step failed (exit code $0).$\r$\nDetailed log: $1$\r$\nPlease send that file to support."
    Abort

  DetailPrint "Launching Kodi POV IL..."
  Exec '"$PROGRAMFILES64\Kodi\kodi.exe"'
SectionEnd
