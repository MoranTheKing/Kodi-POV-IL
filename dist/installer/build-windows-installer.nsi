; Kodi POV IL -- Windows installer.
;
; Installs official Kodi silently into a separate "Kodi POV IL" program
; folder, extracts our wizard + build into portable_data, registers the wizard
; as a system addon in Kodi's addon-manifest.xml so it auto-runs on first
; launch, and creates branded shortcuts that always pass -p. This keeps Kodi
; POV IL independent from any normal Kodi install that uses %APPDATA%\Kodi.
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
!ifndef FILE_VERSION
  !define FILE_VERSION "0.0.0.0"
!endif

Name "${APP_NAME} ${VERSION}"
OutFile "Kodi-POV-IL-Setup-${VERSION}.exe"
InstallDir "$PROGRAMFILES64\Kodi POV IL"
RequestExecutionLevel admin
Icon "povil.ico"
SetCompressor /SOLID lzma
Unicode true
ShowInstDetails show
VIProductVersion "${FILE_VERSION}"
VIAddVersionKey /LANG=1033 "ProductName" "${APP_NAME}"
VIAddVersionKey /LANG=1033 "FileDescription" "${APP_NAME} installer"
VIAddVersionKey /LANG=1033 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "LegalCopyright" "Kodi is a trademark of the XBMC Foundation; POV IL package maintained by MoranTheKing"

Page instfiles

; --------- Helper: find tar.exe on this machine -----------------------
; Returns path to tar.exe in $TarExe. WoW64 redirects $WINDIR\System32
; to SysWOW64 when called from a 32-bit installer, but tar.exe lives
; in the real System32. Sysnative is the WoW64 virtual alias that
; bypasses redirection.
Var TarExe
Var ExistingProfile
Var PortableBackup
Var ProfileBackedUp
Var FreshProfileStage
Var ProfileTarget

Function ResolveTar
  StrCpy $TarExe "$WINDIR\Sysnative\tar.exe"
  IfFileExists "$TarExe" tar_ok 0
  StrCpy $TarExe "$WINDIR\System32\tar.exe"
  IfFileExists "$TarExe" tar_ok 0
    MessageBox MB_OK|MB_ICONSTOP "tar.exe not found in System32/Sysnative. Windows 10 1803 or newer is required."
    Abort
  tar_ok:
FunctionEnd

