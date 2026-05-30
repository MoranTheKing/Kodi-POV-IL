# Building the APK and Windows installer

Two workflows live under `.github/workflows/`:

- **`setup-keystore.yml`** — runs once. Generates an Android release keystore on the runner, encrypts it with your `KEYSTORE_PASSWORD` secret, and opens a PR adding `.secrets/release.keystore.enc` to the repo. The unencrypted keystore never leaves the runner.
- **`build-apk.yml`** — runs each time you cut a release. Decrypts the in-repo keystore, downloads the official Kodi 21.3 APK, relabels it to "Kodi POV IL" and swaps in the custom launcher icon (keeping the package id `org.xbmc.kodi` — see below), bundles the wizard + FENtastic build into `assets/`, signs both architectures, and attaches them (plus an NSIS Windows installer) to a GitHub Release.

Neither workflow uses any third-party `actions/*` — just system tools and the preinstalled `gh` CLI. The repo's restrictive Actions policy doesn't block them.

## End-to-end setup — everything from a phone

1. **Add one secret.** `Settings → Secrets and variables → Actions → New repository secret`
   - Name: `KEYSTORE_PASSWORD`
   - Value: a strong password (16+ chars recommended; this is the only thing protecting your signing key from anyone who clones the repo).
   - **Write it down somewhere.** You'll need it for every future release. If you lose it the keystore is unrecoverable — every user will have to uninstall before the next release.

2. **Run the setup workflow.** `Actions → "Generate signing keystore" → Run workflow`. ~10 seconds.

3. **Merge the auto-PR.** A PR titled "Add encrypted release keystore" appears. Merge it. Now `.secrets/release.keystore.enc` lives in `main`.

4. **Build APKs.** `Actions → "Build APK and Windows installer" → Run workflow`. Defaults are fine for the first release (`version=21.3-povil.1`, `version_code=21301`, `kodi_version=21.3`). ~10-15 minutes.

5. **Done.** A Release tagged `v21.3-povil.1` appears under `Releases` with six attachments (versioned + stable filenames for 32-bit, 64-bit, Windows). The download pages on the GitHub Pages site already link to the stable filenames via `/releases/latest/download/`, so they go live automatically.

6. **Optional — register a Downloader code.** Submit one of the public URLs (e.g. `https://github.com/MoranTheKing/Kodi-POV-IL/releases/latest/download/Kodi-POV-IL-64bit.apk`) to `https://www.aftvnews.com/downloader/`, copy the numeric code it returns, and ask Claude to wire it into `uservar.py`.

## Package id: org.xbmc.kodi (label-only rebrand — the working config)

The build keeps the package id **`org.xbmc.kodi`** and only relabels the app
("Kodi POV IL") + swaps the launcher icon. This is the configuration that
installs and runs reliably, and it's what shipped in every working release.

History of why we're here (three failed attempts at a separate package id, all
reverted):

- **`21.3-povil.26`** renamed only the manifest `package=""` → inconsistent with
  the smali classes → crash-looped on boot.
- **`21.3-povil.27`** renamed the whole package incl. a binary dex patch. apktool
  still re-assembled `classes.dex`, which broke Kodi's JNI registration →
  `System.loadLibrary("kodi")` crashed in `nativeLoad`.
- **`21.3-povil.28`** kept the dex byte-identical but the re-injected
  `resources.arsc` came out compressed → modern Android refused to install
  ("App not installed").

Net: apktool simply cannot produce a renamed-package Kodi APK that both installs
and launches. A *real* separate applicationId needs a **from-source `xbmc/xbmc`
Gradle build** (45–90 min/arch, tighter CI). Until that's worth doing, we stay
on `org.xbmc.kodi`.

Trade-off: shares the package id with the official Kodi from Play Store, so the
two can't be installed side by side. Existing installs update in place normally.

## Bumping a release later

- Bump the `version_code` integer (Android will refuse downgrade installs).
- Choose a new `version` label (e.g. `21.3-povil.29`).
- Run `build-apk.yml`. Same keystore, same `org.xbmc.kodi` package id, so
  existing installs update in place.
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
4. Cut a new release. Android refuses to update an app signed with a different key, so existing installs cannot be upgraded onto the new keystore — existing users have to uninstall the old app first, then install the new one.

This is the same constraint the kodi7rd build operates under.

## Known limitations of the apktool rebrand

This workflow rebrands the official Kodi APK rather than rebuilding from source. Fast (minutes vs hours), but a few edge cases can show up:

- System info screens may still display `org.xbmc.kodi` somewhere. Cosmetic.
- If Kodi's Java/Kotlin code hard-codes its content provider authority outside the manifest, that flow may misbehave. Common paths (playback, addons, scrapers) don't.

If apktool-rebrand turns out lossy, the workflow can be swapped to a from-source xbmc/xbmc build later. Trade-off: 45-90 min per architecture and tighter CI disk-space.
