; Kodi POV IL -- Windows installer.
;
; Installs official Kodi silently into a separate "Kodi POV IL" program
; folder, extracts our wizard + build into portable_data, registers the wizard
; as a system addon in Kodi's addon-manifest.xml so it auto-runs on first
; launch, then launches Kodi with -p. This keeps Kodi POV IL independent from
; any normal Kodi install that uses %APPDATA%\Kodi.
;
; Design choices:
;   - Uses tar.exe (Windows 10 1803+) for zip extraction instead of
;     PowerShell. The three previous installer revisions all failed
;     with "PowerShell setup step failed (exit code -196608)" --
;     PowerShell was rejecting the -File path with "argument does not
;     exist" even though NSIS had just extracted the .ps1 there.
;     Either Defender was quarantining the .ps1, or kodi-setup.exe
;     (also NSIS-based) was clobbering the shared temp dir mid-run.
;     tar.exe is a system binary that AV won't touch.
;   - Manifest patching is done in pure NSIS via FileRead/FileWrite,
;     so the script has zero runtime dependencies beyond what's in
;     C:\Windows\System32 since Windows 10 1803.
;
; Build: makensis -DVERSION=21.3-povil.X build-windows-installer.nsi

!define APP_NAME "Kodi POV IL"
!ifndef VERSION
  !define VERSION "0.0.0"
!endif

Name "${APP_NAME} ${VERSION}"
OutFile "Kodi-POV-IL-Setup-${VERSION}.exe"
InstallDir "$PROGRAMFILES64\Kodi POV IL"
RequestExecutionLevel admin
SetCompressor /SOLID lzma
Unicode true
ShowInstDetails show

Page instfiles

; --------- Helper: find tar.exe on this machine -----------------------
; Returns path to tar.exe in $TarExe. WoW64 redirects $WINDIR\System32
; to SysWOW64 when called from a 32-bit installer, but tar.exe lives
; in the real System32. Sysnative is the WoW64 virtual alias that
; bypasses redirection.
Var TarExe

Function ResolveTar
  StrCpy $TarExe "$WINDIR\Sysnative\tar.exe"
  IfFileExists "$TarExe" tar_ok 0
  StrCpy $TarExe "$WINDIR\System32\tar.exe"
  IfFileExists "$TarExe" tar_ok 0
    MessageBox MB_OK|MB_ICONSTOP "tar.exe not found in System32/Sysnative. Windows 10 1803 or newer is required."
    Abort
  tar_ok:
FunctionEnd

; --------- Helper: register addons in addon-manifest.xml --------------
; Reads $INSTDIR\system\addon-manifest.xml line by line,
; copies to a temp file, and just before the closing </addons> tag
; inserts our system addon entries. The manifest has short lines so
; the 1024-char NSIS string limit isn't a concern. If the manifest
; isn't found we warn (via DetailPrint) and continue -- the wizard
; still ends up in %APPDATA%\Kodi\addons and the user can enable it
; manually under Settings > Add-ons.
Function PatchAddonManifest
  Push $0
  Push $1
  Push $2
  Push $3
  Push $4
  Push $5

  StrCpy $0 "$INSTDIR\system\addon-manifest.xml"
  IfFileExists "$0" 0 manifest_missing

  StrCpy $1 "$0.kpov-new"
  ClearErrors
  FileOpen $2 "$0" r
  IfErrors manifest_missing
  FileOpen $3 "$1" w
  IfErrors close_read

  read_loop:
    ClearErrors
    FileRead $2 $4
    IfErrors read_done

    ; Detect the closing </addons> line (allowing leading whitespace).
    Push $4
    Call TrimAndCompare
    Pop $5
    StrCmp $5 "</addons>" insert_before_close write_through

    insert_before_close:
      ; optional="true" on purpose: a non-optional manifest entry that
      ; Kodi fails to resolve makes CAddonMgr::Init() fail and Kodi
      ; exits before drawing anything. Optional system addons are still
      ; auto-enabled on first launch, but can never brick startup.
      FileWrite $3 '  <addon optional="true">plugin.program.kodipovilwizard</addon>$\r$\n'
      FileWrite $3 '  <addon optional="true">script.module.requests</addon>$\r$\n'
      FileWrite $3 '  <addon optional="true">script.module.six</addon>$\r$\n'
      FileWrite $3 '  <addon optional="true">script.module.certifi</addon>$\r$\n'
      FileWrite $3 '  <addon optional="true">script.module.urllib3</addon>$\r$\n'
      FileWrite $3 '  <addon optional="true">script.module.chardet</addon>$\r$\n'
      FileWrite $3 '  <addon optional="true">script.module.idna</addon>$\r$\n'
      ; All Subs Plus (service.subtitles.all_subs_plus, by burekas)
      ; imports these at module load. Without them registered as
      ; system addons they aren't enabled on first Kodi launch and
      ; the subtitle service crashes with an ImportError before the
      ; user has a chance to open settings. Both ship in the build
      ; under addons/, we just need to wire them in here.
      FileWrite $3 '  <addon optional="true">script.module.beautifulsoup4</addon>$\r$\n'
      FileWrite $3 '  <addon optional="true">script.common.plugin.cache</addon>$\r$\n'
      FileWrite $3 $4
      Goto read_loop

    write_through:
      FileWrite $3 $4
      Goto read_loop

  read_done:
  FileClose $3
  close_read:
  FileClose $2

  ; Replace original. Keep a backup in case the user wants to revert.
  Delete "$0.kpov-bak"
  Rename "$0" "$0.kpov-bak"
  Rename "$1" "$0"
  DetailPrint "Patched $0 (backup at $0.kpov-bak)"
  Goto done

  manifest_missing:
    DetailPrint "WARN: addon-manifest.xml not found at $0"
    DetailPrint "      Wizard will be available under Settings > Add-ons"
    DetailPrint "      after the user enables it manually."

  done:
  Pop $5
  Pop $4
  Pop $3
  Pop $2
  Pop $1
  Pop $0