; --------- Helper: make only portable_data writable --------------------
; Kodi portable mode stores databases, settings, thumbnails and logs below
; the application folder. Program Files is read-only for standard users, so
; the application appeared to work only when launched as Administrator.
; Grant Modify to the locale-independent Builtin Users SID, recursively, on
; portable_data only. The runtime binaries remain protected.
Function GrantPortableDataAccess
  Push $0
  DetailPrint "Granting standard-user access to portable_data..."
  nsExec::ExecToLog '"$SYSDIR\icacls.exe" "$INSTDIR\portable_data" /inheritance:e /grant "*S-1-5-32-545:(OI)(CI)M" /T /C /Q'
  Pop $0
  StrCmp $0 "0" access_ok 0
    MessageBox MB_OK|MB_ICONSTOP "Could not grant write access to:$\r$\n$INSTDIR\portable_data$\r$\n$\r$\nicacls exit code: $0$\r$\nKodi POV IL would not run correctly as a standard user, so setup has stopped."
    Abort
  access_ok:
  Pop $0
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
  Push $6

  StrCpy $0 "$INSTDIR\system\addon-manifest.xml"
  IfFileExists "$0" 0 manifest_missing

  StrCpy $1 "$0.kpov-new"
  Delete "$1"
  ClearErrors
  FileOpen $2 "$0" r
  IfErrors manifest_read_failed
  ClearErrors
  FileOpen $3 "$1" w
  IfErrors manifest_output_open_failed
  StrCpy $6 "0"

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
      IntOp $6 $6 + 1
      ; optional="true" on purpose: a non-optional manifest entry that
      ; Kodi fails to resolve makes CAddonMgr::Init() fail and Kodi
      ; exits before drawing anything. Optional system addons are still
      ; auto-enabled on first launch, but can never brick startup.
      ClearErrors
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
      IfErrors manifest_write_failed
      Goto read_loop

    write_through:
      ClearErrors
      FileWrite $3 $4
      IfErrors manifest_write_failed
      Goto read_loop

  read_done:
  ClearErrors
  FileClose $3
  IfErrors manifest_output_close_failed
  ClearErrors
  FileClose $2
  IfErrors manifest_input_close_failed

  ; A missing or duplicate closing tag means the source was malformed. Never
  ; replace it with a generated file whose structure we could not prove.
  StrCmp $6 "1" manifest_ready manifest_structure_failed

  manifest_ready:
  ; Replace only after every read/write/close check passed. Keep the original
  ; recoverable until the generated file is in its final location.
  Delete "$0.kpov-bak"
  ClearErrors
  Rename "$0" "$0.kpov-bak"
  IfErrors manifest_backup_rename_failed
  ClearErrors
  Rename "$1" "$0"
  IfErrors manifest_install_rename_failed
  DetailPrint "Patched $0 (backup at $0.kpov-bak)"
  Goto done

  manifest_install_rename_failed:
    ; The original is currently in .kpov-bak. Restore it before stopping.
    ClearErrors
    Rename "$0.kpov-bak" "$0"
    IfErrors manifest_restore_failed
    Delete "$1"
    MessageBox MB_OK|MB_ICONSTOP "Could not install the updated addon manifest. The original manifest was restored and setup has stopped."
    Abort

  manifest_restore_failed:
    MessageBox MB_OK|MB_ICONSTOP "Could not install or automatically restore addon-manifest.xml.$\r$\n$\r$\nYour original is safe at:$\r$\n$0.kpov-bak$\r$\nThe generated copy is at:$\r$\n$1$\r$\n$\r$\nSetup has stopped without deleting either copy."
    Abort

  manifest_backup_rename_failed:
    Delete "$1"
    MessageBox MB_OK|MB_ICONSTOP "Could not protect the existing addon-manifest.xml before replacement. The original was left untouched and setup has stopped."
    Abort

  manifest_write_failed:
    FileClose $3
    FileClose $2
    Delete "$1"
    MessageBox MB_OK|MB_ICONSTOP "Could not write the updated addon-manifest.xml. The original was left untouched and setup has stopped."
    Abort

  manifest_output_close_failed:
    FileClose $2
    Delete "$1"
    MessageBox MB_OK|MB_ICONSTOP "Could not finish writing the updated addon-manifest.xml. The original was left untouched and setup has stopped."
    Abort

  manifest_input_close_failed:
    Delete "$1"
    MessageBox MB_OK|MB_ICONSTOP "Could not finish reading addon-manifest.xml. The original was left untouched and setup has stopped."
    Abort

  manifest_structure_failed:
    Delete "$1"
    MessageBox MB_OK|MB_ICONSTOP "addon-manifest.xml did not contain exactly one closing </addons> tag. The original was left untouched and setup has stopped."
    Abort

  manifest_output_open_failed:
    FileClose $2
    Delete "$1"
    MessageBox MB_OK|MB_ICONSTOP "Could not create a temporary addon manifest beside:$\r$\n$0$\r$\n$\r$\nThe original was left untouched and setup has stopped."
    Abort

  manifest_read_failed:
    MessageBox MB_OK|MB_ICONSTOP "Could not read:$\r$\n$0$\r$\n$\r$\nThe original was left untouched and setup has stopped."
    Abort

  manifest_missing:
    DetailPrint "WARN: addon-manifest.xml not found at $0"
    DetailPrint "      Wizard will be available under Settings > Add-ons"
    DetailPrint "      after the user enables it manually."

  done:
  Pop $6
  Pop $5
  Pop $4
  Pop $3
  Pop $2
  Pop $1
  Pop $0
FunctionEnd

