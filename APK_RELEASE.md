# APK Release

The Android APKs and Windows installer are now built automatically by the GitHub Actions workflow at `.github/workflows/build-apk.yml`.

For build instructions, keystore setup, and release procedures see **[APK_BUILD.md](APK_BUILD.md)**.

## Current State

- Android APKs (32-bit + 64-bit) are produced from the official Kodi 21.3 APK, rebranded to `org.xbmc.kodipovil`, and signed with the repo's keystore.
- Each APK ships with `plugin.program.kodipovilwizard` (plus its requests/six python deps) pre-bundled in `assets/` and registered as *optional* system addons. The full FENtastic build is intentionally NOT bundled into `assets/`: the build zip carries desktop copies of addons Kodi already ships inside the APK (e.g. `inputstream.adaptive` with a Windows-only `addon.xml`), and overwriting those broke Kodi startup (black screen). On first launch the wizard auto-downloads and installs the build into the user profile, exactly like a clean-Kodi wizard install.
- The Windows installer is an NSIS wrapper that installs the official Kodi 21.3 and drops the wizard zip into `%APPDATA%\Kodi\addons\packages\`.

## Download pages

After a successful build the following links go live:

- `downloads/android-tv/` — 32-bit ARM APK
- `downloads/android-phone/` — 64-bit ARM APK
- `downloads/windows/` — Windows installer

The wizard's `uservar.py` reads the version pointer files under `wizard/assets/kodi_version_auto_update/` so the in-app "update available" prompt fires whenever a new build is published.
