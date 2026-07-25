# Platform package release

The Android APKs, Windows installer and LG webOS IPK are built by
`.github/workflows/build-apk.yml`. For the release procedure and keystore
setup, see [APK_BUILD.md](APK_BUILD.md).

## Current verified release

[`21.3-povil.48`](https://github.com/MoranTheKing/Kodi-POV-IL/releases/tag/v21.3-povil.48)
was built by
[workflow run 30137185730](https://github.com/MoranTheKing/Kodi-POV-IL/actions/runs/30137185730).
The stable and versioned copy of each package were downloaded after publication
and proved byte-identical:

| Package | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| Android 32-bit | 74,647,406 | `29421caff3c1d75709c607845461e27484432124512c09ed1927798a525e8dc9` |
| Android 64-bit | 74,983,190 | `553c7162f23cbafbd619e7183864a5f3662f01eef290dd7fe03028f0eb436748` |
| Windows | 133,274,232 | `0d6e7f2d8ca227e248c6cef872f2689ba10adbfae62016c148a29087d3916721` |
| LG webOS | 97,576,242 | `f82ab46528450f5ade730604683985ab2fb0d8a726503a820d36d864cf7ee6c9` |

Both APKs report package `org.xbmc.povi`, versionCode `2103048`,
versionName `21.3-povil.48`, the expected ABI and the POV IL label. They are
zip-aligned, carry valid v1/v2/v3 signatures and use the same signing
certificate as the actual `.47` APK, so they can update it in place. The
certificate SHA-256 is
`b69d63b652d991ca78bbbf8aca3f034491696a4c36d6468c3a5a4685a65b5417`.

The downloaded webOS IPK passed the metadata-preserving comparison against the
pinned official package and reports app id `org.xbmc.kodi` with numeric version
`21.3.48`. The downloaded Windows EXE contains the exact pinned Kodi 21.3
installer, build `0.1.101`, Wizard `0.1.34`, POV IL icon and release marker.
The outer Windows EXE is not Authenticode-signed, so SmartScreen can still show
an unknown-publisher warning. Verification covered the real release payload and
installer structure; keep the clean-Windows standard-user launch smoke test in
the release checklist rather than claiming it was run on the maintainer's
machine.

The release pointers were published by
[PR #384](https://github.com/MoranTheKing/Kodi-POV-IL/pull/384), and the
user-facing maintenance note `#541` was published separately by
[PR #385](https://github.com/MoranTheKing/Kodi-POV-IL/pull/385) only after the
artifact and cache gates. Pages
[run 30138021266](https://github.com/MoranTheKing/Kodi-POV-IL/actions/runs/30138021266)
succeeded; the raw and Pages note URLs both returned `541` after the full
five-minute cache window.

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
