# Platform package release

The Android APKs, Windows installer and LG webOS IPK are built by
`.github/workflows/build-apk.yml`. For the release procedure and keystore
setup, see [APK_BUILD.md](APK_BUILD.md).

## Current package design

- Android 32-bit and 64-bit packages are based on official Kodi 21.3 and keep
  the stable application id `org.xbmc.povi`. The release workflow signs every
  version with the same repository keystore, so existing Kodi POV IL installs
  update in place and can coexist with official Kodi.
- Android launcher icons, the Android TV banner, Kodi media icons and launch
  splash are all generated from the canonical POV IL artwork. The workflow
  compares the final signed APK pixels with those sources and fails if upstream
  Kodi artwork returns.
- The Wizard and its pure-Python dependencies are bundled as optional system
  addons. The full FENtastic build is intentionally not copied into Android or
  webOS system assets: on first launch the Wizard installs it into the writable
  user profile.
- The Windows NSIS wrapper installs under `C:\Program Files\Kodi POV IL`.
  `portable_data` remains isolated from `%APPDATA%\Kodi`; updates protect and
  restore that directory, grant standard users Modify permission only there,
  overlay the current Wizard, and recreate branded `-p` shortcuts. A fresh
  profile is extracted and validated in an installer-owned sibling before one
  final rename; the application-release marker and addon manifest also use
  verified backup/replace flows. Kodi is not auto-launched from the elevated
  installer.
- The webOS package keeps app id `org.xbmc.kodi` for in-place updates. Its
  control file, `appinfo.json` and `packageinfo.json` all use the same numeric
  version (for example POV release `21.3-povil.48` becomes webOS `21.3.48`).
  The builder preserves original tar member order and metadata, changes only
  declared branding/manifest/version files, adds the Wizard dependencies, and
  performs an independent structural and byte-level verification.
- Every platform package carries `system/povil-release.txt`. Wizard 0.1.34+
  compares this complete release label with the public pointer instead of
  confusing it with Kodi's unchanged 21.3 core version.

## Download pages

After a successful release, these pages point at the stable latest assets:

- `downloads/android-tv/` — 32-bit ARM APK
- `downloads/android-phone/` — 64-bit ARM APK
- `downloads/windows/` — Windows installer
- `downloads/lg-tv/` — LG webOS IPK and current sideload instructions

The GitHub Pages deploy copies the two APKs to direct one-hop URLs for
Downloader. Windows and webOS use the stable GitHub Release filenames.

## Update behavior

- Android: install the new APK over the existing app. Never uninstall when the
  signing key and `org.xbmc.povi` id are unchanged.
- Windows: run the new setup once. It preserves `portable_data`, repairs its
  ACL and refreshes the POV IL shortcuts/icon.
- webOS: sideload the newer IPK over the existing app while Developer Mode is
  active. Keeping the same app id and a higher valid numeric version makes this
  an update rather than a second app.

The workflow opens a pointer-file PR after publishing a release. Merge that PR
only after all APK/EXE/IPK assets have been downloaded and verified.
