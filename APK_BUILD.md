# Building the APK and Windows installer

Two workflows live under `.github/workflows/`:

- **`setup-keystore.yml`** ג€” runs once. Generates an Android release keystore on the runner, encrypts it with your `KEYSTORE_PASSWORD` secret, and opens a PR adding `.secrets/release.keystore.enc` to the repo. The unencrypted keystore never leaves the runner.
- **`build-apk.yml`** - runs each time you cut a release. Decrypts the in-repo keystore, downloads the official Kodi APK, rebrands it to separate package id `org.xbmc.povi`, relabels it to "Kodi POV IL", bundles the wizard (+ its python deps) into `assets/` as optional system addons (the FENtastic build itself is downloaded by the wizard on first launch -- never baked into `assets/`, see APK_RELEASE.md), signs both architectures, and attaches them plus the independent Windows installer to a GitHub Release.

Neither workflow uses any third-party `actions/*` ג€” just system tools and the preinstalled `gh` CLI. The repo's restrictive Actions policy doesn't block them.

## End-to-end setup ג€” everything from a phone

1. **Add one secret.** `Settings ג†’ Secrets and variables ג†’ Actions ג†’ New repository secret`
   - Name: `KEYSTORE_PASSWORD`
   - Value: a strong password (16+ chars recommended; this is the only thing protecting your signing key from anyone who clones the repo).
   - **Write it down somewhere.** You'll need it for every future release. If you lose it the keystore is unrecoverable ג€” every user will have to uninstall before the next release.

2. **Run the setup workflow.** `Actions ג†’ "Generate signing keystore" ג†’ Run workflow`. ~10 seconds.

3. **Merge the auto-PR.** A PR titled "Add encrypted release keystore" appears. Merge it. Now `.secrets/release.keystore.enc` lives in `main`.

4. **Build APKs.** `Actions ג†’ "Build APK and Windows installer" ג†’ Run workflow`. Defaults are fine for the first release (`version=21.3-povil.1`, `version_code=21301`, `kodi_version=21.3`). ~10-15 minutes.

5. **Done.** A Release tagged `v21.3-povil.1` appears under `Releases` with six attachments (versioned + stable filenames for 32-bit, 64-bit, Windows). The download pages on the GitHub Pages site already link to the stable filenames via `/releases/latest/download/`, so they go live automatically.

6. **Optional ג€” register a Downloader code.** Submit one of the public URLs (e.g. `https://github.com/MoranTheKing/Kodi-POV-IL/releases/latest/download/Kodi-POV-IL-64bit.apk`) to `https://www.aftvnews.com/downloader/`, copy the numeric code it returns, and ask Claude to wire it into `uservar.py`.

## Package id: org.xbmc.povi (side-by-side Android install)

The Android APK now uses **`org.xbmc.povi`** so it can be installed next to
official Kodi (`org.xbmc.kodi`). This is not a manifest-only rename. The
workflow decodes the official APK with `apktool d -s` so the original DEX files
stay intact, then performs same-length binary package patching:

- manifest/resources/text refs: `org.xbmc.kodi` -> `org.xbmc.povi`
- DEX refs: dotted, slash, dash, and underscore package forms
- native/resources binary refs when the same package bytes appear
- DEX SHA-1 + Adler-32 header fields are recalculated after patching

The package ids deliberately have the same length (13 chars). Do not change to
`org.xbmc.kodipovil` or `org.moran.kodi` without switching to a true from-source Kodi build; those ids have
a different length and cannot be patched safely in place.

The workflow runs `.github/scripts/verify_apk_package.py` before zipalign/sign.
If any `org.xbmc.kodi` runtime reference survives in the unsigned APK, the build
fails instead of publishing a crash-looping app.

Previous crash-loop attempts failed because they either changed only the
manifest package or let apktool reassemble smali/classes.dex. The current path
avoids both failure modes.

Windows is independent too: the NSIS installer installs Kodi POV IL under its
own program folder and launches Kodi with `-p`, so its profile lives in
`portable_data` instead of `%APPDATA%\Kodi`.

## Bumping a release later

- Bump the `version_code` integer (Android will refuse downgrade installs).
- Choose a new `version` label (e.g. `21.3-povil.29`).
- Run `build-apk.yml`. Same keystore, same `org.xbmc.povi` package id, so
  Kodi POV IL installs update in place while official Kodi remains separate.
- Merge the auto-PR that bumps `wizard/assets/kodi_version_auto_update/{apk,windows}/latest_*.txt` so installed clients notice the new release.

## What gets published in each release

- `Kodi-POV-IL-<version>-32bit.apk` and `Kodi-POV-IL-32bit.apk`
- `Kodi-POV-IL-<version>-64bit.apk` and `Kodi-POV-IL-64bit.apk`
- `Kodi-POV-IL-Setup-<version>.exe` and `Kodi-POV-IL-Setup.exe`

The stable filenames let the download pages use `/releases/latest/download/<name>` without updating HTML per release.

## Recovery from a lost keystore

If `KEYSTORE_PASSWORD` is lost:

1. Delete the `.secrets/release.keystore.enc` file (via PR or web edit).
2. Rotate `KEYSTORE_PASSWORD` to a new value.
3. Run `setup-keystore.yml` again to mint a fresh keystore.
4. Cut a new release. Android refuses to update an app signed with a different key, so existing installs cannot be upgraded onto the new keystore ג€” existing users have to uninstall the old app first, then install the new one.

This is the same constraint the kodi7rd build operates under.

## Known limitations of the apktool rebrand

This workflow rebrands the official Kodi APK rather than rebuilding from source. Fast (minutes vs hours), but a few edge cases can show up:

- If Kodi upstream adds a new hard-coded package form that is not dotted/slash/dash/underscore, the verifier should catch old references before release.
- If a future Kodi APK changes native package loading assumptions, switch to a from-source xbmc/xbmc Android build.

If apktool-rebrand turns out lossy, the workflow can be swapped to a from-source xbmc/xbmc build later. Trade-off: 45-90 min per architecture and tighter CI disk-space.
