# Building the APK and Windows installer

Two workflows live under `.github/workflows/`:

- **`setup-keystore.yml`** — runs once. Generates an Android release keystore on the runner, encrypts it with your `KEYSTORE_PASSWORD` secret, and opens a PR adding `.secrets/release.keystore.enc` to the repo. The unencrypted keystore never leaves the runner.
- **`build-apk.yml`** — runs each time you cut a release. Decrypts the in-repo keystore, downloads the official Kodi 21.3 APK, relabels it to "Kodi POV IL" and renames the package `org.xbmc.kodi` → `org.mora.kodi` (same-length lockstep rename — see below), bundles the wizard + FENtastic build into `assets/`, signs both architectures, and attaches them (plus an NSIS Windows installer) to a GitHub Release.

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

## Package id: org.mora.kodi (same-length lockstep rename)

The build ships as **`org.mora.kodi`** — a *separate* app from the official
Kodi, so the two install side by side.

How it works, and why it doesn't crash like `21.3-povil.26` did:

- `21.3-povil.26` renamed **only** the manifest `package=""` and left the smali
  classes under `org.xbmc.kodi`. That inconsistency crash-looped on boot.
- The workflow now renames the **whole Java code package AND the applicationId
  in lockstep**: `org/xbmc/kodi` → `org/mora/kodi` across every smali file
  (three forms: slash class-refs, dotted authorities, dash-form lambda method
  names), the manifest `package=`/authorities/component names, and `res/*.xml`.
  apktool re-smalis the result so the dex checksums are correct. Build-time
  sanity gates abort if any old-package reference survives.
- **`org.mora.kodi` is exactly 13 chars, same as `org.xbmc.kodi`** — chosen so
  nothing relies on a length change. (`moran` would have been 14.)
- The native `.so` files are left untouched: `libkodi.so` has **zero**
  `Java_org_xbmc_kodi_*` JNI exports and zero `org/xbmc/kodi` class strings — it
  binds natives via `RegisterNatives` with a class handed in from Java — so the
  rename is safe without touching any binary. (Verified by decoding kodi-21.3.)

⚠️ **Migration:** existing `org.xbmc.kodi` installs can't update in place onto
`org.mora.kodi` (Android treats a different applicationId as a different app).
The new app installs **alongside** the old one; the wizard's update prompt shows
a one-time note telling the user to remove the old app afterwards. From the next
`org.mora.kodi` release onward, updates are in-place again.

🔬 **Always test-boot before announcing.** The rename is verified at build time
(consistency gates + a clean apktool rebuild), but no CI check can confirm the
app actually launches. Install the new APK on one device first; only announce to
users once it boots to the home screen.

## Bumping a release later

- Bump the `version_code` integer (Android will refuse downgrade installs).
- Choose a new `version` label (e.g. `21.3-povil.27`).
- Run `build-apk.yml`. Same keystore, same `org.mora.kodi` package id, so
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
