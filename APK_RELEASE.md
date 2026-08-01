# Platform package release

The Android APKs, Windows installer and LG webOS IPK are built by
`.github/workflows/build-apk.yml`. For the release procedure and keystore
setup, see [APK_BUILD.md](APK_BUILD.md).

## Current verified release

[`21.3-povil.48`](https://github.com/MoranTheKing/Kodi-POV-IL/releases/tag/v21.3-povil.48)
was **rebuilt in place on 2026-08-01** at the same version label. The release
was deleted and recreated with fresh artifacts; the label, versionCode and
release marker are unchanged, so no installed client is prompted to update.

Why it was rebuilt: the packages bundle the Wizard into `assets/`, and the
Wizard shipped in the previous `.48` build (`0.1.34`) carried the extraction
bug that skipped the five FENtastic home-widget files on a fresh install. The
rebuild bundles Wizard `0.1.36`, so a new installation lays those files down on
its first extraction instead of relying on the add-on to restore them at the
next startup.

| Package | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| Android 32-bit | 74,651,502 | `84f08b944a9a9b5b9f0011f3fb3b3cffc2b2ababbd89cdb3f863196b1e186b32` |
| Android 64-bit | 74,983,190 | `46f3de4153c250e068083399708f451b37caa71549992e5ff9d659693438e8f2` |
| Windows | 133,276,916 | `1f22176468ee40b15e93d245dd2beb73058d7de821594d826317b83862ffff0b` |
| LG webOS | 97,576,916 | `253495b5f7e3deeda17a4270948480330d8bbe124deef810902567a9cb05f8c4` |

Both APKs and the Windows installer were downloaded from the published URLs and
hashed; each matched the release-reported digest. Each Android package was
opened and `assets/addons/plugin.program.kodipovilwizard/addon.xml` confirmed to
read `0.1.36`, with the corrected `preserve_widget_layout` rule present in
`resources/libs/extract.py`. The Windows installer's NSIS block was decompressed
and the same `addon.xml` read `0.1.36` there too. The webOS row is the
release-reported digest; that package was not re-downloaded.

`assets/system/povil-release.txt` still reads `21.3-povil.48`, and both version
pointer files (`wizard/assets/kodi_version_auto_update/{apk,windows}/`) were
confirmed unchanged at `21.3-povil.48` on `main` and on Raw. The workflow's
pointer step is a no-op when the label does not change, so no PR was opened and
no client sees a newer version. Version comparison is strictly-newer
(`release_version.is_newer_release`), so an equal label never prompts.

**The APK download links are NOT served from the release.** `downloads/index.html`
points at `https://morantheking.github.io/Kodi-POV-IL/downloads/Kodi-POV-IL-{32,64}bit.apk`,
which are files on the `gh-pages` branch. `deploy-pages.yml` copies them there
with `gh release download`, so **a Pages deploy must run AFTER the release
assets are uploaded** — otherwise the site keeps serving the previous APK while
the release holds the new one. That is exactly what happened on 2026-08-01: the
Pages deploy ran at 12:35 and the assets landed at 12:52, so the site served
Wizard `0.1.34` APKs until `deploy-pages.yml` was dispatched again at 13:06.
Both files were then re-downloaded from the live page and matched the release
digests byte-for-byte. **Always re-run Deploy GitHub Pages as the last step of
a package release.** The Windows and webOS links use
`releases/latest/download/...` and are not affected.

The earlier `.48` build (workflow run 30137185730, Wizard `0.1.34`, build
`0.1.101`) recorded these hashes, kept for reference: Android 32-bit
`29421caff3c1d75709c607845461e27484432124512c09ed1927798a525e8dc9`
(74,647,406), Android 64-bit
`553c7162f23cbafbd619e7183864a5f3662f01eef290dd7fe03028f0eb436748`
(74,983,190), Windows
`0d6e7f2d8ca227e248c6cef872f2689ba10adbfae62016c148a29087d3916721`
(133,274,232), LG webOS
`f82ab46528450f5ade730604683985ab2fb0d8a726503a820d36d864cf7ee6c9`
(97,576,242).

Both APKs report package `org.xbmc.povi`, versionCode `2103048`,
versionName `21.3-povil.48`, the expected ABI and the POV IL label. They are
zip-aligned, carry valid v1/v2/v3 signatures and use the same signing
certificate as the actual `.47` APK, so they can update it in place. The
certificate SHA-256 is
`b69d63b652d991ca78bbbf8aca3f034491696a4c36d6468c3a5a4685a65b5417`.

The webOS IPK reports app id `org.xbmc.kodi` with numeric version `21.3.48`.
The outer Windows EXE is not Authenticode-signed, so SmartScreen can still show
an unknown-publisher warning. Keep the clean-Windows standard-user launch smoke
test in the release checklist rather than claiming it was run on the
maintainer's machine.

The original `.48` release pointers were published by
[PR #384](https://github.com/MoranTheKing/Kodi-POV-IL/pull/384), and the
user-facing maintenance note `#541` by
[PR #385](https://github.com/MoranTheKing/Kodi-POV-IL/pull/385) only after the
artifact and cache gates.

### Guarded workflow constants

`build-apk.yml` refuses to run unless the dispatch inputs exactly match
`EXPECTED_RELEASE` / `EXPECTED_VERSION_CODE` / `EXPECTED_KODI_VERSION`
(currently `21.3-povil.48` / `2103048` / `21.3`). Dispatching any other value
fails in the first step, in about 12 seconds, before anything is built — so a
mistyped version cannot produce a release. To ship a genuinely new version,
bump those constants in the workflow deliberately, in the same commit as
`WIZARD_VERSION` if the Wizard changed.

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