; --------- Helper: write release marker transactionally ----------------
; A missing marker makes Wizard .34 treat the package as legacy .47 and offer
; .48 again forever. Verify the generated contents, protect an existing marker
; and restore it if the final rename fails.
Function WriteReleaseMarker
  Push $0
  Push $1
  Push $2
  Push $3
  Push $4
  Push $5

  StrCpy $0 "$INSTDIR\system\povil-release.txt"
  StrCpy $1 "$0.kpov-new"
  StrCpy $2 "$0.kpov-bak"
  StrCpy $5 "0"
  Delete "$1"

  ClearErrors
  FileOpen $3 "$1" w
  IfErrors marker_open_failed
  ClearErrors
  FileWrite $3 "${VERSION}$\r$\n"
  IfErrors marker_write_failed
  ClearErrors
  FileClose $3
  IfErrors marker_close_failed

  ; Read the temporary file back before it can replace anything.
  ClearErrors
  FileOpen $3 "$1" r
  IfErrors marker_verify_open_failed
  ClearErrors
  FileRead $3 $4
  IfErrors marker_verify_read_failed
  ClearErrors
  FileClose $3
  IfErrors marker_verify_close_failed
  StrCmp $4 "${VERSION}$\r$\n" marker_verified marker_verify_content_failed

  marker_verified:
  IfFileExists "$0" marker_backup_existing marker_install_new
  marker_backup_existing:
    Delete "$2"
    ClearErrors
    Rename "$0" "$2"
    IfErrors marker_backup_failed
    StrCpy $5 "1"

  marker_install_new:
    ClearErrors
    Rename "$1" "$0"
    IfErrors marker_install_failed
    DetailPrint "Wrote verified release marker: $0"
    Goto marker_done

  marker_install_failed:
    StrCmp $5 "1" marker_restore_existing marker_install_failed_without_backup
  marker_restore_existing:
    ClearErrors
    Rename "$2" "$0"
    IfErrors marker_restore_failed
    Delete "$1"
    MessageBox MB_OK|MB_ICONSTOP "Could not install the new release marker. The previous marker was restored and setup has stopped."
    Abort
  marker_install_failed_without_backup:
    Delete "$1"
    MessageBox MB_OK|MB_ICONSTOP "Could not install the new release marker. No existing marker was changed; setup has stopped."
    Abort
  marker_restore_failed:
    MessageBox MB_OK|MB_ICONSTOP "Could not install or automatically restore the release marker.$\r$\n$\r$\nThe previous marker is safe at:$\r$\n$2$\r$\nThe generated marker is at:$\r$\n$1$\r$\n$\r$\nSetup has stopped without deleting either copy."
    Abort
  marker_backup_failed:
    Delete "$1"
    MessageBox MB_OK|MB_ICONSTOP "Could not protect the existing release marker before replacement. It was left untouched and setup has stopped."
    Abort
  marker_write_failed:
    FileClose $3
    Delete "$1"
    MessageBox MB_OK|MB_ICONSTOP "Could not write the release marker. Setup has stopped."
    Abort
  marker_close_failed:
    Delete "$1"
    MessageBox MB_OK|MB_ICONSTOP "Could not finish writing the release marker. Setup has stopped."
    Abort
  marker_verify_open_failed:
    Delete "$1"
    MessageBox MB_OK|MB_ICONSTOP "Could not reopen the generated release marker for verification. Setup has stopped."
    Abort
  marker_verify_read_failed:
    FileClose $3
    Delete "$1"
    MessageBox MB_OK|MB_ICONSTOP "Could not read back the generated release marker. Setup has stopped."
    Abort
  marker_verify_close_failed:
    Delete "$1"
    MessageBox MB_OK|MB_ICONSTOP "Could not finish verifying the generated release marker. Setup has stopped."
    Abort
  marker_verify_content_failed:
    Delete "$1"
    MessageBox MB_OK|MB_ICONSTOP "The generated release marker did not match ${VERSION}. Setup has stopped."
    Abort
  marker_open_failed:
    MessageBox MB_OK|MB_ICONSTOP "Could not create the release marker beside:$\r$\n$0$\r$\n$\r$\nSetup has stopped."
    Abort

  marker_done:
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

  StrCpy $ExistingProfile "0"
  StrCpy $ProfileBackedUp "0"
  StrCpy $PortableBackup "$PROGRAMFILES64\Kodi POV IL.portable_data-backup"
  StrCpy $FreshProfileStage "$PROGRAMFILES64\Kodi POV IL.portable_data-new"

  ; Recover automatically if a previous setup was interrupted after moving
  ; the profile out of the official Kodi installer's reach.
  IfFileExists "$PortableBackup" 0 backup_recovery_done
    IfFileExists "$INSTDIR\portable_data" backup_conflict 0
      CreateDirectory "$INSTDIR"
      ClearErrors
      Rename "$PortableBackup" "$INSTDIR\portable_data"
      IfErrors backup_recovery_failed 0
      DetailPrint "Recovered portable_data from an interrupted setup."
      Goto backup_recovery_done
    backup_conflict:
      MessageBox MB_OK|MB_ICONSTOP "Setup found both the live profile and a recovery profile:$\r$\n$INSTDIR\portable_data$\r$\n$PortableBackup$\r$\n$\r$\nNothing was deleted. Please keep both folders and contact support."
      Abort
    backup_recovery_failed:
      MessageBox MB_OK|MB_ICONSTOP "Could not restore the recovery profile from:$\r$\n$PortableBackup$\r$\n$\r$\nNothing was deleted. Setup has stopped."
      Abort
  backup_recovery_done:

  ; Best effort: updates are often launched by the wizard from inside Kodi.
  ; Stop the running process before moving the live profile or replacing the
  ; runtime. A missing process returns a non-zero code and is harmless.
  nsExec::ExecToLog '"$SYSDIR\taskkill.exe" /F /IM kodi.exe'
  Pop $0
  Sleep 500

  ; This sibling is installer-owned and never a live user profile. Removing a
  ; leftover here makes an interrupted fresh extraction retry from a clean
  ; build instead of being mistaken for an existing installation.
  RMDir /r "$FreshProfileStage"
  IfFileExists "$FreshProfileStage" fresh_stage_cleanup_failed 0
  Goto fresh_stage_cleanup_done
  fresh_stage_cleanup_failed:
    MessageBox MB_OK|MB_ICONSTOP "Could not clean the interrupted fresh-install staging profile:$\r$\n$FreshProfileStage$\r$\n$\r$\nSetup has stopped without touching the live profile."
    Abort
  fresh_stage_cleanup_done:

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

  ; Preserve every existing portable setting/addon before invoking the
  ; upstream installer. Its uninstaller is allowed to replace $INSTDIR, so
  ; keeping the profile inside that tree during an update risks data loss.
  IfFileExists "$INSTDIR\portable_data" profile_exists profile_backup_done
  profile_exists:
    StrCpy $ExistingProfile "1"
    ClearErrors
    Rename "$INSTDIR\portable_data" "$PortableBackup"
    IfErrors profile_backup_failed 0
    StrCpy $ProfileBackedUp "1"
    DetailPrint "Protected the existing portable_data profile during update."
    Goto profile_backup_done
  profile_backup_failed:
    MessageBox MB_OK|MB_ICONSTOP "Kodi POV IL's existing profile is still in use or could not be protected:$\r$\n$INSTDIR\portable_data$\r$\n$\r$\nClose Kodi and run setup again. Nothing was deleted."
    Abort
  profile_backup_done:

  DetailPrint "Installing Kodi POV IL runtime..."
  ExecWait '"$2\kodi-setup.exe" /S /D=$INSTDIR' $0
  StrCmp $0 "0" runtime_installed 0
    StrCmp $ProfileBackedUp "1" runtime_failure_restore runtime_install_failed
    runtime_failure_restore:
      IfFileExists "$INSTDIR\portable_data" runtime_failure_restore_conflict 0
      CreateDirectory "$INSTDIR"
      ClearErrors
      Rename "$PortableBackup" "$INSTDIR\portable_data"
      IfErrors runtime_failure_restore_failed 0
      StrCpy $ProfileBackedUp "0"
      MessageBox MB_OK|MB_ICONSTOP "Kodi installer failed with exit code $0. Your existing portable_data profile was restored; setup has stopped."
      Abort
    runtime_failure_restore_conflict:
      MessageBox MB_OK|MB_ICONSTOP "Kodi installer failed with exit code $0 and left a portable_data directory behind.$\r$\n$\r$\nYour original profile is safe at:$\r$\n$PortableBackup$\r$\nThe installer's partial directory is at:$\r$\n$INSTDIR\portable_data$\r$\n$\r$\nNothing was deleted. Setup has stopped."
      Abort
    runtime_failure_restore_failed:
      MessageBox MB_OK|MB_ICONSTOP "Kodi installer failed with exit code $0, and setup could not restore the original profile automatically.$\r$\n$\r$\nYour original profile is safe at:$\r$\n$PortableBackup$\r$\n$\r$\nSetup has stopped."
      Abort
    runtime_install_failed:
    MessageBox MB_OK|MB_ICONSTOP "Kodi installer failed with exit code $0. Aborting."
    Abort
  runtime_installed:

  ; Restore an existing profile after the runtime is safely in place.
  StrCmp $ProfileBackedUp "1" 0 profile_restored
    IfFileExists "$INSTDIR\portable_data" restore_target_conflict 0
    ClearErrors
    Rename "$PortableBackup" "$INSTDIR\portable_data"
    IfErrors restore_failed 0
    StrCpy $ProfileBackedUp "0"
    DetailPrint "Restored the existing portable_data profile."
    Goto profile_restored
  restore_target_conflict:
    MessageBox MB_OK|MB_ICONSTOP "The Kodi runtime unexpectedly created a portable_data profile. Your original profile is safe at:$\r$\n$PortableBackup$\r$\n$\r$\nSetup has stopped without overwriting either copy."
    Abort
  restore_failed:
    MessageBox MB_OK|MB_ICONSTOP "Could not restore your profile. It is safe at:$\r$\n$PortableBackup$\r$\n$\r$\nSetup has stopped."
    Abort
  profile_restored:

  ; tar.exe -xf zip -C dest. For an update, preserve the complete existing
  ; profile and overlay only the current wizard. A fresh build is extracted
  ; completely into an installer-owned sibling and becomes live by one rename;
  ; a failed/partial extraction can therefore never look like an existing
  ; profile on the next retry.
  StrCmp $ExistingProfile "1" existing_profile_target fresh_profile_target
  existing_profile_target:
    CreateDirectory "$INSTDIR\portable_data"
    CreateDirectory "$INSTDIR\portable_data\addons"
    CreateDirectory "$INSTDIR\portable_data\userdata"
    StrCpy $ProfileTarget "$INSTDIR\portable_data"
    DetailPrint "Existing profile detected; preserving settings and build data."
    Goto profile_target_ready

  fresh_profile_target:
    CreateDirectory "$FreshProfileStage"
    CreateDirectory "$FreshProfileStage\addons"
    CreateDirectory "$FreshProfileStage\userdata"
    StrCpy $ProfileTarget "$FreshProfileStage"
    DetailPrint "Extracting Kodi POV IL build into a fresh staging profile..."
    nsExec::ExecToLog '"$TarExe" -xf "$2\build.zip" -C "$FreshProfileStage"'
    Pop $0
    StrCmp $0 "0" fresh_build_extracted 0
      RMDir /r "$FreshProfileStage"
      MessageBox MB_OK|MB_ICONSTOP "Build extraction failed (tar exit $0). The partial fresh-install staging profile was removed; setup has stopped."
      Abort
    fresh_build_extracted:
    ; These are real payload anchors from build .101. Checking the directories
    ; would be tautological because setup creates them before extraction.
    IfFileExists "$FreshProfileStage\addons\skin.fentastic\addon.xml" 0 fresh_build_invalid
    IfFileExists "$FreshProfileStage\userdata\guisettings.xml" profile_target_ready fresh_build_invalid
    fresh_build_invalid:
      RMDir /r "$FreshProfileStage"
      MessageBox MB_OK|MB_ICONSTOP "The build archive did not create the required addons and userdata directories. The incomplete staging profile was removed; setup has stopped."
      Abort

  profile_target_ready:

  DetailPrint "Overlaying latest wizard..."
  nsExec::ExecToLog '"$TarExe" -xf "$2\wizard.zip" -C "$ProfileTarget\addons"'
  Pop $0
  StrCmp $0 "0" wizard_extracted 0
    StrCmp $ExistingProfile "0" 0 wizard_extract_failed
      RMDir /r "$FreshProfileStage"
    wizard_extract_failed:
    MessageBox MB_OK|MB_ICONSTOP "Wizard extraction failed (tar exit $0). Setup has stopped."
    Abort
  wizard_extracted:
  IfFileExists "$ProfileTarget\addons\plugin.program.kodipovilwizard\addon.xml" wizard_verified 0
    StrCmp $ExistingProfile "0" 0 wizard_verify_failed
      RMDir /r "$FreshProfileStage"
    wizard_verify_failed:
    MessageBox MB_OK|MB_ICONSTOP "The Wizard archive did not contain its expected addon.xml. Setup has stopped."
    Abort
  wizard_verified:

  ; Make a complete fresh profile live only after both archives verified.
  StrCmp $ExistingProfile "1" profile_live 0
    IfFileExists "$INSTDIR\portable_data" fresh_profile_target_conflict 0
    ClearErrors
    Rename "$FreshProfileStage" "$INSTDIR\portable_data"
    IfErrors fresh_profile_publish_failed 0
    StrCpy $ProfileTarget "$INSTDIR\portable_data"
    Goto profile_live
  fresh_profile_target_conflict:
    MessageBox MB_OK|MB_ICONSTOP "The Kodi runtime unexpectedly created a portable_data directory during the fresh install.$\r$\n$\r$\nThe complete new profile is safe at:$\r$\n$FreshProfileStage$\r$\nThe unexpected directory is at:$\r$\n$INSTDIR\portable_data$\r$\n$\r$\nNothing was deleted. Setup has stopped."
    Abort
  fresh_profile_publish_failed:
    MessageBox MB_OK|MB_ICONSTOP "Could not make the completed fresh profile live. It is safe at:$\r$\n$FreshProfileStage$\r$\n$\r$\nSetup has stopped."
    Abort
  profile_live:

  DetailPrint "Registering wizard in addon-manifest.xml..."
  Call PatchAddonManifest

  ; Install the shared POV icon after the upstream runtime so updates cannot
  ; replace it. Also write the package-specific release marker consumed by
  ; Wizard .34+; Kodi's core version alone cannot distinguish POV releases.
  SetOutPath "$INSTDIR"
  ClearErrors
  File "/oname=povil.ico" "povil.ico"
  IfErrors icon_install_failed
  IfFileExists "$INSTDIR\povil.ico" icon_installed icon_install_failed
  icon_install_failed:
    MessageBox MB_OK|MB_ICONSTOP "Could not install the Kodi POV IL icon. Setup has stopped."
    Abort
  icon_installed:
  Call WriteReleaseMarker

  Call GrantPortableDataAccess

  ; --- Shortcuts that ALWAYS launch portable mode (-p) -------------------
  ; THE relaunch bug: the only launch that used -p was the Exec below, which
  ; runs once at install time. Kodi's own bundled setup (run silently above)
  ; leaves a plain "Kodi" entry that starts kodi.exe WITHOUT -p, so every
  ; later launch opened vanilla Kodi on %APPDATA%\Kodi -- no build, no skin
  ; ("works great the first time, empty after you close and reopen"). Create
  ; clearly named POV IL shortcuts that pass -p and carry the custom icon.
  ; Create both the invoking user's copy (repairs old .47 shortcuts) and a
  ; public copy for other standard users on the machine. We never delete or
  ; repoint a separately-installed normal Kodi shortcut.
  DetailPrint "Creating branded Kodi POV IL shortcuts (portable -p)..."
  SetShellVarContext current
  CreateShortCut "$DESKTOP\Kodi POV IL.lnk" "$INSTDIR\kodi.exe" "-p" "$INSTDIR\povil.ico" 0
  CreateDirectory "$SMPROGRAMS\Kodi POV IL"
  CreateShortCut "$SMPROGRAMS\Kodi POV IL\Kodi POV IL.lnk" "$INSTDIR\kodi.exe" "-p" "$INSTDIR\povil.ico" 0
  SetShellVarContext all
  CreateShortCut "$DESKTOP\Kodi POV IL.lnk" "$INSTDIR\kodi.exe" "-p" "$INSTDIR\povil.ico" 0
  CreateDirectory "$SMPROGRAMS\Kodi POV IL"
  CreateShortCut "$SMPROGRAMS\Kodi POV IL\Kodi POV IL.lnk" "$INSTDIR\kodi.exe" "-p" "$INSTDIR\povil.ico" 0

  ; Best-effort cleanup of the staging dir. Leaves nothing behind
  ; under APPDATA except the actual Kodi data tree.
  Delete "$2\kodi-setup.exe"
  Delete "$2\wizard.zip"
  Delete "$2\build.zip"
  RMDir "$2"

  MessageBox MB_OK|MB_ICONINFORMATION "Kodi POV IL ${VERSION} was installed successfully.$\r$\n$\r$\nOpen it from the Kodi POV IL desktop or Start-menu shortcut. Kodi will run as your normal Windows user; do not use Run as administrator."
SectionEnd
