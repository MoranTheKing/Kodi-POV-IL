# Building the APK and Windows installer

The `.github/workflows/build-apk.yml` workflow produces signed Android APKs (32-bit + 64-bit) and a Windows installer for `Kodi POV IL`, and attaches them to a GitHub Release. It is triggered manually (`workflow_dispatch`).

The Android build does **not** compile Kodi from source. It downloads the official Kodi 21.3 APK from `mirrors.kodi.tv`, decompiles it with `apktool`, rebrands the package id to `org.xbmc.kodipovil`, bundles the wizard + POV-IL build into `assets/`, and re-signs with our keystore. End result: an APK that installs side-by-side with the official Kodi (Play Store / kodi.tv) and that on first launch already has the wizard and build loaded.

The Windows installer is a small NSIS wrapper that runs the official Kodi 21.3 setup, drops the wizard and build zips into the user's `%APPDATA%\Kodi\addons\packages\`, and leaves a `Next Step.txt` on the desktop.

The workflow uses **no third-party GitHub Actions** (it does everything with apt-installed tooling and the preinstalled `gh` CLI), so the repo's restrictive "Actions permissions" policy doesn't block it.

## One-time setup

1. Generate a signing keystore (this is permanent — losing it forces every user to uninstall before installing future versions).
2. Add four repository secrets so the workflow can sign the APK.

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

`-validity 10000` ≈ 27 years. Keep the resulting `release.keystore` **outside** the repo. Treat it like a password — if it leaks, anyone can ship a malicious update that overrides yours.

### 2. Encode the keystore and add the secrets

```bash
base64 -w0 release.keystore > keystore.b64   # Linux
# macOS: base64 -i release.keystore -o keystore.b64
cat keystore.b64
```

Copy the printed text.

In the repo on GitHub: `Settings → Secrets and variables → Actions → New repository secret`. Add **four** secrets:

- `KEYSTORE_B64` — the base64 blob.
- `KEYSTORE_PASSWORD` — whatever you put in `-storepass`.
- `KEY_ALIAS` — `kodipovil` (or whatever you put in `-alias`).
- `KEY_PASSWORD` — whatever you put in `-keypass` (usually the same as `KEYSTORE_PASSWORD`).

## Running the build

`Actions → "Build APK and Windows installer" → Run workflow`.

Inputs:

- `version` — visible version label, e.g. `21.3-povil.1`. Becomes the release tag `v21.3-povil.1`.
- `version_code` — Android `versionCode` integer. Must strictly increase between releases. Suggested: `<KodiVersionWithoutDots><build>` (e.g. `21301`).
- `kodi_version` — upstream Kodi to rebrand. Default `21.3`.

The run takes ~5-15 minutes (single job, sequential 32-bit then 64-bit build, then Windows installer).

## What the workflow publishes

A GitHub Release tagged `v<version>` with the following assets:

- `Kodi-POV-IL-<version>-32bit.apk` and `Kodi-POV-IL-32bit.apk` (stable filename for "latest" redirect)
- `Kodi-POV-IL-<version>-64bit.apk` and `Kodi-POV-IL-64bit.apk`
- `Kodi-POV-IL-Setup-<version>.exe` and `Kodi-POV-IL-Setup.exe`

The download pages already link to the stable filenames via the
`/releases/latest/download/<name>` redirect, so users always get the
latest release without you having to update the HTML.

The workflow also opens a PR titled "Publish APK <version> pointer files"
that bumps `wizard/assets/kodi_version_auto_update/{apk,windows}/latest_*.txt`.
Merging that PR is what makes the in-Kodi "update available" prompt
notice the new release.

## After the first successful build — register the Downloader code

`Kodi POV IL` is wired to use the AFTVnews Downloader (the orange app on Fire TV / Android TV). To register a numeric code:

1. After the workflow finishes and the Release is live, visit `https://www.aftvnews.com/downloader/`.
2. Submit the public download URL — preferably the stable one:
   `https://github.com/MoranTheKing/Kodi-POV-IL/releases/latest/download/Kodi-POV-IL-64bit.apk`
3. The site returns a short numeric code (kodi7rd's is `864332`).
4. Tell Claude the code; the wizard's `uservar.py` will be updated and the in-app "update" dialog will start showing this code to users.

## Known limitations of the apktool rebrand

This workflow rebrands the official Kodi APK rather than rebuilding from source. That is fast (minutes vs hours) but a few edge cases can show up:

- Some Kodi screens (mainly system info) may still show file paths under `org.xbmc.kodi` instead of `org.xbmc.kodipovil`. Cosmetic only.
- If Kodi's Java/Kotlin code hard-codes its content provider authority anywhere outside the manifest, that flow may misbehave. None of the common paths (playback, addons, scrapers) are known to do this, but if you spot something broken, that's the first place to look.

If apktool-rebrand turns out to be too lossy, the workflow can be swapped to a from-source xbmc/xbmc build later. The trade-off is build time (45-90 min per architecture) and CI disk-space pressure.
