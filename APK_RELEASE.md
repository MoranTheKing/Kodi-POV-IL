# Platform package release

The Android APKs, Windows installer and LG webOS IPK are built by
`.github/workflows/build-apk.yml`. For the release procedure and keystore
setup, see [APK_BUILD.md](APK_BUILD.md).

## Current verified release

[`21.3-povil.49`](https://github.com/MoranTheKing/Kodi-POV-IL/releases/tag/v21.3-povil.49)
was **rebuilt in place on 2026-08-23** (workflow run 32613503647, assets
uploaded 02:49 UTC) at the same version label. The release was deleted and
recreated with fresh artifacts; the label, versionCode and release marker are
unchanged, so no installed client is prompted to update.

Why it was rebuilt: the packages bundle the Wizard into `assets/`, and the
`.49` build published on 2026-08-14 carried Wizard `0.1.46`. `0.1.48` closes
the quick-update path that KILLED Kodi rather than closing it -- which skips
the settings save, so anything changed that session was lost -- and adds the
Umbrella / Account Manager auto-install and the pack-integrity repairs.

**This matters for a new installation specifically.** `startup.py` self-updates
the Wizard before it extracts the build, but the update only lands on disk: the
running process keeps the `extract` module it already imported, so a brand-new
install extracts with whatever Wizard version the APK shipped. Rebuilding is
what makes the FIRST extraction use `0.1.48`.

| Package | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| Android 32-bit | 74,684,270 | `029aa092a14e245166c4a4d71c367c0d97da084ec8a919d17d83945cf0669111` |
| Android 64-bit | 75,020,054 | `4cf28309a8a6ade1609eba4c3981f1d6b44f152f0811c2fa800321abf70f4c42` |
| Windows | 142,447,847 | `37fec0970b00d935a0e82b5ae8cc4ed914267fbf93454ec40606746684635165` |
| LG webOS | 97,611,186 | `246c85ca82d3debb6446cf3df6a69aac64d93a8e6190e5582a9ce108da9dc667` |

The 64-bit APK was downloaded **from the live download page** (not from the
release) and hashed: `4cf28309...f70f4c42`, byte-identical to the release
asset. Opened, it reports `assets/system/povil-release.txt` =
`21.3-povil.49` and `assets/addons/plugin.program.kodipovilwizard/addon.xml` =
`0.1.48`. The 32-bit page copy was matched by size only (74,684,270); the
Windows and webOS rows are the release-reported digests and were not
re-downloaded.

### WHAT THE APK DOES NOT CONTAIN, because it is easy to assume otherwise

**The build is not in the package.** `build-apk.yml` bundles Kodi's own
add-ons plus the Wizard (62 add-ons in the 64-bit APK), and lifts exactly six
pure-Python modules out of the build zip -- `script.module.requests`, `six`,
`certifi`, `urllib3`, `chardet`, `idna` -- because the Wizard imports
`requests` at startup. `plugin.video.pov`, `service.subtitles.kodipovilai`,
`skin.fentastic` and the rest are NOT there. A fresh install downloads the
build from `wizard/assets/build.txt` on first launch, which is why a new
device lands on whatever build.txt currently serves rather than on whatever
was current when the APK was built.

So a package rebuild changes exactly two things: the bundled Wizard, and those
six modules. It does not "ship a newer build".

**The APK download links are NOT served from the release.** `downloads/index.html`
points at `https://morantheking.github.io/Kodi-POV-IL/downloads/Kodi-POV-IL-{32,64}bit.apk`,
which are files on the `gh-pages` branch. `deploy-pages.yml` copies them there
with `gh release download`, so **a Pages deploy must run AFTER the release
assets are uploaded** — otherwise the site keeps serving the previous APK while
the release holds the new one.

This happened twice. On 2026-08-01 the Pages deploy ran at 12:35 and the assets
landed at 12:52, so the site served Wizard `0.1.34` APKs until
`deploy-pages.yml` was dispatched again at 13:06. This document then said, in
bold, to always re-run Deploy GitHub Pages as the last step of a package
release — and on 2026-08-23 that manual step was missed, so the packages
rebuilt at 02:49 sat on the release while the site kept serving the previous
ones. Measured: the release asset was 75,020,054 bytes and the live page was
still 75,011,862.

A documented manual step that is skipped once is a documented manual step that
will be skipped again. **`deploy-pages.yml` now also triggers on
`release: [published, edited]`**, so the sync follows the packages by itself.
`test_pages_sync_follows_a_release` pins the trigger AND the reason it is
needed — that `build-apk.yml`'s pointer step exits without committing when the
version label has not changed, which is why a rebuild at an unchanged label
produces no push to `main` and therefore used to produce no Pages deploy.

The Windows and webOS links use `releases/latest/download/...` and are not
affected.

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

Both APKs report package `org.xbmc.povi`, versionCode `2103049`,
versionName `21.3-povil.49`, the expected ABI and the POV IL label. They are
zip-aligned, carry valid v1/v2/v3 signatures and use the same signing
certificate as the `.47` and `.48` APKs, so they can update either in place. The
certificate SHA-256 is
`b69d63b652d991ca78bbbf8aca3f034491696a4c36d6468c3a5a4685a65b5417`.

The webOS IPK reports app id `org.xbmc.kodi` with numeric version `21.3.49`.
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
(currently `21.3-povil.49` / `2103049` / `21.3`). Dispatching any other value
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
  version (for example POV release `21.3-povil.49` becomes webOS `21.3.49`).
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
