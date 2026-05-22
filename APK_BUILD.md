# Building the APK and Windows installer

The `.github/workflows/build-apk.yml` workflow produces signed Android APKs (32-bit + 64-bit) and a Windows installer for `Kodi POV IL`. It is triggered manually (`workflow_dispatch`).

The Android build does **not** compile Kodi from source. It downloads the official Kodi 21.3 APK from `mirrors.kodi.tv`, decompiles it with `apktool`, rebrands the package id to `org.xbmc.kodipovil`, bundles the wizard + POV-IL build into `assets/`, and re-signs with our keystore. End result: an APK that installs side-by-side with the official Kodi (Play Store / kodi.tv) and that on first launch already has the wizard and build loaded.

The Windows installer is a small NSIS wrapper that runs the official Kodi 21.3 setup, drops the wizard and build zips into the user's `%APPDATA%\Kodi\addons\packages\`, and leaves a `Next Step.txt` on the desktop.

## One-time setup

Before you can run the workflow you need to:

1. Generate a signing keystore (this is permanent — losing it forces every user to uninstall before installing future versions).
2. Add four repository secrets so the workflow can sign the APK.
3. Adjust branch protection so the `publish` job is allowed to push to `main` (the job commits the built artifacts back to `apk/` and `windows/`).

### 1. Generate the keystore

Run this on your own machine (Linux / macOS / WSL):

```bash
keytool -genkey -v \
  -keystore release.keystore \
  -alias kodipovil \
  -keyalg RSA \
  -keysize 2048 \
  -validity 10000 \
  -storepass 'CHANGE_ME_STRONG_PASSWORD' \
  -keypass  'CHANGE_ME_STRONG_PASSWORD' \
  -dname 'CN=Kodi POV IL, O=MoranTheKing, C=IL'
```

The `-validity 10000` value is the number of days the certificate is valid (~27 years). Keep the resulting `release.keystore` file in a safe place outside the repo. **Treat it like a password — if it leaks, anyone can ship a malicious update that overrides your real one.**

### 2. Encode the keystore and add the secrets

```bash
base64 -w0 release.keystore > keystore.b64   # Linux
# macOS: base64 -i release.keystore -o keystore.b64
cat keystore.b64
```

Copy the printed text (long base64 blob).

In the repo on GitHub:

- `Settings → Secrets and variables → Actions → New repository secret`
- Add **four** secrets:
  - `KEYSTORE_B64` — the base64 blob from the command above.
  - `KEYSTORE_PASSWORD` — whatever you put in `-storepass`.
  - `KEY_ALIAS` — `kodipovil` (or whatever you put in `-alias`).
  - `KEY_PASSWORD` — whatever you put in `-keypass` (usually the same as `KEYSTORE_PASSWORD`).

### 3. Allow the workflow to push artifacts

The `publish` job needs to commit the built APKs to `apk/`. By default a repo with branch protection on `main` blocks the workflow's automated push.

`Settings → Branches → main → Edit rule`:

- Either temporarily disable "Require a pull request before merging" while the workflow runs, or
- Add `github-actions[bot]` to the allowed bypass list.

If you prefer to keep protection strict, change the `publish` job in the workflow to open a PR instead — ask Claude and it'll switch the workflow to that mode.

## Running the build

`Actions → "Build APK and Windows installer" → Run workflow`.

Inputs:

- `version` — visible version label, e.g. `21.3-povil.1`. Bump this each release.
- `version_code` — Android `versionCode` integer. Must strictly increase between releases or Android will refuse to update. Suggested format: `<KodiVersionWithoutDots><build>` (e.g. `21301`).
- `kodi_version` — upstream Kodi version to rebrand. Default `21.3`. Don't change unless Kodi released a new minor and you want to base on it.

The run takes ~5-15 minutes. The two Android jobs (`armeabi-v7a` + `arm64-v8a`) run in parallel.

On success the `publish` job commits to `main`:

- `apk/Kodi-POV-IL-<version>-32bit.apk`
- `apk/Kodi-POV-IL-<version>-64bit.apk`
- `windows/Kodi-POV-IL-Setup-<version>.exe`
- `wizard/assets/kodi_version_auto_update/apk/latest_apk_version.txt`
- `wizard/assets/kodi_version_auto_update/windows/latest_windows_version.txt`

The `downloads/android-*/index.html` pages already point at these paths, so they go live automatically.

## After the first successful build — register the Downloader code

`Kodi POV IL` is wired to use the AFTVnews Downloader (the orange app on Fire TV / Android TV). To register a numeric code:

1. After the workflow finishes and the APKs are on `main`, visit `https://www.aftvnews.com/downloader/`.
2. Submit the public download URL — pick the page (not the direct file), e.g.:
   `https://github.com/MoranTheKing/Kodi-POV-IL/raw/main/apk/`
   or, if you'd rather give them the direct 64-bit APK URL:
   `https://github.com/MoranTheKing/Kodi-POV-IL/raw/main/apk/Kodi-POV-IL-21.3-povil.1-64bit.apk`
3. The site returns a short numeric code (kodi7rd's is `864332`).
4. Tell Claude the code; the wizard's `uservar.py` will be updated and the in-app "update" dialog will start showing this code to users.

Once the wizard has a real `APK_DOWNLOADER_CODE`, the in-Kodi flow "open Downloader app → type code" works exactly like the kodi7rd Twilight/POV builds.

## Known limitations of the apktool rebrand

This workflow rebrands the official Kodi APK rather than rebuilding from source. That is fast (minutes vs hours) but a few edge cases can show up:

- Some Kodi screens (mainly system info) may still show file paths under `org.xbmc.kodi` instead of `org.xbmc.kodipovil`. Cosmetic only.
- If Kodi's Java/Kotlin code hard-codes its content provider authority anywhere outside the manifest, that flow may misbehave. None of the common paths (playback, addons, scrapers) are known to do this, but if you spot something broken, that's the first place to look.

If apktool-rebrand turns out to be too lossy, the workflow can be swapped to a from-source xbmc/xbmc build later. The trade-off is build time (45-90 min per architecture) and CI disk-space pressure.
