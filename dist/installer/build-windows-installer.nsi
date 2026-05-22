; Kodi POV IL — Windows installer wrapper.
;
; Runs the official Kodi 21.3 installer silently, then drops the
; wizard zip into Kodi's portable_data/userdata so the wizard is
; available on first launch. The build zip is also copied to the
; user's Downloads folder for manual install if needed.
;
; Build:  makensis -DVERSION=21.3-povil.1 installer.nsi
; Output: Kodi-POV-IL-Setup-${VERSION}.exe

!define APP_NAME "Kodi POV IL"
!ifndef VERSION
  !define VERSION "0.0.0"
!endif

Name "${APP_NAME} ${VERSION}"
OutFile "Kodi-POV-IL-Setup-${VERSION}.exe"
InstallDir "$LOCALAPPDATA\Kodi POV IL"
RequestExecutionLevel admin
SetCompressor /SOLID lzma
Unicode true

Page directory
Page instfiles

Section "Install"
  SetOutPath "$PLUGINSDIR"
  File "kodi-setup.exe"
  File "wizard.zip"
  File "build.zip"

  ; Run the official Kodi installer silently (NSIS-based, /S works)
  DetailPrint "Installing official Kodi..."
  ExecWait '"$PLUGINSDIR\kodi-setup.exe" /S' $0
  StrCmp $0 "0" kodi_ok kodi_fail
  kodi_fail:
    MessageBox MB_OK|MB_ICONSTOP "Kodi installer failed with exit code $0. Aborting."
    Abort
  kodi_ok:

  ; Locate Kodi's userdata folder. Default install puts it at:
  ;   %APPDATA%\Kodi\userdata
  StrCpy $1 "$APPDATA\Kodi"
  IfFileExists "$1\*.*" found_kodi
    MessageBox MB_OK|MB_ICONSTOP "Could not find Kodi at $1 after install."
    Abort
  found_kodi:

  ; Copy the wizard zip and build zip into Kodi's addons folder so
  ; the user can "Install from zip" without re-downloading.
  CreateDirectory "$1\addons\packages"
  CopyFiles /SILENT "$PLUGINSDIR\wizard.zip" "$1\addons\packages\plugin.program.kodipovilwizard.zip"
  CopyFiles /SILENT "$PLUGINSDIR\build.zip"  "$1\addons\packages\Kodi-POV-IL-FENtastic.zip"

  ; Drop a README on the desktop explaining the next step
  FileOpen $2 "$DESKTOP\Kodi POV IL - Next Step.txt" w
  FileWrite $2 "Kodi has been installed.$\r$\n$\r$\n"
  FileWrite $2 "To finish setting up Kodi POV IL:$\r$\n"
  FileWrite $2 "  1. Launch Kodi.$\r$\n"
  FileWrite $2 "  2. Go to Settings > Add-ons > Install from zip file.$\r$\n"
  FileWrite $2 "  3. Allow 'unknown sources' if prompted.$\r$\n"
  FileWrite $2 "  4. Navigate to:$\r$\n"
  FileWrite $2 "       %APPDATA%\Kodi\addons\packages\plugin.program.kodipovilwizard.zip$\r$\n"
  FileWrite $2 "  5. The wizard will start automatically.$\r$\n$\r$\n"
  FileWrite $2 "Source URL (if you ever need it):$\r$\n"
  FileWrite $2 "  https://morantheking.github.io/Kodi-POV-IL/$\r$\n"
  FileClose $2

  ; Run Kodi once so the user is taken straight into the next step
  ; if Kodi's launcher is registered.
  ;Exec '"$PROGRAMFILES\Kodi\kodi.exe"'
SectionEnd
