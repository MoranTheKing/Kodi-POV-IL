# Building the APK and Windows installer

Two workflows live under `.github/workflows/`:

- **`setup-keystore.yml`** — runs once. Generates an Android release keystore on the runner, encrypts it with your `KEYSTORE_PASSWORD` secret, and opens a PR adding `.secrets/release.keystore.enc` to the repo. The unencrypted keystore never leaves the runner.
- **`build-apk.yml`** — runs each time you cut a release. Decrypts the in-repo keystore, downloads the official Kodi 21.3 APK, rebrands it to `org.moran.kodi` (applicationId / provider authorities / permissions only — the code package is left intact so Kodi's native JNI still resolves), bundles the wizard + FENtastic build into `assets/`, signs both architectures, and attaches them (plus an NSIS Windows installer) to a GitHub Release.

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

## Package id: org.moran.kodi (one-time migration)

The build now ships as `org.moran.kodi`, **not** `org.xbmc.kodi`. This means:

- New installs no longer collide with the official Kodi from the Play Store —
  both can live on the device side by side.
- **Existing `org.xbmc.kodi` installs cannot update in place onto this build.**
  Android treats a different applicationId as a different app, so the first
  `org.moran.kodi` release installs *alongside* the old one. The wizard's
  update prompt now detects the old package id too and shows a one-time note
  telling the user the new app installs separately and the old one can be
  removed afterwards.
- From the *next* `org.moran.kodi` release onward, updates are in-place again
  (same package id, same keystore).

## Bumping a release later

- Bump the `version_code` integer (Android will refuse downgrade installs).
- Choose a new `version` label (e.g. `21.3-povil.26`).
- Run `build-apk.yml`. Same keystore, same `org.moran.kodi` package id, so
  installs from the previous `org.moran.kodi` release update in place.
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
4. Cut a new release with a new package id (e.g. `org.moran.kodi2`) — Android refuses to update an app signed with a different key, so existing installs cannot be upgraded. New users get the new package; existing users have to uninstall the old one first.

This is the same constraint the kodi7rd build operates under.

## Known limitations of the apktool rebrand

This workflow rebrands the official Kodi APK rather than rebuilding from source. Fast (minutes vs hours), but a few edge cases can show up:

- System info screens may still display `org.xbmc.kodi` somewhere. Cosmetic.
- If Kodi's Java/Kotlin code hard-codes its content provider authority outside the manifest, that flow may misbehave. Common paths (playback, addons, scrapers) don't.

If apktool-rebrand turns out lossy, the workflow can be swapped to a from-source xbmc/xbmc build later. Trade-off: 45-90 min per architecture and tighter CI disk-space.
