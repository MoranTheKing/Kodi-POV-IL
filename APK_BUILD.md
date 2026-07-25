# Building Android, Windows and webOS packages

Two workflows live under `.github/workflows/`:

- **`setup-keystore.yml`** ג€” runs once. Generates an Android release keystore on the runner, encrypts it with your `KEYSTORE_PASSWORD` secret, and opens a PR adding `.secrets/release.keystore.enc` to the repo. The unencrypted keystore never leaves the runner.
- **`build-apk.yml`** - runs each time you cut a release. It builds and verifies
  two signed Android APKs, the profile-preserving Windows installer and the
  metadata-preserving LG webOS IPK. The Wizard and its pure-Python dependencies
  are bundled; the FENtastic build is installed into the writable user profile
  on first launch rather than baked over Kodi's platform system addons.

Neither workflow uses any third-party `actions/*` ג€” just system tools and the preinstalled `gh` CLI. The repo's restrictive Actions policy doesn't block them.

## End-to-end setup ג€” everything from a phone

1. **Add one secret.** `Settings ג†’ Secrets and variables ג†’ Actions ג†’ New repository secret`
   - Name: `KEYSTORE_PASSWORD`
   - Value: a strong password (16+ chars recommended; this is the only thing protecting your signing key from anyone who clones the repo).
   - **Write it down somewhere.** You'll need it for every future release. If you lose it the keystore is unrecoverable ג€” every user will have to uninstall before the next release.

2. **Run the setup workflow.** `Actions ג†’ "Generate signing keystore" ג†’ Run workflow`. ~10 seconds.

3. **Merge the auto-PR.** A PR titled "Add encrypted release keystore" appears. Merge it. Now `.secrets/release.keystore.enc` lives in `main`.

4. **Build platform packages.** `Actions → "Build Android, Windows and webOS
   packages" → Run workflow`. Supply a release label such as
   `version=21.3-povil.48`, a strictly increasing Android `version_code` such as
   `2103048`, and `kodi_version=21.3`. Release `.47` inherited upstream
   `versionCode=2103000`, so `.48` must stay above it; `21348` would be treated
   by Android as a downgrade and cannot update an existing installation.

5. **Verify before announcing.** A release appears with eight attachments:
   versioned and stable filenames for 32-bit Android, 64-bit Android, Windows
   and webOS. Download every real asset and run the package verification
   checklist below before merging the generated pointer PR.

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

Windows is independent too: the NSIS installer installs under
`C:\Program Files\Kodi POV IL`; every branded shortcut launches `kodi.exe -p`,
so its profile lives in `portable_data` rather than `%APPDATA%\Kodi`. Before an
update it moves the full profile to a sibling recovery folder outside the
upstream install tree, restores it afterward, and grants the Builtin Users SID
Modify access only on `portable_data`. The installer never launches Kodi while
elevated.

The Windows setup currently has no Authenticode certificate. SmartScreen may
therefore show the normal "unrecognized app" warning; eliminating that warning
requires a trusted Windows code-signing certificate. This is separate from the
fixed runtime-permission bug: after setup, Kodi POV IL must open as a standard
user and must not need "Run as administrator".

Wizard 0.1.35+ suppresses automatic package checks only for legacy Android/
Windows installations that predate `povil-release.txt`. A manual check still
uses the `.47` compatibility bridge, and marked `.48+` packages retain
automatic eligibility for important future full-application releases. This
prevents ordinary quick-update maintenance from immediately showing an
unrequested APK/EXE replacement dialog to a legacy installation.

LG webOS keeps the official `org.xbmc.kodi` app id so a newer IPK upgrades the
existing app. The public POV label is converted to a valid numeric webOS
version (`21.3-povil.48` → `21.3.48`) in all three package metadata files.
Never write a hyphenated POV label into `appinfo.json`.

## Bumping a release later

- Bump the `version_code` integer (Android will refuse downgrade installs).
- Keep it above the highest value already shipped. The `.48` baseline is
  `2103048`, chosen to exceed the legacy `.47` value `2103000`.
- Choose a new `version` label (e.g. `21.3-povil.49`).
- Bump the workflow's guarded `EXPECTED_RELEASE`,
  `EXPECTED_VERSION_CODE` and `EXPECTED_KODI_VERSION` together with the input
  defaults. The job intentionally stops before downloading anything when an
  input differs from those reviewed release constants.
- Ensure `.github/workflows/build-apk.yml` points at the Wizard ZIP that is
  already published on `main`.
- Build the Wizard with `tools/build_wizard_package.py --previous <old.zip>
  --manifest wizard/release_manifests/<release>.json --version <version>`.
  The release manifest must explicitly list every replaced/added member and
  lock the previous/output SHA-256. Confirm the versioned and `latest` ZIPs
  under both `dist/` and `wizard/` are byte-identical and every Wizard index
  link resolves before publishing the channel manifest.
- Run `build-apk.yml`. Same keystore, same `org.xbmc.povi` package id, so
  Kodi POV IL installs update in place while official Kodi remains separate.
- Verify the final signed APK artwork/marker/signature, Windows installer,
  webOS metadata/app id/native executable and all stable download URLs.
- Merge the auto-PR that bumps
  `wizard/assets/kodi_version_auto_update/{apk,windows}/latest_*.txt` only
  after the release assets pass.

## What gets published in each release

- `Kodi-POV-IL-<version>-32bit.apk` and `Kodi-POV-IL-32bit.apk`
- `Kodi-POV-IL-<version>-64bit.apk` and `Kodi-POV-IL-64bit.apk`
- `Kodi-POV-IL-Setup-<version>.exe` and `Kodi-POV-IL-Setup.exe`
- `Kodi-POV-IL-<version>-webos.ipk` and `Kodi-POV-IL-webos.ipk`

The stable filenames let the download pages use `/releases/latest/download/<name>` without updating HTML per release.

## Mandatory package verification

The workflow fails before release creation unless:

- final `aapt dump badging` metadata exactly matches the reviewed package id,
  increasing versionCode, public versionName, app label and ABI;
- all six Android launcher densities, both Android TV banner locations, every
  Kodi media icon, the launch splash and `povil-release.txt` match the canonical
  assets;
- the webOS ar order is exactly `debian-binary`, `control.tar.gz`,
  `data.tar.gz`; original tar member ordering/metadata and every untouched file
  byte remain stable; `kodi-webos` remains executable and byte-identical; all
  versions/app ids, bundled addons, artwork and marker are correct;
- the Windows NSIS compiler accepts the installer script and embeds the shared
  POV IL `.ico`.

After the workflow succeeds, repeat the checks against the downloaded GitHub
Release assets. A successful build job alone is not the release gate.

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