FunctionEnd

; --------- Helper: trim whitespace + CRLF, push result ----------------
; Input on stack: a line possibly with leading spaces and trailing
; CR/LF. Output on stack: trimmed string.
Function TrimAndCompare
  Exch $R0   ; original line
  Push $R1
  Push $R2

  ; Strip leading whitespace (space/tab).
  trim_left:
    StrCpy $R1 $R0 1
    StrCmp $R1 " " 0 +3
      StrCpy $R0 $R0 "" 1
      Goto trim_left
    StrCmp $R1 "$\t" 0 +3
      StrCpy $R0 $R0 "" 1
      Goto trim_left

  ; Strip trailing CR/LF and whitespace.
  trim_right:
    StrLen $R2 $R0
    IntCmp $R2 0 trim_done
    IntOp $R2 $R2 - 1
    StrCpy $R1 $R0 1 $R2
    StrCmp $R1 "$\r" 0 +3
      StrCpy $R0 $R0 $R2
      Goto trim_right
    StrCmp $R1 "$\n" 0 +3
      StrCpy $R0 $R0 $R2
      Goto trim_right
    StrCmp $R1 " " 0 +3
      StrCpy $R0 $R0 $R2
      Goto trim_right
    StrCmp $R1 "$\t" 0 +3
      StrCpy $R0 $R0 $R2
      Goto trim_right

  trim_done:
  Pop $R2
  Pop $R1
  Exch $R0
FunctionEnd

Section "Install"
  ; Resolve $APPDATA to the *invoking* user's profile, not the
  ; elevated admin's. Without this, $APPDATA under UAC elevation
  ; points at C:\Users\Administrator\AppData\Roaming, which the user
  ; never sees when they later launch Kodi from their own account.
  SetShellVarContext current

  Call ResolveTar

  ; Stage payload files under a stable APPDATA subdir we control.
  ; Earlier revisions extracted into $PLUGINSDIR ($TEMP\nsXXXX.tmp)
  ; and PowerShell came up complaining the .ps1 path didn't exist --
  ; the file was vanishing between extraction and execution. APPDATA
  ; is a private user directory that AV is less likely to scrub.
  StrCpy $2 "$APPDATA\Kodi-POV-IL-Setup"
  RMDir /r "$2"
  CreateDirectory "$2"

  SetOutPath "$2"
  File "kodi-setup.exe"
  File "wizard.zip"
  File "build.zip"

  ; Pre-create Kodi POV IL's portable data dir (Kodi normally does this on
  ; first launch with -p; we need it now so the build can land in it). This is
  ; intentionally NOT %APPDATA%\Kodi, so official Kodi remains untouched.
  CreateDirectory "$INSTDIR"
  CreateDirectory "$INSTDIR\portable_data"
  CreateDirectory "$INSTDIR\portable_data\addons"
  CreateDirectory "$INSTDIR\portable_data\userdata"

  DetailPrint "Installing Kodi POV IL runtime..."
  ExecWait '"$2\kodi-setup.exe" /S /D=$INSTDIR' $0
  StrCmp $0 "0" +3 0
    MessageBox MB_OK|MB_ICONSTOP "Kodi installer failed with exit code $0. Aborting."
    Abort

  ; tar.exe -xf zip -C dest. libarchive (which backs tar.exe on
  ; Windows) handles standard .zip files natively since Win10 1803.
  ; -C changes to the destination dir before extracting; the zip
  ; already has the correct top-level structure (addons/, userdata/,
  ; etc.) so files land where Kodi expects.
  DetailPrint "Extracting Kodi POV IL build..."
  nsExec::ExecToLog '"$TarExe" -xf "$2\build.zip" -C "$INSTDIR\portable_data"'
  Pop $0
  StrCmp $0 "0" +3 0
    MessageBox MB_OK|MB_ICONSTOP "Build extraction failed (tar exit $0).$\r$\nStaging dir: $2"
    Abort

  DetailPrint "Overlaying latest wizard..."
  nsExec::ExecToLog '"$TarExe" -xf "$2\wizard.zip" -C "$INSTDIR\portable_data\addons"'
  Pop $0
  StrCmp $0 "0" +3 0
    MessageBox MB_OK|MB_ICONSTOP "Wizard extraction failed (tar exit $0).$\r$\nStaging dir: $2"
    Abort

  DetailPrint "Registering wizard in addon-manifest.xml..."
  Call PatchAddonManifest

  DetailPrint "Launching Kodi POV IL..."
  Exec '"$INSTDIR\kodi.exe" -p'

  ; Best-effort cleanup of the staging dir. Leaves nothing behind
  ; under APPDATA except the actual Kodi data tree.
  Delete "$2\kodi-setup.exe"
  Delete "$2\wizard.zip"
  Delete "$2\build.zip"
  RMDir "$2"
SectionEnd
