# Kodi POV IL — Project Handoff (public)

> Onboarding notes for anyone (or any AI session) picking up this repo.
> Architecture, release channels, and the exact shipping procedures.

## What this project is

A Hebrew-localized Kodi build (skin + addons + wizard) for users in Israel,
plus a standalone subtitle addon. Main pieces:

- **`plugin.video.pov`** — the streaming addon (upstream "POV", vendored).
  The build patches it at runtime for Hebrew UI, menus, favourites, etc.
- **`service.subtitles.kodipovilai` ("MoranSubs")** — the in-house subtitle
  addon: human Hebrew sources (Ktuvit / Wizdom / OpenSubtitles / SubSource
  and more via the vendored sources engine), AI translation to Hebrew via
  Google Gemini (bring your own key), a community subtitle pool, and
  SubSync — automatic verification/fixing of subtitle timing (build edition).
- **`plugin.program.kodipovilwizard`** — installs the build and applies
  quick updates.

Skins: `skin.fentastic` (default), `skin.povil.nox`, `skin.estuary`,
`skin.arctic.fuse.3`.

## Repo layout (the parts that matter)

```
addons/service.subtitles.kodipovilai/   # MoranSubs source
  addon.xml                             # addon version lives here
  service.py  default.py
  resources/lib/                        # translation, sources engine bridge,
                                        # SubSync, runtime patchers, ...
dist/                                   # built zips (committed)
repo/                                   # Kodi repository (GitHub Pages)
wizard/assets/build.txt                 # channel manifest the wizard reads
wizard/assets/notification_files/quick_update.txt  # quick-update trigger+text
tools/build_ai_subtitles_packages.py    # builds standalone + build-edition zips
tools/publish_repo_channel.py           # publishes repo/addons.xml + zips
.github/scripts/platform_branding.py    # derives/verifies shared package artwork
.github/scripts/build_webos_ipk.py      # metadata-preserving webOS IPK builder
dist/installer/build-windows-installer.nsi  # isolated Windows portable installer
tools/build_wizard_package.py           # deterministic Wizard ZIP builder
tools/build_wizard_quickfix.py          # replaces only the Wizard in a quickfix
```

## The two distribution channels

### Build / quickfix channel (most users)
- Users install the full build once, then the wizard applies quick updates.
- `wizard/assets/build.txt` line `gui="...quickfix-<N>.zip"` points at the
  current quickfix zip (a full build tree).
- `quick_update.txt` first line is `<id>|||<title>`, then a body. The wizard
  triggers an update when the numeric `<id>` CHANGES — bump it to deliver.
- **Build a quickfix by copying the PREVIOUS quickfix zip and replacing only
  the changed files**, then verify member-by-member (CRC) that nothing else
  changed. Never rebuild from scratch.

### Standalone repo channel
- A Kodi repository served from GitHub Pages at
  `https://morantheking.github.io/Kodi-POV-IL/repo/` (synced from `main`).
- The standalone addon is a curated subset (see
  `tools/build_ai_subtitles_packages.py`): no build/wizard healers and no
  POV/skin patchers, but WITH the sources engine and the auto-on-play
  search — it functions as a complete primary subtitle addon on a clean
  Kodi (works alongside an independent POV / Umbrella install).
- Ship with `tools/build_ai_subtitles_packages.py` then
  `tools/publish_repo_channel.py`.

## Hard rules

1. **Deploy = merge to `main`.** The wizard fetches raw files from `main`;
   GitHub Pages syncs from `main`.
2. **Never overwrite a shipped `pool.py` with the git-source one** when
   assembling zips, and never commit the plaintext pool credential, its local
   packaging helper, or the current private Worker source. The community-pool
   client in shipped zips is provisioned at packaging time (maintainer-only);
   the git source intentionally is not. When `pool.py` logic did not change,
   inherit it byte-for-byte from the previous good zip. When its logic did
   change, use the credential-aware packaging flow; a missing secret/helper/
   marker or a remaining placeholder MUST abort the build.
3. **Bump `_VERDICT_VERSION` in `subsync.py`** whenever sync logic changes,
   so cached verdicts recompute on devices.
4. **Notifications are deliberately quiet.** Rare, gentle, specific, Hebrew,
   ending with "אין צורך בפעולה מצדכם" when true. No non-ASCII glyphs that
   skin fonts may lack (a ✓ once rendered as tofu).
5. **One concern per quickfix**, byte-verified before shipping.

## MoranSubs feature map (quick orientation)

- `resources/lib/translate.py` — AI translation orchestration (chunking,
  retries, caches, pool reuse).
- `resources/lib/prompt.py` — the translation prompt (gender rules, cast
  block, reference-language gender blocks).
- `resources/lib/arabic_gender.py` — the gender-reference oracle: fetches a
  human subtitle of the same title in a gender-marking language (priority:
  out-of-sync human Hebrew, Arabic, then hi/es/ru/pt/pl/uk/fr/it/cs/ro/el/
  bg/sr/hr/sk/ur/nl), time-aligns it to the source, and feeds per-line
  gender hints to the prompt. Fully fail-open.
- `resources/lib/autosub_service.py` — auto-on-play Hebrew search/apply
  (shared by the full build's service.py and the standalone slim service).
- `resources/lib/subs_engine/` + `subs_engine_bridge.py` — the vendored
  human-sources engine and its MoranSubs bridge.
- `resources/lib/subsync.py`, `sync_align.py`, `mkv_probe.py`,
  `release_match.py` — SubSync (build edition; see `SUBSYNC_PLAN.md`).
- `resources/lib/pov_*_patcher.py`, `<skin>_*_patcher.py`,
  `umbrella_*_patcher.py` — runtime patchers applied by the build's service at
  boot. Marker-gated, compile-checked, atomic writes, `.pyc` dropped; a patch
  that can't apply never breaks its host. Anchors are built from the target
  file's own detected EOL — see the CRLF entry below for why.
- `resources/lib/mdblist_umbrella_mirror.py`, `trakt_umbrella_mirror.py`,
  `umbrella_watch_source.py` — one authorisation covering POV and Umbrella,
  and the two Umbrella settings that decide which service it READS watched
  state from. All writes go through `addon_settings_safe`; never bare
  `setSetting` another add-on.
- `resources/lib/pov_seasons_view_seed.py` — writes POV's own `views.db` row
  so the season list opens on a poster view, per skin, once.

## Shipping a quickfix (checklist)

1. Bump `addon.xml` version + add a `changelog.txt` entry.
2. Sync-logic change? Bump `_VERDICT_VERSION`.
3. Copy previous quickfix zip -> new name; `zip` in ONLY the changed files at
   their in-zip paths (never `pool.py` unless its logic truly changed). On
   Windows, take replacement text bytes from the intended canonical Git index
   (`git show :path`), not raw worktree files that may contain CRLF; assert the
   packaged member is byte-identical to that Git blob.
4. Verify: same member set (plus intentionally added files) and only intended
   CRC changes. If `pool.py` did not change, it must be byte-identical. If it
   did change, prove separately that (a) the logic outside the protected key
   block is the intended new logic, (b) the protected block matches the last
   known-good release, and (c) a Kodi-context signed live `/lookup` returns
   HTTP 200. Never print the credential while testing.
5. Get a separate read-only reviewer to inspect the source diff, ZIP member/CRC
   diff, credential preservation and privacy boundary. Do not ship a blocker.
6. Choose the next numeric note id `N`, but **do not edit `quick_update.txt`
   yet**. Point mutable `build.txt` at the new quickfix and add
   `wizard/assets/build_versions/N.txt`; its normalized Git blob must be
   byte-identical to `build.txt`. Wizard 0.1.33+ resolves an automatic update by
   this immutable per-note path and never falls back to mutable `build.txt`.
7. **Phase 1 — artifacts only:** commit packages/repo metadata, `build.txt` and
   `build_versions/N.txt` on the working branch, fast-forward `main`, and push.
   Leave the live note on the previous id. Verify the public raw packages and
   manifests against the exact Git blobs/hashes and require GitHub Pages success.
   For the Kodi repository channel, fetch the live HTTP response bodies and require
   `MD5(exact bytes returned by GET repo/addons.xml)` to equal the exact 32-character
   lowercase-hex body returned by `GET repo/addons.xml.md5`. Never substitute a
   Windows worktree copy whose line endings may have been converted to CRLF.
8. Wait at least the full raw-GitHub cache window (currently 300 seconds) after
   verified publication, then fetch and verify again. Query strings are **not**
   cache-busters here: empirical testing showed raw.githubusercontent ignores
   them for its cache key. Old Wizard <=0.1.32 clients still read mutable
   `build.txt`, which is why this wait is mandatory.
8b. **A NEW FILE in the add-on needs `--allow-add`.** `build_addon_quickfix.py`
   refuses to add a member the previous quickfix did not have unless it is
   named: `--allow-add addons/service.subtitles.kodipovilai/resources/lib/<new>.py`.
   Without it the build stops -- and it names the added files and the flag,
   rather than saying "member names or order changed" as this document used to
   claim. That guard exists so a stray file cannot slip into a package
   unnoticed, so name the file rather than weakening it. Only the first
   quickfix carrying the file needs the flag; every later one inherits it.

   **COUNT THE NEW FILES AGAINST THE SHIPPED QUICKFIX, NOT AGAINST YOUR OWN
   MEMORY OF THIS BRANCH.** My own release notes said "exactly two new files"
   for 0.1.537 and named the two written this week. There are three: the tile
   patcher was added in `c6fff06`, several commits earlier, and never shipped,
   so it is just as new to `0.1.536` as the other two. The build would have
   stopped on it. One command answers it, and it is worth running every time:

   ```
   python3 - <<'PY'
   import zipfile, os, pathlib
   z = 'dist/Kodi-POV-IL-FENtastic-quickfix-<PREV>.zip'
   have = {os.path.basename(n) for n in zipfile.ZipFile(z).namelist()}
   root = pathlib.Path('addons/service.subtitles.kodipovilai')
   print(sorted({p.name for p in root.rglob('*.py')} - have))
   PY
   ```

   For 0.1.537 that is `pov_addon_window_patcher.py`,
   `recent_updates_tile_patcher.py` and `update_nag_patcher.py`.
9. **Phase 2 — note only:** now bump `quick_update.txt` to `N` (the id before
   `|||`) and update its footer. Every user-facing quickfix/AI release needs a
   fresh id plus a gentle Hebrew title/body; changing only the footer never
   triggers delivery. Have the separate reviewer approve this one-file diff,
   commit/push it alone, and do not call the release live until the public raw
   URL returns the exact new note. A notification-only re-announcement needs
   only this phase because no artifact/manifest pairing changes.
9b. **Regenerate the note archive AFTER writing the new note:**
   `python3 tools/build_recent_updates.py`, then commit
   `wizard/assets/notification_files/recent_updates.txt` with the note. It
   reads the working copy first, so running it before the note is written
   publishes an archive missing the very update announcing it. It is capped at
   ten and verifies its own output round-trips.
10. Wizard delivery invariant: never persist the new note id until
    `quick_update()` succeeds, and success requires extraction `(100%, 0 errors)`.
    False, exception, partial extraction, corrupt ZIP or a missing versioned
    manifest must preserve the prior id so the next startup retries.

## Android / Windows / webOS package release (21.3-povil.48 baseline)

These rules encode the failures found in release `.47`; do not revert to the
older platform workflow.

### Verified `.48` release record (2026-07-25)

- The implementation shipped through PR #380 (`81e7f2a`), followed by the
  transparent-alpha artwork verifier correction in PR #381 (`198fdaa`) and the
  Android package-metadata guard in PR #383 (`a29b591`). The final clean build
  is workflow run `30137185730`; release:
  `https://github.com/MoranTheKing/Kodi-POV-IL/releases/tag/v21.3-povil.48`.
- An earlier `.48` attempt exposed that apktool's `versionInfo` still carried
  upstream `versionCode=2103000`. That temporary release and tag were deleted,
  its pointer PR #382 was closed unmerged, and the final release was rebuilt
  with `versionCode=2103048`. Never restore the rejected shorthand `21348`.
- Stable/versioned release assets were downloaded and proved byte-identical.
  SHA-256: Android 32-bit
  `29421caff3c1d75709c607845461e27484432124512c09ed1927798a525e8dc9`,
  Android 64-bit
  `553c7162f23cbafbd619e7183864a5f3662f01eef290dd7fe03028f0eb436748`,
  Windows
  `0d6e7f2d8ca227e248c6cef872f2689ba10adbfae62016c148a29087d3916721`,
  and webOS
  `f82ab46528450f5ade730604683985ab2fb0d8a726503a820d36d864cf7ee6c9`.
- Both APKs passed package/version/ABI/artwork/marker/zipalign and v1/v2/v3
  signature verification. Their signer certificate matches the downloaded
  `.47` APK (`b69d63b652d991ca78bbbf8aca3f034491696a4c36d6468c3a5a4685a65b5417`).
  The real webOS IPK passed the pinned-package structural and byte-preservation
  verifier. The real Windows EXE contains the exact pinned Kodi installer,
  build 0.1.101, Wizard 0.1.34 and canonical icon. The outer EXE remains
  unsigned; do not describe it as Authenticode-signed, and retain a clean
  standard-user Windows launch smoke test in future release gates.
- Pointer PR #384 merged as `7b5a21a`; raw and Pages pointers both showed
  `.48` after a 313-second cache gate. Quick-update note #541 was then reviewed
  as a one-file change and merged separately in PR #385 (`a69391e`). Pages run
  `30138021266` succeeded, and both raw and Pages returned the exact 541 note
  after a 392-second post-merge cache gate. No private backend or
  credential-bearing files entered either phase.

1. **One application release label, platform-native encoding.** Public pointers
   and Android/Windows package markers use `21.3-povil.N`. webOS metadata accepts
   only `x.y.z`, so `build_webos_ipk.py` maps that to `21.3.N` and writes the
   same value to `control`, `appinfo.json` and `packageinfo.json`.
2. **Wizard compares the POV package release, not Kodi core.** Wizard 0.1.34+
   reads `special://xbmc/system/povil-release.txt` and uses
   `resources/libs/common/release_version.py`. Never restore the old
   `float(pointer) > CONFIG.KODIV` code: every POV package is still Kodi 21.3,
   and hyphenated pointer labels cannot be floats. A missing marker is treated
   as `.47` only to bridge already-installed legacy packages to `.48`.
3. **Android update identity is permanent.** Keep package id `org.xbmc.povi`,
   the same encrypted keystore and an increasing `versionCode`. Existing users
   then install the new APK over the old one; uninstalling would erase their
   profile. Official Kodi can remain installed alongside it. Release `.47`
   actually reports the inherited upstream value `2103000`, so `.48` uses
   `2103048`; never use the smaller shorthand `21348`, which Android rejects as
   a downgrade. Patch apktool's `versionInfo` in `apktool.yml` (the decoded
   manifest omits these fields) and verify the final signed APK with
   `aapt dump badging`.
4. **Android TV branding is more than `ic_launcher`.** Some launchers use
   `res/drawable-xhdpi/banner.png`; Kodi also carries upstream art in
   `assets/media/`. Generate the banner, media icons and launch splash from the
   canonical logo/splash and run `platform_branding.py verify-apk` on the final
   signed APK. A build with even one upstream Kodi image must fail.
5. **Windows portable mode must be writable without elevating Kodi.** The
   runtime stays in `C:\Program Files\Kodi POV IL`, while Builtin Users SID
   `S-1-5-32-545` receives recursive Modify permission on `portable_data` only.
   Before invoking the upstream installer, move an existing full profile to
   the sibling recovery directory; restore it before any overlay. Abort without
   deleting either copy on a conflict. The Wizard must download the setup to
   `%TEMP%\Kodi-POV-IL-Updates`, never inside `portable_data` (a running EXE in
   that tree prevents the protective rename). Never auto-launch Kodi from the
   elevated installer. Treat any existing `portable_data` directory as a user
   profile, including empty/partial layouts, and check every recovery rename.
   Build a fresh profile in the installer-owned `portable_data-new` sibling and
   publish it by rename only after both build and Wizard extractions validate;
   this prevents a partial first install from being mistaken for a valid update
   on retry. Build `addon-manifest.xml` beside the original, require
   exactly one closing `</addons>` tag and successful writes/closes, then swap
   it only after protecting the original; restore the backup automatically if
   the second rename fails.
6. **Windows shortcuts are the launcher contract.** Create/refresh current-user
   and all-users `Kodi POV IL` shortcuts to `kodi.exe -p` with `povil.ico`.
   Do not patch the signed upstream `kodi.exe` icon resource; that invalidates
   its signature and increases AV/SmartScreen risk. The outer setup remains
   unsigned until a trusted Authenticode certificate is provisioned.
7. **webOS update identity is permanent.** Keep app/package id
   `org.xbmc.kodi`; changing it creates a second app and loses the in-place
   update path. Rebuild from the pinned official IPK with
   `build_webos_ipk.py`, not extract/re-tar shell commands. Preserve ar member
   order and original TarInfo metadata/untouched payload bytes, executable mode
   and `kodi-webos` bytes. Bundle only the Wizard and allowed pure-Python
   dependencies.
8. **Real artifacts are the gate.** The Action compiling successfully is not
   enough. Download both APKs, the EXE and IPK from the release; verify stable
   aliases, Android signature/package/version/artwork/marker, webOS numeric
   versions/id/native executable/artwork/marker, and the Windows embedded
   Wizard/build/icon plus standard-user ACL behavior on a clean VM.
9. **Publication is still two-phase.** First publish Wizard 0.1.34, quickfix
   0.1.483, mutable `build.txt`, immutable `build_versions/541.txt`, package
   workflow/docs and keep live note 540. Build and verify `.48`, merge the
   generated pointer PR, wait for raw/Pages caches, and only then publish note
   541. Existing `.47` users receive Wizard .34 through that quickfix and see
   the `.48` app update on the following startup.
10. **Repository scope is unchanged.** Platform packaging uses only the
    repository's public source and release artifacts. `pool/worker.js` remains
    the intentionally stale public copy unless a separately authorized Worker
    task says otherwise.
11. **Wizard ZIP publication has four synchronized targets.** Build with
    `tools/build_wizard_package.py --previous <old.zip> --manifest
    wizard/release_manifests/<release>.json --version <version>`. The versioned
    manifest explicitly lists replaced/added members and locks both input and
    output SHA-256, so it remains reproducible in a clean post-commit checkout
    without absorbing unrelated source drift. The versioned and `latest` ZIPs
    under both `dist/` and `wizard/` must be byte-identical, and every ZIP linked
    by `wizard/index.html` must exist. Newly added ZIP members use fixed
    metadata. Do not add a Wizard index link or update `latest` by hand.
12. **Legacy automatic package checks are marker-gated from Wizard 0.1.35.**
    Wizard 0.1.34 ran `kodi_version_update_check()` on every Android/Windows
    startup. Its missing-marker bridge classified a pre-marker package as `.47`,
    so quick maintenance could be followed by a full `.48` APK/EXE replacement
    dialog. Keep the startup hook, but an automatic check must return quietly
    when `povil-release.txt` is absent or invalid. A user-initiated manual check
    may still use the `.47` bridge, and marked `.48+` packages remain eligible
    for important future automatic package releases. The correction is Wizard
    0.1.35 (SHA-256
    `63b832ac192bac7148745e8f5fc0846c1647c74cf677c970de02aa161cf53dfe`)
    / quickfix 0.1.484 (SHA-256
    `1fa9e3ef7e995372a21ffebb81366271c7e9238f170c0e4c3d8f2b6c1b3feea8`).
    The release followed the two-phase gate: PR #387 / merge
    `3979e13380816a6939d134a414a0a4e9a43539b0` published the artifacts,
    `build.txt` and immutable `build_versions/542.txt` while note 541 remained
    live. Raw and Pages bytes were verified, Pages run `30146338621` succeeded,
    and the artifacts were re-fetched after the full 300-second cache window.
    PR #388 / merge `1acd25214f8201c5ee53772ceb5096011d502281`
    then changed only `quick_update.txt`. Note 542 (SHA-256
    `53476437396edb56ea7f35b11536e0d190a34d26a7592587912061da076cb0b3`)
    became exact on raw and Pages at 2026-07-25 09:02:53 Israel; Pages run
    `30146725554` succeeded. Existing note-541 users therefore receive the
    corrective quickfix, whose successful same-boot path exits Kodi before old
    startup code can continue to the package checker. Both independent reviews
    returned SHIP. `pool.py` remained byte-identical to 0.1.483 and no private
    Worker or streaming artifact entered the repository.

## Integrating third-party skin updates (playbook, learned the hard way)

The FENtastic skin receives updates from a community author as full-folder
zips. NEVER copy the folder wholesale; integrate file-by-file:

1. **Diff against the currently-shipped quickfix** and take ONLY files that
   actually changed (his zips re-ship everything, including files we already
   optimized or fixed).
2. **Scan deletions in every changed file** for OUR features (grep for
   MoranSubs / chooser / patcher markers / Hebrew labels). His base tree
   predates some of our baked-in fixes — re-splice what his copy drops
   (e.g. the pause-window `MoranSubsChooserOpen` visibility guard).
3. **XML regression gate**: a file that parses clean today must still parse
   clean after his update (raw `&` in plugin URLs is his recurring bug —
   escape to `&amp;`). Pre-existing quirk files are tolerated as-is.
4. **Exclude his personal `userdata` skin-settings snapshot** — shipping it
   resets every user's customizations.
5. **Feature gates must be unset-safe**: his view-locking rewrote view
   visibility to `Skin.String(lock.view.type)` equality checks that are
   FALSE for everyone until the string exists — every gated view rendered
   empty. Any skin-string gate must carry a `String.IsEmpty(...)` default
   branch. Scan for BOTH literal and `$PARAM`'d gate forms.
6. **A typo can be load-bearing.** His `fullscreenvidep` typo silently
   disabled half a visibility condition; "fixing" it changed a window's
   auto-open behavior and shipped a field bug. Author-tested behavior is
   the spec — never correct a third-party typo without re-deriving what
   the running behavior actually was.
7. Re-encode oversized preview PNGs to the display size before shipping.
8. Independent validation on every integration, and again on every fix.

## Arctic Fuse 3: what the shipped skin actually IS (learned 2026-08)

The AF3 in `dist/Kodi-POV-IL-AF3-skin-pack.zip` is **"Arctic Fuse 3 (Mod)"**
(provider "jurialmunkey, jamal2362") — upstream `jurialmunkey/skin.arctic.fuse.3`
plus a mod layer whose source repo is no longer public. The mod layer, extracted
by diffing against pristine upstream, is: `1080i/Includes_u3k.xml` +
`media/u3k/` + a DialogCustom u3k settings section, an extra OSD `button_9`
slot in `Includes_OSD.xml`, `left=120` in `Includes_Hubs.xml`, mod strings
`#31985-#31999` in en_gb/de_de po files, `language/resource.language.he_il/`,
`fonts/NotoSans-Regular.ttf`, `extras/icons/ppi.png`, and our 3 shortcuts
JSONs (homesubmenu / homewidgets / powermenu). The addon version carries a
**deliberate `6.` prefix** (upstream `3.2.14` ships as `6.3.2.14`) so no
external repo can ever auto-downgrade it; keep the prefix on every update.

**Updating AF3** (done for 6.3.2.9 → 6.3.2.14, upstream v3.2.9 → v3.2.14):
clone upstream, `git archive` the new tag, re-apply the mod layer (files
upstream didn't touch: copy ours verbatim; overlap files: 3-way merge with
`git merge-file`, unions resolved by keeping both sides), keep the Mod
identity line with the new `6.`-prefixed version, then rebuild the pack zip
(`addons/*` + `media/`). Gates: every XML parses, no duplicate msgctxt ids,
af3_*_patcher anchors still present, upstream-deleted files really absent.
v3.2.14 dropped `Custom_1192_HolidayTheme.xml` — Kodi loads any Custom_*.xml
that merely exists, so the wizard got `purge_before_extract` on the AF3 skin
pack (deletes the old skin folder after a successful download, before
extract). Upstream bumped `script.skinvariables` to 2.2.2 minimum, so the
pack's bundled copy was updated in the same release (deps still satisfied by
the deps-pack's jurialmunkey 0.2.35 / infotagger 0.0.8).

**How AF3 updates reach users:** the pack URL is FIXED (`AF3_PACK_BASE_URL`),
so fresh AF3 installs always get the current pack. Existing AF3 users update
via wizard `auto_update_active_skin_pack()` (extended in 0.1.37 to cover AF3,
not just NOX) gated by `AF3_CE_SKIN_VERSION` in `wizard.py` — bump that
constant on every pack update or nobody already on the skin re-downloads.

The crash "stop playback on AF3 → back to Home → force-close" is a KNOWN
upstream issue (jurialmunkey/skin.arctic.fuse.3 #230), reproduced on the
latest skin and closed "not planned" — a skin update does not fix it; the
honest user guidance is to use another skin if it bites.

## Wizard release gotcha: two artifact chains, one source of truth

The bundled-wizard quickfix chain and the standalone wizard ZIP chain both
claim to ship "the wizard", but `build_wizard_quickfix.py` replaces the WHOLE
wizard subtree from the standalone ZIP. Any source improvement that reaches
the quickfix chain but is never listed in a wizard release manifest gets
SILENTLY REVERTED by the next quickfix built from that ZIP -- this actually
happened in 0.1.506's first build: `startup.py`/`resources/settings.xml`
(quick-update retry-safety, `QUICK_UPDATE_MAX_TRIES`) had lived only in the
quickfix chain since 0.1.500, and the freshly-built quickfix downgraded them.
Caught by the release validator; fixed by adding both files to the 0.1.37
manifest, which realigned the ZIP chain with source. RULE: when building a
quickfix, diff the wizard subtree against the PREVIOUS quickfix and account
for every changed member -- an unexplained change is a regression, not noise.

## Umbrella pilot (opt-in, shipped 2026-08-08, note 569)

`dist/Kodi-POV-IL-Umbrella-pack.zip` = Umbrella 6.7.81 + CocoScrapers 1.0.39
+ BOTH official repository addons (assembled byte-identical from
umbrellaplug/umbrellaplug.github.io and not-coco-joe/repository.cocoscrapers;
validator re-verified every file). The umbrella repo addon folder is renamed
to `repository.umbrella` to match its addon id -- Kodi ignores a repo whose
folder differs from the id, and the official zip ships it mismatched.
Installed ONLY via the wizard menu entry "התקן Umbrella (ניסיוני)"
(main_menu.py -> router action install_umbrella -> wizard.install_umbrella_pilot
-> the shared _ensure_packs_installed machinery, gate UMBRELLA_PACK_VERSION).
After install both update straight from their developers' repos -- we are NOT
their update channel, same trust model as POV via repository.kodifitzwell.
Known gap: the MoranSubs release-name-matching niceties are POV-aware and run
"blind" on Umbrella playback -- the first hook to port if the pilot graduates.
Merging both engines' source lists into one dialog is NOT feasible and should
not be attempted.

The pilot's original "NO home tile, NO search wiring, NO defaults change" rule
ended with 0.2.474: Umbrella now has a home tile, a search switch and Hebrew
menus (below). The rule it was protecting still stands in its stronger form --
**nothing Umbrella-related exists on a device that has not installed
Umbrella**. Every one of those surfaces is gated on `xbmcaddon.Addon(
'plugin.video.umbrella')` succeeding, and the gate is checked at the moment
the surface is built, not stamped once.

## The search-engine switch: POV or Umbrella, all four skins (0.2.474)

One setting, `search_provider` (`pov` default / `umbrella`), hidden in
MoranSubs' settings.xml and owned by `resources/lib/search_provider.py`. The
user changes it from the "מנוע החיפוש - POV / Umbrella" home tile (FENtastic /
Estuary / NOX) or the matching AF3 submenu + power-menu row -- both of which
run `RunScript(service.subtitles.kodipovilai,action=search_provider)`.

**The provider is baked into the skin files, not resolved at click time.** A
RunScript forwarder on the search button would make switching instant, but it
puts a Python process launch in front of the most-used button in the build and
gives it a way to fail that it does not have today. Switching is rare;
searching is nightly. So the switch rewrites files and pays a `ReloadSkin()`.

Two shapes, because the skins genuinely differ:

- **FENtastic / Estuary / NOX** activate a HUB and the add-on takes over. One
  onclick per skin, written by `fentastic_search_patcher`. POV's hub is
  `navigator.search`; Umbrella's is `tools_searchNavigator`. NOX also has a
  main-menu search item carrying the bare path -- it now recognises whichever
  provider's path is in the file today, not just the one the skin shipped
  with, or the second switch would be a no-op.
- **Arctic Fuse 3** types the query IN THE SKIN and builds four result rows
  from `search_path.xml`, so switching means swapping four path prefixes
  (`af3_search_pov_patcher`). Umbrella has a term-driven action for all four
  (`movieSearchterm`, `tvSearchterm`, `actorSearchMovies`,
  `collections_Searchterm`), so AF3 keeps all four rows on either provider.
  The `DefaultSearch-POV*` TOKEN names are unchanged on purpose -- they are
  opaque keys shared with the searchwidgets node, and renaming them would
  break every row.

Two things that are easy to get wrong here:

- **The AF3 marker carries the provider** (`_marker(provider)`). A marker that
  ignored it would leave AF3 searching whatever it was first patched with, for
  ever, because `already_patched` would keep matching.
- **`current()` falls back to POV whenever Umbrella is not installed**, even
  when the stored choice says otherwise. A search button that opens a missing
  add-on is worse than one that searches the other one.

Both patchers already run at every startup, so the choice survives a skin
update that ships a fresh file and applies to a skin the user has not switched
to yet. `apply_to_skins()` reloads ONLY when the user is on a skin that was
actually rewritten (AF3 goes through `af3_home_patcher._rebuild_af3_shortcuts`,
which regenerates the includes first).

## Account Manager Lite (installed for everyone since 0.2.474)

`dist/Kodi-POV-IL-AcctMgr-pack.zip` = `script.module.acctmgr` 1.1.5a +
`script.module.acctvwr` 1.1.4 (a HARD dependency of acctmgr, in no repo the
build already carries) + `repository.709` 1.0.2, all taken verbatim from
github.com/Zaxxon709/zaxxon and assembled by `tools/build_acctmgr_pack.py`,
which refuses to build unless each zip's top-level folder equals the add-on id
inside it. Shipping the developer's repo means he is the update channel from
then on -- same trust model as Umbrella and as POV via repository.kodifitzwell.
Installed **automatically for every device** since 0.2.474, by
`wizard.ensure_acctmgr_for_everyone()` from `startup.py` -- once per device,
recorded in the wizard setting `acctmgr_auto`, gated on the build already
being installed, and NOT re-attempted if the download fails silently (no
marker, so the next boot retries). A user who uninstalls it afterwards is not
fought with. The manual entry "התקן Account Manager (ניסיוני)" (main_menu.py ->
router action `install_acctmgr` -> `install_acctmgr_pilot`) still exists.

Why it stopped being opt-in: POV's "חיבור שירותים" screen now authorises the
debrid accounts THROUGH Account Manager, so one connect reaches every add-on
instead of POV alone. Without it installed the same rows silently fall back to
POV-only. The screen looks identical either way, which is exactly why the
difference must not be left to chance.

### The services screen (`pov_services_patcher` v10)

Each AM-backed row REPLACES the POV-native one it covers rather than sitting
beside it -- two rows both labelled "real-debrid" is the confusion this set out
to avoid. POV's own class stays as the fallback wherever AM is missing, and one
clearly marked row at the bottom ("חיבור ל-POV בלבד (מתקדם)") still reaches the
untouched POV menu, so no failure inside AM can leave anybody unable to connect
POV at all.

THREE rows stay POV-only, each for a reason worth not rediscovering:

- **trakt** — AM 1.1.5a's `traktAuth` AND `traktReSync` both end in
  `os._exit(1)`: they FORCE-CLOSE KODI after a 3-second "Force Closing Kodi!"
  toast. `traktAuth` additionally calls `control.updates_off()`, silently
  turning Kodi's global add-on auto-updates off, and answering "no" to its
  "create your sync list now?" question falls off the end of the branch so the
  click does nothing at all. No other AM service does any of this. Report
  upstream alongside the SyncManager bug.
- **easydebrid** — AM writes `easydebrid.token` but never DECLARES it in its
  settings.xml, so the write is a silent no-op and its EasyDebrid rows are
  absent from its own settings screen. Routing it through AM connects nothing.
- **tmdblist** — AM has no TMDb service at all.

MDBList keeps OUR QR pairing (AM's is a bare keyboard prompt for the API key)
and hands AM the finished, validated key afterwards, then fires
`mdblistReSync`. Deliberately NOT mirrored on disconnect: AM's
`mdblist_auth()` pushes whatever key it holds and, for POV, also sets
`watched_indicators=2` with `mdbl_indicators_active=true` -- running it with a
BLANK key would point POV's watched-status provider at MDBList with no key.
Disconnect clears AM's own two settings and stops there.

AM's `<service>Auth` actions ALREADY run the sync themselves (auth -> push to
every installed add-on -> enable the startup re-sync). Never chain a `ReSync`
after an `Auth`: it syncs the same account twice and shows two progress runs.

What it is: one place to authorise Real-Debrid, Premiumize, AllDebrid, TorBox,
OffCloud, EasyDebrid, Easynews, Trakt and MDBList, which it then writes into
every supported add-on it finds installed (~25, POV and Umbrella among them).
Its `SyncManager()` re-pushes at EVERY Kodi startup, so an add-on installed
later picks the accounts up on the next boot without the user doing anything.

Note the source of the repo link: `Zaxxon709/repo` is only the repository
installer and has not been touched since 2024-04. The add-ons live in
`Zaxxon709/zaxxon`, which is actively maintained.

Four things established by reading 1.1.5a, so they are not re-derived:

- **Upstream bug, reported.** `am_masters()` returns `(... offcloud, torbox
  ...)`; `SyncManager()` unpacks `(... torbox, offcloud ...)`. So TorBox's
  startup sync is gated on the OffCloud token, and the OffCloud branch tests
  `oc_master_token` which that function never assigns -> `NameError` swallowed
  by the enclosing `except`, logged only as "Startup OffCloud Startup Sync
  FAILED". Manual sync from its settings screen is unaffected.
- **It patches other add-ons' source**, injecting a marker-gated, compile-
  validated Trakt-ordering snippet into `plugin.video.pov/resources/lib/
  service.py` and `plugin.video.umbrella/service.py`. Same discipline as ours
  and NO collision: our patchers touch POV's `modules/settings.py`,
  `caches/trakt_cache.py`, `modules/sources.py` and Umbrella's
  `resources/lib/modules/sources.py`. Keep it that way.
- **It sets Kodi's global `general.addonupdates` to 2** — "never check for
  updates" — via JSON-RPC in `control.updates_off()`, and never restores it.
  An earlier version of this note said "to 0 (install updates automatically)";
  that was wrong, and the direction matters: the setting STOPS add-on updates
  rather than forcing them. Only `traktAuth` calls it, which is one more
  reason the build's Trakt row does not go through Account Manager.
- **Uninstalling it without "revoke" first** leaves the add-ons carrying
  whatever it wrote. Its own string 40088 says so.

Privacy check: outbound hosts are the services' own APIs, raw.githubusercontent
for its self-update check, and paste.kodi.tv for log upload. No telemetry.

### NEVER bare-setSetting another add-on (0.2.470, note 573)

`xbmcaddon.Addon(other_id).setSetting(k, v)` is not a targeted write. Kodi
loads that add-on's ENTIRE settings.xml into memory, changes one value and
re-serialises the whole file (`Addon.cpp`: UpdateSetting -> SaveSettings ->
SettingsToXML). On the load leg `CAddonSettings::Load` only WARNS and keeps the
DEFAULT when a stored value fails the definition's current constraints, and the
save leg then writes that default to disk. One key of ours can therefore reset
a setting we never named. Every settings write into a foreign add-on goes
through `resources/lib/addon_settings_safe.py`: snapshot the stored values,
write only the named keys that really differ, read back, restore anything
foreign that moved, and return `failed` for anything that did not land.

Two rules that came out of it and apply to every future patcher:

- **A "done" marker records what LANDED, not what was attempted.** Marking a
  key done after a failed write disables the retry forever, and the only trace
  is a WARNING nobody reads. Read `failed` and withhold the marker.
- **A mute you set, you unmute unconditionally.** Umbrella mutes its own
  settings monitor via home-window `umbrella.updateSettings`; leaving it at
  `'false'` silently stops the add-on reacting to the USER's next settings
  change for the rest of the session.

Also settled while chasing a "the update reset my resolution" report, so it
does not get re-investigated: **Umbrella has no setting that filters 720p.**
The `remove.*` block (`sources.py:1011+`) removes codecs, audio, HDR, Dolby
Vision, CAM, SD, 3D and AI-Upscaled -- `remove.sd.sources` tests
`quality != 'SD'` and nothing more. `hosts.quality` ("Max Quality", filed under
Sorting and Filters -> Source Filtering Options, which is why users read it as
a filter) only picks a sort rank; with `'1'` it puts 1080p first, **720p
second**, and pushes 4K to the bottom. External-provider (CocoScrapers) results
are not exempt from anything: they land in `self.sourceDict`, flow into
`self.scraper_sources`, and are merged into `self.sources` at line 817, i.e.
BEFORE the filter block. More 720p after an update means more providers, not a
lost setting.

## Shipped 2026-08-13: note 591 (0.2.491 / wizard 0.1.45 / quickfix 0.1.536)

**The quick-update freeze.** Two of our own code paths ran at the same moment:
one refreshes the skin after an update, the other restarts POV so the update
takes effect. When they met, the home screen was rebuilt while POV could not be
constructed, every POV row on it raised "Unknown addon id", and POV's service
had to be killed. Root-caused from two field logs and confirmed by the reporter
applying the same update cleanly on NOX -- the one skin where that patcher does
not run, which is what identified the pairing.

Every skin reload on the update path now waits for POV to be constructible
first: both FENtastic patchers, the AF3 rebuild and its tools row, the search
switch, the service's tile reload (no skin gate at all, so it covers every
skin), and all three reload sites in the wizard. A reload that cannot go ahead
is deferred, logged, and left UNSTAMPED so the next run retries. No path
reports "applied" for an update that was not.

Measured per guarded site: POV healthy 0.00s, a real cycle 3.05s, POV not
installed 0.00s, POV switched off by hand 10.15s.

**Eleven adversarial rounds, and what each killed.** Worth keeping, because
every one of these reads sensible on the page:

| Design | Why it died |
|---|---|
| A shared counter in `Window(10000)` | Five rounds, each finding a new way it was wrong |
| A sticky "I have seen POV work" flag | The wizard's entry point is `reuselanguageinvoker=false`, so its interpreter is new every invocation. The flag could never be set there, on any platform, ever |
| A `_gave_up` latch | One transient JSON-RPC failure disarmed every guard in the process for the rest of the session |
| Asking JSON-RPC "is POV installed" | It answers the same for "unknown id" and "busy", and busy is the moment being guarded. Now a disk check |
| Splitting on `pending_enable` alone | `pov_reload` recorded nothing there, so a failed SERVICE cycle read as the user's own choice and the reload fired into it -- the original crash, through the check meant to prevent it |

Three of those blockers were code added mid-fix. The rule that caught them was
running the validator's own reproduction against the fold, every time.

**Also in 0.2.491:**

- `_ensure_pov_enabled` stopped re-enabling POV on no evidence. It ran on every
  boot and undid a user's deliberate choice silently -- and because
  `hot_reload`'s first act is to cycle the service, it completed before the
  wizard's own POV checks were even reached. It now acts only on a record
  `pov_reload` writes before disabling and clears only once POV can be
  constructed again. See "Two records, two questions" below.
- The last ten update notes, with a home tile on every skin. See that section.
- AF3's un-seeded submenu slots, and the version constant that asked every AF3
  user to upgrade on every boot. See the AF3 section.

## Two records, two questions (the tile durability rule, got wrong twice)

`recent_updates_tile_patcher` seeds one favourites tile. Its "do not put back
what the user removed" rule was wrong in both directions before it was right,
and both wrongs came from answering with one record what needs two.

- Marker as a comment INSIDE `favourites.xml`: the wizard's
  `update_favourites_xml_file()` copies a static per-skin seed over that file
  on every skin switch, so the marker died with it and a DELETED tile came
  back.
- Marker as a sidecar file: it survives the copy, but it says "we have offered
  this", which is true forever -- so a tile the same copy removed from someone
  who never touched it was never restored. Silent and permanent.

The two questions are separate: *is this still a file we edited* (a comment
beside the tile -- its ABSENCE proves the file was replaced) and *did the user
tell us to go away* (the sidecar, recording a deletion, written at the moment
the comment still proves it was one). `favourites_xml_patcher` already does
this with its anchor tile; this now does it too.

Known hole, deliberately written into the code: deleting the tile and switching
skin with no service run in between. The tile returns once; delete it again and
the next start records it for good.

## The last ten update notes (0.2.491)

`tools/build_recent_updates.py` regenerates
`wizard/assets/notification_files/recent_updates.txt` from the git history of
`quick_update.txt` itself, so the archive is the text users were actually
shown and cannot drift from it. Ten is enforced AT GENERATION, not left to the
reader -- a reader that trims is one bad release away from shipping ninety.

Parsed by splitting on a header at the START OF A LINE, never on any `|||`:
a body mentioning `|||` mid-sentence would otherwise tear a record in half and
shift every one after it.

Reachable at `plugin://plugin.program.kodipovilwizard/?mode=recentupdates`,
plus a favourites tile on the three skins that use favourites and a
`HOME_SUBMENU` row on AF3, which does not.

**Regenerate it at every release, in phase 2, after `quick_update.txt` is
written** -- it reads the working copy first so the new note is in its own
archive.

## Arctic Fuse 3 leaves four submenu slots un-seeded (2026-08-13)

A user's Kodi force-closed on opening a submenu after playback. AF3 declares
FIVE submenu slots in its generator data -- `homesubmenu`, `1101submenu`,
`1102submenu`, `1103submenu`, `1104submenu` -- and ships a stock node file for
the first one only. `Includes_Home.xml` builds the include name from the slot
at parse time, so reaching a slot with no node leaves
`<include>skinvariables-1102submenu-staticitems</include>` unresolved. Kodi
keeps the unresolved element rather than dropping it, the directory provider
reads the literal string `"include"` as a path, and the process dies. The
user's exact final log line reproduces from that mechanism.

NOT OUR BUG -- verified against a clone of the real skin, the pack we ship, and
`script.skinvariables`, plus running `af3_home_patcher` end-to-end against a
fake filesystem: it creates and deletes none of those files. It is our users'
crash though, so the four numbered slots are seeded EMPTY. Empty on purpose:
real entries would put items in a submenu nobody built. It does not make a slot
visible either -- AF3 gates that on `HomeSwitcher.<id>.Toggle`, a string this
repo never sets. A slot the user has populated is left byte-for-byte alone.

**And a version constant that had rotted.** `af3_home_patcher.AF3_CE_VERSION`
was `6.3.2.9` while `wizard.AF3_CE_SKIN_VERSION` had moved the shipped pack to
`6.3.2.14`, and the gate compared with `==`. So it read as "is the skin the
version we ship" and behaved as "is it any other version at all": every AF3
user already on the correct pack was asked to upgrade on every boot -- a
progress dialog and five add-on re-registrations, forever, for nothing. Fixed,
and the comparison is now `>=` like the wizard's own gate, so the next constant
left behind costs nothing instead of costing a dialog a day.

## The startup repair pass runs inline on main, on purpose (2026-08-13)

There was a `_start_build_startup_repairs()` that put the pass on a daemon
thread, and nothing ever called it. Deleted rather than wired up, because two
things depend on the pass finishing before `main()` moves on:

- `pov_reload.wait_until_settled`'s bounds (30s, and 10s for an outage we did
  not cause) were chosen BECAUSE three of its four callers are steps in that
  inline pass, where a wait is not a delayed reload, it is the subtitle service
  not starting. Off the main thread those numbers would have to be re-derived.
- `_publish_repairs_state` / `REPAIRS_DONE_PROPERTY` is what the wizard's
  `hot_reload` waits on before it cycles anything.

Moving it is reasonable to want; doing it by accident is not, which is what a
dead function sitting there invites.

## Shipped 2026-08-12: note 589 (0.2.489 / wizard 0.1.44 / quickfix 0.1.534)

One day, one release, nine code changes, six adversarial validation rounds.
Every finding below was reproduced by execution before it was folded.

- **A fresh install could not start at all.** See "Never log before the folders
  exist" below. Wizard 0.1.43.
- **POV's five cache tables rebuilt** after POV auto-updated itself and
  reordered their columns, and the **favourites** it orphaned copied across.
  See "POV auto-updates itself out from under the build".
- **The watched tick** stopped appearing on unwatched items in the album-icons
  view, and started appearing in the Poster view where it never had. See "The
  watched tick: two opposite reports, one source of truth".
- **MDBList in My Movies / My Series**, from the file Account Manager actually
  writes rather than Kodi's in-memory copy, with each tile placed beside its
  own kind.
- **The recovery record** for an add-on left disabled by an interrupted update:
  it survives a dead JSON-RPC, a full disk and a squatted temp name, and is
  only dropped when Kodi actually says the add-on is gone.

Two release-process lessons worth more than the fixes:

1. **The wizard ZIP was built before the last two folds touched wizard.py**, so
   it shipped without them. The "two artifact chains" gotcha, hit again. What
   caught it was `tools/test_platform_packages.py` after it was retargeted from
   a historical version to the current one -- so keep that test pointing at the
   release being shipped, and compare each artifact to its OWN predecessor.
2. **The same performance trap was walked into twice in one day**: a regex with
   `.*?` anchored at the end costs O(n^2) on input that never closes.
   `_strip_comments` was rewritten to escape it in the morning and `_trim_tail`
   reintroduced it in the afternoon (98 seconds on 64k unclosed comments, on a
   call that runs while a menu is drawn). If a scanner walks text, walk it once.

## Umbrella scrapes a TV show with whatever title it was handed (open)

Field report: "In Treatment S02E12 in Umbrella gives sources for completely
different shows." The log settles it in one line -- the same episode, the same
evening:

    22:53  tvshowtitle='In Treatment'  -> In.Treatment.S02E12...x264-CasStudio, played
    23:01  tvshowtitle='בטיפול'         -> unplayable, three times

Umbrella scrapes with the title it is given. No torrent is named "בטיפול
S02E12", so the only results are whatever matched the S02E12 pattern alone --
in the screenshot, anime from NYAA.

It is not a bug in Umbrella so much as an asymmetry in its own settings.
`sources.play()` calls `imdb_meta_chk()`, which asks IMDb for the canonical
title by id and replaces the one it was handed -- but only when the flag is on:

    movies:   imdb.Moviemeta.check = true   imdb.Movietitle.check = true
    tv shows: imdb.Showmeta.check  = false  imdb.Showtitle.check  = false

So films scrape with their English title and series scrape with the Hebrew one.
On an English build nobody ever notices. POV is unaffected because it keeps the
original title for scraping.

THE FIX seeds those two show-side settings to true, through
`addon_settings_safe` like every other Umbrella setting this build sets, once
each and respecting a user who later turns them off. It is exactly what
upstream already does for movies. `imdb.Showyear.check` is deliberately left
alone: the year is not what is wrong, and changing more than the reported fault
is how a fix earns a bug report of its own.

Measured cost: one IMDb suggestion request per explicit play, 0.3-1.1s in
fifteen live calls, on the path before the sources window opens. Zero requests
when rendering an episode list. Every failure -- no id, timeout, junk JSON --
falls back to the title it was handed and never breaks playback.

THREE KNOWN GAPS, all validated, none blocking:

1. **Continuous playback bypasses it.** `prescrapeNext()` calls `getSources()`
   directly and `imdb_meta_chk` lives only in `play()`, whose `preResolved`
   branch also returns before the gate. A user who turns Umbrella's
   "Continuous playback" on still scrapes every episode after the first with
   the displayed title. That setting is off by default and this build ships no
   Umbrella settings file, so it is opt-in -- but closing it means patching
   Umbrella's own source, not a setting.
2. **`imdb_meta_chk` never checks that the reply is about the id it asked
   for.** A malformed or wrong-entity id makes the endpoint fall back to fuzzy
   search and return an unrelated title, complete with a year, which passes its
   only sanity check. Pre-existing -- movies have had this exposure since
   upstream shipped their flag true -- but this makes it reachable for shows.
3. **IMDb's canonical title is occasionally a worse match than the one we
   had.** tt1877368 answers "The Great British Baking Show" where releases use
   "Bake Off". Umbrella already hardcodes a workaround for one such title, so
   the class is known upstream and only partly handled.

## POV auto-updates itself out from under the build (2026-08-12, critical)

The build ships POV 5.12.04 **and** `repository.kodifitzwell`, the POV author's
own repo, and the build's `guisettings.xml` has `general.addonupdates = 0`
("install updates automatically"). So on the first launch after a fresh
install, Kodi replaces our POV with whatever that repo publishes -- today
6.08.10. That is legitimate and there is nothing to "fix" about it, but two
consequences bite every one of our users and nobody else:

**1. Five cache tables poisoned.** POV 6 reordered the columns of its own cache
tables and kept `CREATE TABLE IF NOT EXISTS`, so on an UPGRADE the old table
survives -- and POV 6 writes to it positionally, with no column list:

    5.12.04:  maincache (id, data, expires)      6.08.10:  maincache (id, expires, data)
    INSERT OR REPLACE INTO maincache VALUES (?, ?, ?)   <- no column names

The expiry lands in the payload column and the payload in the expiry column.
Everything that reads a cached list gets an int. It never expires either: the
test is `expires > ?` and in SQLite TEXT always compares greater than INTEGER.
Affected: `maincache`, `metadata`, `season_metadata`, `function_cache`,
`results_data`. Symptoms reported from the field: search errors with
`TypeError: 'int' object is not iterable`, and empty or missing
popular/new widgets. A device that installs POV 6 CLEAN never sees any of it --
only a device that came through the build.

**2. Favourites orphaned.** POV 5 kept them in `favourites.db` (`favourites`);
POV 6 keeps them in `watched.db` (`favorites`) and migrates nothing.
`traktcache4.db -> traktcache.db` and `providerscache2.db ->
providerscache.db` moved too, but both refill themselves within a sync.

`resources/lib/pov_cache_schema_patcher.py` repairs both, reading POV's OWN
declarations out of its `cache.py` rather than keeping a copy here -- POV has
changed these once already. It rebuilds a table only when the column NAMES
match and just the order differs, only for a closed list of caches, and it
restores the declared indexes in the same breath (DROP TABLE takes them with
it). Watched status, resume points, views and the navigator lists are out of
scope by rule and by name.

**When POV next changes version, diff the CREATE statements first.** The whole
class of bug is invisible in a normal review: nothing in POV's diff looks
dangerous, and the damage only appears on machines that had the previous
version.

## Never log before the folders exist (2026-08-12, cost: every new install)

The hot-reload heal pass was placed at the top of the wizard's `startup.py`, on
the reasoning that nothing should need a disabled add-on before it is back. But
`import resources.libs.wizard` reaches `custom_save_data_config`, which logs one
line at IMPORT time, and `logging.log` opens the wizard log with `'w+'`. On a
fresh profile `addon_data/plugin.program.kodipovilwizard` does not exist yet, so
the open raised `FileNotFoundError` out of an import statement -- and the
handler below it logged too, and raised again. `startup.py` died before doing
anything, and the build could not be installed at all.

Three rules, locked by `tools/test_wizard_startup_order.py`:

1. `tools.ensure_folders()` runs before anything imports the wizard package.
2. A handler for "the log could not be written" uses `xbmc.log`, never
   `logging.log`.
3. `logging.log` creates its own folder and never lets a file failure escape to
   its caller. The Kodi log line is already out by then; an import-time logger
   that raises takes down whatever imported it.

Note the recovery problem this created: the crash happens at line 819 and
`auto_quick_update()` is called at line 949, so an affected device never checks
for updates again -- and our repo channel serves only the subtitles add-on, not
the wizard. The way out is a MANUAL quick update from the wizard UI
(`default.py`, a different entry point), which also creates the missing folder
as a side effect and unsticks the startup service permanently.

## The watched tick: two opposite reports, one source of truth (2026-08-12)

"No tick in the default view" and "a tick on EVERYTHING in this one view" are
the same bug seen from both sides, and both are fixed against
`WallWatchedIconVar` (gated on `Integer.IsGreater(ListItem.Playcount,0)`),
which is what the views that behave correctly already read.

The view users call **"סמלילי אלבומים"** is `View_630_AdvancedList`. The skin
does not name it: its container is a `<control type="fixedlist" id="630">` with
no `<viewtype>` element, so Kodi labels it from its own table -- string 541,
"Album icons". (Same table gives 20021 "Poster" = "כרזה", which is the
cross-check.) It builds rows from `ViewTypeBaseLayout_`, used by nothing else
in the skin, which drew its icon from `$VAR[ListPVRRecordingsIconVar]` -- the
PVR RECORDINGS variable, whose third rule is a hardcoded `OverlayWatched.png`
for ANY non-empty overlay. POV and Umbrella set an overlay on unwatched items
too, so every row got a tick.

Two things worth keeping: skin XML in this build is NOT valid XML to a strict
parser (raw `&` inside skin expressions), so pre-write checks must parse the
rewritten BLOCK, not the file. And any scanner over skin markup must skip
comment regions -- this build's own `MyVideoNav.xml` keeps two whole views
commented out, and a dead copy of a block will otherwise win the search.

## Resolved questions (so they don't resurface)

- **FENtastic DialogSubtitles "row height" marker (investigated 2026-07):**
  the shipped skin carries the `AI_SUBS_DIALOG_ROW_HEIGHT_v1` marker while
  its rows are 75px. That is a DELIBERATE bake-out: the current picker
  design is a compact single-line row whose release-name label has
  `<scroll>true</scroll>` in the focused layout — long names marquee-scroll
  when focused, nothing is clipped. The row-height patcher targeted the OLD
  two-line-wrap design and must stay no-op'd on FENtastic. Do not "fix" it.

## POV is patched at THREE layers — know which one renders (critical)

POV self-updates (users jump from the build's bundled 5.12 to 6.07+ from an
external repo), and it moved files between releases. When Hebrew-ising or
fixing POV, remember:

1. **Source `.py`** (`menu_lists.py`, `menus/` or `indexers/navigator.py`,
   `modules/dialogs.py`, ...). Patching these only affects behavior POV
   computes fresh. `navigator.py` lives in `indexers/` on 5.12 and `menus/`
   on 6.07 — patchers must try both paths.
2. **reuselanguageinvoker** — POV keeps a live Python process across a
   session, so a `.py` patch applied at our service startup is NOT re-imported
   until POV cycles. Call `pov_reload.note_patched()` after a `.py` patch to
   cycle POV the same session (guard: only on a real `patched`, or it loops).
3. **navigator.db + Window(10000) cache** — POV renders the MAIN MENUS from a
   STORED copy in `special://profile/addon_data/plugin.video.pov/navigator.db`
   (table `navigator(list_name,list_type,list_contents)`, `list_contents =
   repr(list)`), seeded ONCE from `menu_lists.py`, and memoised in
   `Window(10000)` props `pov_<list>_<type>`. So a `menu_lists.py` patch alone
   NEVER changes an existing install's menu — you must rewrite the DB rows AND
   clear the memory props. This is exactly what `pov_anime_hebrew_patcher.py`
   does (anime rows only, name tokens only, other lists byte-identical). The
   personal-area rows are handled the same way by `pov_navigator_patcher.py`.

## Gemini API auth

Calls use the `x-goog-api-key` HEADER, not `?key=` (newer `AQ.`-prefixed keys
401 on the query param). One credential per request. `gemini.py` only.

## Gemini model config (0.2.434)

Default free model = **`gemini-3.5-flash-lite`** (500/day tier), paid "newest" =
**`gemini-3.6-flash`** (20/day tier). Dropdown also keeps 3.1-flash, 2.5-flash-
lite, 2.5-flash. To change models, touch ALL of: `settings.xml` (`<default>` +
`<option>` values + the numeric labels 32230/32234), `language/*/strings.po`
(label text), `gemini_quota.py` `MODEL_LIMITS` + `MODEL_TRACKED`, and the code
fallbacks in `translate.py`, `subsync.py`, `default.py`, `gemini.py:test_key`.
RPM cap (`translate._gemini_free_rpm_cap`) + flash-lite detection are SUBSTRING-
based ('flash-lite'/'flash'), so new ids auto-tier. Existing users are migrated
by `service._maybe_bump_gemini_model()` (marker `_gemini_model_bump_v1`, DECLARED
in settings.xml) — rewrites only the two exact superseded ids, once. The model
ids follow Google's `gemini-<ver>-flash[-lite]` pattern; NOT verified against the
live API here — confirm a translation works on-device after any model change.

## autosub live/IPTV guard

`autosub_service.py` skips the auto Hebrew search for live playback: PVR
protocol paths, a non-empty `VideoPlayer.ChannelName`, zero `getTotalTime()`
(5 s grace), and a configurable addon exclusion list `autosub_excluded_addons`
(default `plugin.video.idanplus`). All fail-open.

## MDBList integration — status (0.2.425–0.2.437, all shipped)

The full chain works: QR pairing, watched/progress sync, list manager, account
heal, Collection routing + crash-safe sync. Delivered across seven releases:
- **0.2.425 / qf 0.1.464** — QR pairing for MDBList (like the other services),
  replacing manual key entry. Phone form reuses `gemini_pair` transport
  (`mdblist_pair.py`); connect writes POV's `mdblist.token` + `mdblist_user` +
  `mdbl_indicators_active` + `watched_indicators` via a forwarder injected into
  POV's My Services (`pov_services_patcher._AiMDBList`, INJECT_VERSION 9);
  `default.py` `connect_mdblist` flow. Connect aux-writes are gated on a verified
  token; manual entry is binary-with-retry.
- **0.2.426 / qf 0.1.465** — pair-window port was invisible: 6-digit
  `[COLOR=ffd166]` = Kodi alpha 00 = fully transparent. All pair-window colours ->
  8-digit opaque (also fixes the Gemini pair window). `_run_pair_qr`/`_PairWindow`.
- **0.2.427 / qf 0.1.466** — `pov_mdblist_patcher.py` (boot patcher for POV 6.x
  `indexers/mdblist_api.py`): (A) scrub apikey out of POV's error log; (B) on
  mark-watched POST `scrobble/stop`@100 by tmdb id (POV's `scrobble/clear` 404s)
  so the title clears PAUSED + counts in Watch Stats. Anchors on the `success =
  result[...]` line inside `mdbl_watched_unwatched`; guarded to mark_as_watched +
  key=='tmdb' + movies/episodes; the erase-bookmark path is untouched.
- **0.2.428 / qf 0.1.467** — `heal_mdblist_account()`: POV keys the whole account
  on `mdblist_user` (`mdblist_api.py:332` `if not get_setting('mdblist_user'):
  return 'no account'`), NOT the token. A connect that stored an empty username
  left the account "inactive" (manager "No results", sync monitor aborts) while
  direct scrobbling still worked (token-based). Heal on boot: token set + user
  empty -> fetch username from `/user` -> store it. POV's `onSettingsChanged`
  invalidates its `pov_settings` cache so the write takes effect ~immediately.
- **0.2.429 / qf 0.1.468** — Collection button crash (Hebrew UI). POV routes the
  Watchlist/Collection buttons by their English label text; our Hebrew translation
  of "Collection" -> "קולקציה" made POV treat it as a user list by that name, POST
  to a non-existent list (404) -> None -> crash. Fix D (`ensure_manager_patched`,
  `menus/mdblist.py`): stable English ids `[('watchlist',...),('collection',...)]`,
  Hebrew stays in the DISPLAY label. Fix C: None-guard the add/remove result.
- **0.2.430 / qf 0.1.469** — Collection post-add sync crash (Fix E, `ensure_patched`
  in `pov_mdblist_patcher.py`). After Fix D correctly routed to `add_to_collection`,
  POV's post-add `mdbl_sync_activities()` still crashed: `reset_activity()` returns
  the raw DB row (a TUPLE) instead of a dict when the cached `mdbl_get_activity`
  row can't be eval'd back (and skips its self-heal write), so `cached['...']` ->
  "tuple indices must be integers" on every sync (periodic monitor + Collection
  button). Guard right after `cached = mdbl_cache.reset_activity(latest)`: if
  cached/latest isn't a dict, `clear_all_mdbl_cache_data(refresh=False)` once
  (rebuilds a clean dict next run) + `return 'failed'`. Also covers a non-JSON API
  response (`latest` as str). Marker `AI_SUBS_MDBL_SYNC_GUARD_v1`. Sonnet: SHIP.

KEY MDBList API facts (probed with a dummy key: 401 = endpoint exists, 404 =
missing): `scrobble/start|pause|stop`, `sync/watched`, `sync/collection`,
`sync/playback` all exist; `scrobble/stop`@>=80% marks watched + finalizes
(clears) the session; there is NO DELETE on `sync/playback` (405). Account
activeness = `mdblist_user` non-empty. Username field is `username` (matches POV
native `result['username']`).

REMAINING (Phase B, the NEXT stage): MDBList **home tiles per skin** ("My Movies
(MDBList)" / "My Series (MDBList)"), like the existing Trakt/TMDB/POV tiles, with
baked images — per-skin mechanisms as in `scratchpad/MDBLIST_INTEGRATION_PLAN.md`.
Manager-add + Continue-Watching/watched sync are DONE.

- **0.2.431 / qf 0.1.470** — Watchlist-only manager: DROP the Collection button.
  The reporting device runs a POV build we don't have cached, whose
  `mdbl_sync_activities` crashes in a `for key, args, func in (...)` loop at a
  spot Fix E's anchor doesn't dominate (`tuple indices must be integers`). Rather
  than chase a per-version anchor, we removed Collection from the manager
  entirely (`ensure_manager_patched` now emits a single `('watchlist', ...)`
  choice; marker bumped STABLE_IDS_v1 -> WATCHLIST_ONLY_v2 so v1 devices
  re-patch; upgrades from either the original localised-id anchor or the 0.2.429
  two-choice line). MDBList "Collection" marks OWNED media -> meaningless for a
  streaming build, so nothing actionable is lost. POV still appends its own
  'dropped' toggle for shows. Fix E retained as defense for the periodic monitor.

Net: Watchlist add/remove + watched/progress sync are the supported surface;
Collection is intentionally gone. Watchlist unaffected throughout.

### Phase B — home tiles (task #68). FIRST SLICE SHIPPED: 0.2.432 / qf 0.1.471.
Decision (budget): tiles read the **MDBList Watchlist split by media type**, NOT
separate auto-created lists — one cached POV watchlist read serves both, so it's
budget-safe on the 1000 req/day free key.
- **Exact POV routes (verified in pov607)**: `action=mdblist_watchlist` with
  `mode=build_movie_list` (movies only) vs `mode=build_tvshow_list` (shows only).
  POV returns the watchlist mixed and its movies/tvshows Menu picks the type — no
  URL media-type param. Icon inside POV: `mdblist.png` (present in POV skin media).
- **Tiles (all skins, via favourites)** — DONE:
  - Branded PNGs `Twilight/{Movies/My_Movies_MDBList,Shows/My_Shows_MDBList}.png`
    (512² RGBA). Generator: `scratchpad/gen_mdblist_tiles.py` — clones the POV
    variant tile, swaps ONLY the top-right logo box (diff bbox 285,109-415,202)
    with an MDBList wordmark badge (teal "MDB"/navy "List" on white panel).
    Auto-install via build_icons_patcher (new files → no stale texture cache).
  - Two `<favourite>` entries in `resources/fixtures/favourites_fentastic_canonical.xml`
    (grouped with the POV personal tiles) → clean installs + skin seeds get them.
  - `favourites_personal_tiles_patcher._insert_mdblist_tiles`: opt-in, GATED on
    `_mdblist_connected()` (POV `mdblist.token` set), add-only, fire-once via the
    json sidecar key `mdblist_tiles` (+ marker AI_SUBS_FAVOURITES_MDBLIST_TILES_SEEN_v1).
    Non-MDBList users: byte-identical no-op. Deletions stick. Sonnet: SHIP.
- **tiles parity — DONE (0.2.437 / qf 0.1.476).** favourites already covered every
  skin; the two skins that keep their OWN native home structure now show it there
  too, routed to the SAME `mdblist_watchlist` action — so the newest-first sort
  (Fix F/G) is INHERITED, never re-implemented in the skin layer:
  1. **FENtastic navigator.db** — `pov_navigator_patcher.py`: `MOVIES_PA_V5` /
     `TVSHOWS_PA_V5` = V4 + an appended `{'action':'mdblist_watchlist',
     'iconImage':'mdblist', 'mode':'build_movie_list'|'build_tvshow_list', 'name':
     '[B]…(MDBList)[/B]'}` row (LAST, matching favourites order). Target is
     connection-aware: V5 (known_old V1..V4) when `_mdblist_connected()`, else V4
     (known_old V1..V3). Byte-exact migration; add-only (disconnect keeps V5;
     user-customized rows left alone). `iconImage:'mdblist'` short-name resolves to
     POV's already-shipped `mdblist.png`.
  2. **Arctic Fuse 3 skinvariables** — `af3_home_patcher.py`: 2 `HOME_WIDGETS`
     entries (after Trakt in each group), `PATCH_VERSION` v20->v21 (forces the
     rebuild so the merged node surfaces), gated in the FILES loop (canonical
     filtered of any `mdblist_watchlist` path when not connected). The existing
     3-way `_merge_widget_nodes` appends them brand-new to existing installs and
     honors user deletions. Icons `My_{Movies,Shows}_MDBList.png` already ship and
     deploy via `build_icons_patcher` (unfiltered os.walk). Sonnet: SHIP
     (byte-exactness re-derived in a Python interpreter); 18/18 local behavioral
     tests (navigator migration over real sqlite + AF3 merge over a mock FS,
     covering connect/disconnect/reconnect/user-removed/customized).
  Manager-add + watched/progress sync already done. Continue-Watching (Phase D)
  still deferred (series via /upnext if POV scrobbles episodes; movies stay local).
- **0.2.433 / qf 0.1.472 — recency: newest-first sort + Watchlist∪Collection merge.**
  1. `pov_mdblist_patcher.ensure_lists_sort_recent()`: one-time flip of POV's
     `sort.watchlist` + `sort.collection` from default 0 (A-Z) to 1 (date-added
     desc), only when at default (respects a deliberate choice), gated by hidden
     marker `_lists_sort_recent_v1`, declared in settings.xml. **The reason
     recorded here at the time was wrong** and is corrected in the entry below
     on undeclared markers: they DO persist. Declaring them is house style, not
     a fix. Governs
     MDBList/Trakt/TMDB watchlist+collection views; skin-independent.
  1b. **Fix G (0.2.435) — the sort actually working.** The 0.2.433 `sort.*`=1
     write did NOT take: POV serves settings from a cached `pov_settings` window-
     property JSON (`SettingsManager._sync`), and a boot-time cross-addon write
     never invalidates it (POV isn't running then) -- so `lists_sort_order` kept
     reading the old default 0 (Title) and a just-added title stayed at the
     bottom. **Lesson: cross-addon setSetting to POV does NOT reliably reach POV's
     running reads; patch the READER instead of writing the value.**
     `ensure_sort_default_patched()` patches POV `modules/settings.py`
     `lists_sort_order()` -> returns 1 (Date Added) when stored is 0/empty, for
     `watchlist`/`collection` ONLY (progress/watched byte-unchanged; those share
     the fn). Deterministic; marker `AI_SUBS_SORT_RECENT_DEFAULT_v1`. The
     setSetting migration is kept as best-effort so POV's sort menu also shows
     "Date Added" selected when the write does stick. Sonnet: SHIP.
  1c. **The three "My Movies/My Series" tiles route through DIFFERENT code** --
     this bit us: fixing one service doesn't fix the others.
     - **MDBList** tile -> POV's `mdblist_watchlist` (Fix G handles it).
     - **Trakt / TMDB** tiles (`trakt_my_movies` / `tmdb_my_movies`) -> OUR
       injected `_BLOCK_TEMPLATE` in `pov_menus_patcher.py`, which MERGES
       collection+watchlist+favorites. It was concatenating them (fresh watchlist
       add landed after the whole collection). **0.2.436** fixes the Trakt branch:
       append `(collected_at, media_ids)` and sort by date desc before unwrapping
       (POV maps listed_at->collected_at for the watchlist; None->'' so the
       all-string sort can't TypeError). Same template serves movies+tvshows.
       TMDB branch left as-is (no per-item date; API returns created_at.desc).
       Patcher is revert-then-reapply so no marker bump needed. Sonnet: SHIP.
     - NOTE: `resources/lib/pov_overrides/menus/*` is DEAD (nothing deploys it;
       pov_menus_patcher heals it away via STALE_OVERRIDE_MARK='_flex_call').
       The live merge is `_BLOCK_TEMPLATE`, NOT pov_overrides.
  2. **Fix F** in `ensure_patched()`: patch POV `mdblist_watchlist()` to append
     the Collection ("Recently Added", where a Trakt import lands) to the
     Watchlist -- deduped by tmdb id, each collection row reshaped to watchlist
     form (`release_date`='YYYY-01-01' from year for the unaired filter,
     `watchlist_at`=collected_at for the recency sort). So the EXISTING "My
     Movies/My Series (MDBList)" tiles show both lists merged, newest-first --
     NO extra tiles/images (a draft's separate "Recently Added" tiles were
     dropped as redundant per the user). Anchor: the unique
     `if not settings.show_unaired_watchlist():` line. Reuses POV's cached
     'mdbl_collection' object (no extra API). Fail-open. Global (POV's own
     MDBList Watchlist nav row merges too -- intended; 'all' path early-returns
     before the merge so only the movies/shows tiles merge). Sonnet: SHIP.

NOTIFICATION MISTAKE (now guarded): 0.2.426/427/428 first shipped reusing the same
`quick_update` note_id (only footer bumped) -> no notification fired. Fixed at
#525. The current two-phase checklist requires a fresh `N`, an immutable
`build_versions/N.txt`, and an independently reviewed note-only phase.

## Community-pool Worker — invocation & D1 cost control (free-tier survival)

The pool Worker (`povil-subs-pool`, `pool/worker.js` in the repo is a SANITIZED
public copy — the DEPLOYED worker is maintained privately and hand-deployed via
`wrangler`; it is NOT in git, see the `9effa41` revert). Free-tier ceilings that
bite: **100k Worker requests/day**, **D1 100k rows-written/day**, **D1 5M
rows-read/day**. We have been living right under the request cap (~99k/day), so
this is an ongoing discipline, not a one-off.

### D1 read cost — maintained pool-size counters (deployed worker)
The `/stats` dashboard used to size each prefix with `SELECT COUNT(*) FROM kv
WHERE k>='kt:'...` — a range scan that reads EVERY matching row (~13k for `kt:`),
~74% of all D1 reads and growing with the catalog. Replaced with O(1) integer
counters `cnt:v1:/sync:/kt:/emb:` maintained by the D1-KV shim's put/delete
(atomic upsert-increment via `meta.changes`; ai-safe torn-write fix: the else
branch is an atomic upsert, never a bare `UPDATE ... WHERE k=?`), lazily seeded,
and reseeded daily by the cron. Dashboard now reads one row per prefix. (This is
the D1-counter worker the user deployed as version `f73057c6`.)

### Worker-only invocation MEASUREMENT (no client/build change)
To find WHICH routes drive the ~99k/day WITHOUT a build push, the deployed worker
samples requests and reports a breakdown, readable by the owner:
- **`cnt:rt:<path>`** — sampled 1/20 in `fetch()` via `ctx.waitUntil(bumpRoute)`.
- **`cnt:cb:<outcome>`** — sampled 1/20 inside the `/contribute` pipeline
  (`bumpContrib`): pre-decision `auth_reject` / `bad_json` / `quality`, and
  post-decision `dedup_source` / `dedup_result` / `toomany` / `stored`.
- **`GET /routes?key=<STATS_TOKEN>`** returns both, scaled ×20, with
  `contrib_wasted_pct` and `est_per_day`; **`&reset=1`** clears the window.
- Sampling keeps the extra D1 writes ~5k/day each (safe). `cnt:rt:`/`cnt:cb:` are
  disjoint from the pool-size `cnt:v1:` etc. Bounded cardinality: unknown paths
  bucket to `other`. **Key interpretive rule:** the `/contribute` ROUTE est counts
  ALL POSTs; `contrib_est_total` counts only those reaching a dedup/store decision
  — the GAP is the pre-decision (auth/quality/json) rejects.

### The finding (measured 2026-07-24)
`/contribute` ≈ **53%** of requests, `/lookup` ≈ 47%. Within `/contribute`:
**`quality` (422) ≈ 76%**, `auth_reject` ≈ 13%, `toomany` (429) ≈ 11%, `stored`
tiny (~2-3k/day genuine — matches the maintainer's own count). So ~95% of
`/contribute` POSTs are wasted, dominated by the server's quality gate: the client
was uploading partial/failed translations (stayed mostly English) the server only
422s. Everything else (`/lookup` 90s client cache, `/ev` piggybacked on
`/contribute`, `/sdh` throttled) was already optimized in earlier tasks.

### Client fix — mirror the server's gates BEFORE the POST
`pool.py`:
- **`_srt_quality_ok(srt)`** — a BYTE-EXACT mirror of worker.js `srtQualityOk`
  (≥15 cues = count of `-->`; ≥200 Latin/Hebrew/Arabic letters; Hebrew ratio
  ≥0.5; ranges `0x590-0x5FF` heb, `+0x600-0x6FF` Arabic + `A-Za-z`). **Fails OPEN**
  (returns True on any error) so a genuine sub is NEVER withheld. Verified against
  a Python port of the server gate over 400 fuzz cases + the exact 0.5 boundary.
- **`_pool_at_capacity(body)`** — skips a contribute to an episode already at the
  server's `MAX_VARIANTS` (25) — the 429/toomany case — using the request-cached
  `_lookup_raw` (NO new request). Non-ai_emb only, so the ai_emb PROMOTION path is
  untouched (a good ai_emb passes the mirror and still uploads).
- Applied at the top of BOTH `_post` (async AI path) and `_post_sync` (durable
  Ktuvit drainer). In the drainer, quality/capacity → `'drop'`, which also FIXES A
  LATENT BUG: a real 422 there was previously misclassified `'retry'` and looped
  for up to 14 days.
- Why the cap stays at 25 (maintainer asked): it bounds the `/lookup` response
  size, the result-hash dedup's per-variant Telegram downloads (O(variants)), and
  the picker UX — NOT invocations. The client capacity-skip removes the wasted
  429s without touching the cap. Direct Ktuvit search still covers anything not
  pooled.
- Non-blocking nit (Sonnet): `share_cache()` bulk-share with an at-capacity,
  byte-identical-duplicate file won't write its `.shared` marker, so it re-checks
  every bulk run — zero network cost (the capacity check is a cached read),
  cosmetic only.
- **Expected effect after the corrected release propagates:** quality (~40% of
  all invocations) + toomany (~6%) stop being sent → ~99k/day toward ~50k/day.
  This is the crack.

### Packaging regression and urgent correction (2026-07-24)

- The optimization logic above was introduced in source for AI `0.2.438` /
  quickfix `0.1.477`, but those two distributed artifacts are **known-bad for
  community-pool authentication**: packaging left the public empty `_pool_key()`
  placeholder in their `pool.py`. Consequently, once Kodi loaded either update,
  authenticated `/lookup` and `/contribute` could not succeed. Do not use either
  artifact as the credential source for a future release.
- Corrected and shipped as AI `0.2.439` / quickfix `0.1.478` / notification
  `536` (commit `0696389`). Both were built surgically from the bad release while
  transplanting only the protected block from the last known-good `0.2.437` /
  `0.1.476`; the new gate logic outside that block remains byte-equivalent to
  `0.2.438`. Each zip retained the same member set/order and changed only
  `addon.xml`, `changelog.txt`, and `pool.py`. The standalone dist/latest/repo
  copies are byte-identical, and a signed live `/lookup` from the packaged client
  returned HTTP 200.
- `tools/build_ai_subtitles_packages.py` now fails hard when `pool.py`, its
  injection markers, `$POOL_SECRET`, the local helper, or a successfully
  injected non-placeholder block is missing. Warning-only keyless builds are
  forbidden. The public source placeholder and public stale Worker reference
  remain unchanged; the current Worker is still private and was not redeployed.
- The initial measurement clock for `0.2.439` / `0.1.478` was superseded by the
  delivery recovery and follow-up release below. Do not reset `/routes` against
  the incomplete notification-536 cohort.

### Quick-update delivery recovery and settings follow-up (2026-07-24)

- A maintainer-device screenshot showed Wizard state `quick_update_noteid=536`
  even though neither the update nor its note had been delivered. Wizard 0.1.32
  wrote the new id **before** download/extraction; a failed attempt then marked
  the note dismissed, so every later startup treated 536 as handled.
- Wizard `0.1.33` fixes the state machine: false/exception leaves the prior id,
  and the id advances only after a verified extraction result of `100%` with
  zero errors. Partial/corrupt/failed extraction returns false before DB,
  version or notification state changes. `tools/test_quick_update_delivery.py`
  covers failure, exception, success ordering, extraction results and manifest
  routing.
- `quick_update.txt` and mutable `build.txt` are independent raw-GitHub cache
  objects (`max-age=300`), and query parameters were empirically ignored as
  cache-busters. The automatic path now binds numeric note `N` to immutable
  `wizard/assets/build_versions/N.txt`. Publication is permanently two-phase:
  artifacts/manifests first, remote verification plus >300 seconds, then a
  note-only commit.
- Recovery shipped as Wizard `0.1.33` / quickfix `0.1.479` / AI `0.2.439`:
  phase-1 commit `683c811`, notification `537` commit `81c369b`. This repairs
  devices whose 0.1.32 state had already been poisoned at 536; old clients saw
  the already-settled mutable manifest, and the installed 0.1.33 makes future
  failures retry-safe.
- A follow-up field screenshot exposed exactly three internal boolean settings
  as blank Expert-mode toggles in both channels: `embedded_translate`,
  `embedded_http_extract`, and `af3_first_launch_dialog_done`. The file uses
  Kodi's version-1 settings schema, but those rows used legacy
  `visible="false"` plus Expert level 3. AI `0.2.440` / quickfix `0.1.480`
  changes only `addon.xml`, `changelog.txt` and `settings.xml`: the three ids,
  types, defaults and controls are preserved, while they are now Internal level
  4 with the proper `<visible>false</visible>` child.
- The two embedded flags remain hidden compatibility state, and the AF3 flag
  remains an internal one-shot marker. There was no prior decision to expose
  those raw technical booleans. The later user decision shipped as one explained
  Advanced selector instead (see the 0.2.441 follow-up below).
- The follow-up used the same guarded two-phase flow: artifacts/manifest commit
  `aade7db`, neutral maintenance note `538` commit `7e446f6`. Standalone
  versioned/latest/repo ZIPs are byte-identical; quickfix member order/set is
  unchanged; only the intended three members differ; `pool.py` is byte-identical
  to the authenticated known-good release; all ZIP/XML/regression tests and two
  independent review rounds passed. Public raw note 538 was verified live.
- Final documentation review then caught that Windows CRLF conversion made the
  declared repository checksum differ from the LF bytes served by Pages. Commit
  `86848d1` pins both repository metadata files to LF, makes the publisher hash
  the same LF bytes it writes, and adds
  `tools/test_repo_channel_integrity.py`. After Pages completed, the exact live
  `repo/addons.xml` response MD5 matched the exact live
  `repo/addons.xml.md5` body (`f5dc039d42b7a606dc1d5d904aa89e62`).
- The user-facing embedded-method decision and gender-reference audit shipped as
  AI `0.2.441` / quickfix `0.1.481` / note `539`. Advanced now exposes exactly
  one selector with five explained modes: `auto` (recommended: align, then direct
  extraction), `align_only`, `direct`, `local_only` (zero embedded HTTP/debrid
  reads), and `off`. A one-shot marker preserves the legacy disabled/local-only
  choices; the hidden booleans are mirrored only for downgrade compatibility.
  Every miss remains fail-open to the normal external-subtitle path.
- Provider metadata collection is parallel, but reference downloads and
  alignment are deliberately **strictly serial** under one plan lock: exhaust up
  to 10 candidates in the current language before entering the next language;
  first aligning candidate wins. Exact chain:
  `he, ar, hi, es, ru, pt, pl, uk, fr, it, cs, ro, el, bg, sr, hr, sk, ur, nl`.
  AI `0.2.441` initially used a 15-download global envelope. That value is
  superseded by AI `0.2.442`: the hard-title envelope is now **50 downloads
  total**, still at most 10 per language and still 30 seconds of active
  download/alignment work (Gemini idle time between lazy fallbacks is excluded).
  This can fully examine the five strongest saturated languages
  (he/ar/hi/es/ru), while the active-work deadline prevents a request storm.
- Release `0.2.441` used the guarded two-phase flow: artifacts/manifests commit
  `8f0c1d1`, then neutral note-only commit `1c19eb8` after Pages success, exact
  public hash verification and a post-cache recheck beyond 300 seconds. Raw note
  539 became live at **2026-07-24 21:32:34 Israel**. AI version/latest/repo ZIPs
  are identical (SHA-256
  `6e3b96584ed467b174eaa5ecdff653b4e5b9eab61d0765d6388f924595f33f2f`);
  QF SHA-256 is
  `4934916885cea74efe410e1619d63de63c48728977defb11902b0cafc71d0e1e`.
  Both editions kept member set/order and changed exactly nine intended members;
  `pool.py` is byte-identical to the authenticated 0.2.440/0.1.480 bases.
  Independent review caught a Windows worktree CRLF/package-parity mismatch
  before publication; the final ZIPs were rebuilt from canonical staged Git
  blobs and re-reviewed SHIP. The public stale Worker reference was unchanged.
- The 50-download correction shipped as AI `0.2.442` / quickfix `0.1.482`
  (artifact commit `73be591`) and notification `540` (`afac8ef`). The
  standalone versioned/latest/repository ZIPs are byte-identical (SHA-256
  `3a3f4df7125616be87cb5fad785bbfe03e1e5be338c7ede6a05785b106c1d854`);
  quickfix SHA-256 is
  `7f063e9c5457bdd7973a7679cdbb019d86210cb5945f0bd1994ae3f4fb2c54bf`.
  Direct embedded extraction still becomes the ordinary AI payload and reaches
  the one common `arabic_gender.begin(...)` gate; `mkv_probe.py` and
  `embedded_extract.py` intentionally do not call the oracle themselves.
- Wizard/package repair then produced quickfix `0.1.483` without changing the
  AI add-on or its credential-bearing `pool.py`; notification `541` is the
  separate platform-maintenance phase described in the package release record.
- **Measurement clock now starts from successful note 540 delivery.** Allow at
  least 24 hours for `0.2.442` / `0.1.482` adoption. The preferred low-traffic
  reset remains
  **Monday 2026-07-27 at 03:00 Israel**; reset `/routes` once, then measure one
  complete fresh 24-hour window. Dashboard/rollup cadence is 15 minutes.

### Remaining levers (ranked)
1. **`auth_reject` (~7%) → Cloudflare WAF at the EDGE.** The fork / very-old
   versions POST and get 401/403/426 — but the request ALREADY hit the Worker
   (an invocation). A Cloudflare **Firewall/WAF rule** that blocks those (by the
   known-fork signature / a missing-or-stale `x-pov-*` header / an old version
   field) runs BEFORE the Worker, so it is **NOT counted as an invocation**. This
   is the only way to cut auth waste; it can't be done in worker code. Pair with
   pushing users to the latest version (the newest client also has the quality
   gate, so upgrading fixes their quality waste too — the maintainer's combined
   idea, which is correct).
2. **`dedup_result` → expose `result_hash` in `/lookup`** so the client can skip a
   POST whose Hebrew already exists under a different source hash (the one dedup
   layer the client currently can't predict). Only worth it if measurement shows
   it's material after the quality fix.
3. **Adding Wizdom uploads** (maintainer wanted this): fine ONCE the waste above is
   cut — until then every extra POST risks the cap.

## Open items (as of this handoff)

0. **A home widget showing the last 10 update notes — REQUESTED, NOT BUILT.**
   Asked for more than once, agreed to more than once, and never written down
   until now, which is exactly why it kept being forgotten. Requirements as
   given:

   - A widget on the HOME screen, on **all four skins** (FENtastic, Estuary,
     NOX, Arctic Fuse 3), listing the ten most recent update notes so a user
     can read what changed without waiting for a notification to appear.
   - **If the user deletes the widget it must stay deleted** -- not restored by
     the next quick update, and not by the next launch. `fentastic_widget_patcher`
     already has the pattern for this and the comment explaining why
     (`_WIDGET_SEED_FLAG` / `_WIDGET_SEED_VERSION`): seed once per device, then
     the user owns the widget list. Anything that re-adds a row on every start
     is the bug that pattern exists to prevent.

   The part worth knowing before starting: **there is no archive of past note
   texts.** `wizard/assets/notification_files/quick_update.txt` holds only the
   current note and is overwritten every release, and `build_versions/N.txt`
   carries the manifest for note N but not its text. So the widget needs a
   published archive file (devices read raw.githubusercontent; they cannot
   read git), and the release tooling has to append to it.

   The good news: **git has every version of quick_update.txt**, so the archive
   can be built RETROACTIVELY rather than starting empty from today --
   `git log -p wizard/assets/notification_files/quick_update.txt` is the whole
   history. One-time backfill, then append on each release.

   **TEN, AND NEVER MORE THAN TEN -- IN THE PUBLISHED FILE, NOT JUST ON SCREEN.**
   The obvious build is an archive that grows for ever and a widget that shows
   the first ten of it. That is the wrong one: every device re-fetches this
   file, so an archive nobody trims turns into a payload that grows by a note
   per release, for ever, on every launch, on every device -- to display ten
   rows. The release tooling appends the new note and **drops the oldest in the
   same step**, so the file is a fixed ten entries from the day it is created
   and the fetch never grows. The backfill takes the last ten notes, not all of
   them. The widget then displays what it is given rather than deciding what to
   trim, which also means the cap cannot be lost by a skin that renders the
   list differently.

1. **Trakt/TMDB add crash — RESOLVED (AI 0.2.377 / quickfix 0.1.416).** The
   REAL root cause (from a SECOND field crash log, 2026-07-16) was **our own
   patch**, not POV's setting. `pov_combined_discover_patcher` (edit 3) had
   rewritten POV's `kodi_utils.py container_refresh()` to ALSO fire
   `UpdateLibrary(video,special://skin/foo)` (the widget-reload ping) so AF3
   home widgets would reload after mark-watched/clear-progress. But
   `container_refresh()` is called from ~30 sites **including every Trakt add**
   (`indexers/trakt_api.py`). The ping triggers a RecentlyAdded home update →
   ALL POV home widgets reload at once → many `plugin.video.pov/router.py`
   invocations run concurrently on POV's `reuselanguageinvoker` interpreter →
   CPython dict corruption `SystemError: Objects/dictobject.c:1756` → native
   crash. The log had ZERO "Widget Refresh Performed" lines, proving POV's own
   setting-gated `refresh_widgets()` (entry.py) never ran — the ping was ours.
   `special://skin/foo` fired at 13:56:44.849, SystemError at 13:56:44.988.
   Two more traps this exposed: POV renders settings from an in-memory
   `SettingsManager` cache (Window prop `pov_settings`), so an `xbmcaddon`
   `setSetting` to disk is invisible to POV's live session — a setting-flip
   fix can't work same-session; and `UpdateLibrary(video,special://skin/foo)`
   /`widget_refresh` exists at exactly one POV source line, so a grep for
   `skin/foo` across OUR repo is the way to find every injector. Fix: edit 3
   removed from the discover patcher, and `pov_container_refresh_crash_fix.py`
   reverts the ping to stock `Container.Refresh` on already-patched devices
   (compile-checked, atomic, `.pyc` dropped, then `pov_reload.note_patched()`
   so it applies this session). FENtastic already reloads its widgets on
   `Container.Refresh`, so nothing is lost. The 0.2.376 `pov_widget_crash_guard`
   (forces `trakt.sync_refresh_widgets` off) is kept as harmless
   defense-in-depth for the separate SyncMonitor path.
2. **Anime "navigation" on phone — RESOLVED (not a bug, no code change).** The
   report was: hard to scroll left/right + a long-press bounces to home inside
   anime lists on a phone. Root cause found: it is NOT anime-specific and NOT a
   POV bug — the user confirmed the SAME thing in regular POV lists, while the
   HOME-screen widgets scroll fine. POV lists render in FENtastic's **Poster**
   view (`View_51_Poster`, `<orientation>horizontal</orientation>`), and Kodi on
   Android doesn't swipe HORIZONTALLY inside a full-window list view (only the
   home widget carousels do). Fix is per-device, not code: in POV → Settings →
   **Set Views** (`navigator.set_view_modes`, label #32510) pick a VERTICAL view
   (Wall #500 / InfoWall #54, both `type="panel"`) for Movies/TV Shows — then
   up/down touch works. Anime submenus route through the identical
   `build_tvshow_list`/`build_movie_list` builders as regular lists (byte-
   identical), which is why it was never anime-specific. Do NOT change the
   shipped default view (it would affect TV/remote users too — the user
   explicitly declined that).
3. **iPhone Gemini API-key pairing — Phase 1 SHIPPED (AI 0.2.424 / quickfix
   0.1.463 / notification #522).** The prior theory ("iOS blocks the local
   server") was WRONG for the common case: field reports showed the local POST
   *reached* Kodi and the key was 401-rejected — i.e. the TRANSPORT worked and
   the KEY arrived CORRUPTED. Root cause: iOS/WebKit (every iOS browser is
   WebKit) mangles the pasted key in the text field (smart-punctuation /
   autocorrect / case) in ways `_sanitize_key` can't always reverse; the SAME
   key pairs fine from Mac/Windows/Android. Phase 1 fixes the existing local-HTTP
   page (`gemini_pair.py` `_HTML_FORM`, client-only, zero Cloudflare): `input
   type=password` (suppresses the iOS mangling), a `paste` handler reading the
   RAW `clipboardData` (bypasses field-level mangling), and ON-PHONE validation
   against Google (`x-goog-api-key` header so `AQ.` keys work; classify by HTTP
   status — 400/401/403 = bad key, 429/5xx/network = ambiguous → send anyway and
   let Kodi's `test_key` decide) so a corrupted/bad key is caught on the phone
   with a clear message instead of a confusing Kodi 401. This makes same-device
   iPhone work (incl. cellular, via loopback). Two Sonnet rounds (round 1 caught
   a real 429-as-bad-key misclassification + a TOCTOU field-swap race; round 2
   SHIP after fixes, empirically driving every status/abort/no-fetch path).
   pool.py untouched (key 802ba87a preserved). **Phase 2 (cross-device iPhone —
   Kodi on a separate box + phone on the LAN, blocked by the iOS Local-Network
   prompt) is DESIGNED, BUILT and locally PROVEN but NOT yet shipped:** an
   opt-in "cloud pairing" fallback via a blind, E2E-encrypted rendezvous on the
   community Worker (a fresh 32-byte secret rides in the QR URL FRAGMENT — never
   sent to any server; the phone encrypts the key and POSTs only ciphertext; Kodi
   polls with backoff, decrypts, HMAC-verifies). Kept as an on-demand fallback so
   its polling costs ~0 Worker invocations in normal use. Full design +
   byte-parity-tested crypto/Worker/Pages/client components live in the
   maintainer's scratchpad (`GEMINI_PAIR_CLOUD_PLAN.md`), not committed (backend).
4. **Community-pool request reduction — SHIPPED (AI 0.2.379 / quickfix 0.1.418).**
   Removed two redundant round-trips to the community-pool Worker. (a) On the
   first entry to a title the source-window Hebrew-% seed
   (`he_sub_match._pool_lookup`) and the background availability warm each hit
   `/lookup` for the same media within ~1s; a short (15 s) cross-process memo
   (`he_pool_raw.json`, unique per-writer temp suffix like the `.tmp`/`.stmp`
   avail-cache writers) makes them share ONE request. (b) The pool reuse
   pre-check in `translate.py` did a blind `<hash>_ar` then `<hash>` `/sub` GET
   (the `_ar` one almost always a 404); it now consults the already-cached
   `/lookup` variant list via a new cache-only `pool.lookup_cached()` and fetches
   only a hash that exists, falling back to the old blind probe only when the list
   isn't cached — so it can never ADD a request. Separate-validator reviewed
   (two rounds) + unit-tested; shipped by key-preserving zip surgery (the shipped
   `pool.py` credential is transplanted from the prior zip, never rebuilt from
   source — see the packaging rule above).
5. **AI translation stopping mid-title on a rate limit — RESOLVED (AI 0.2.380 /
   quickfix 0.1.419).** Gemini returns HTTP 429 for BOTH a temporary per-minute
   rate limit (RPM/TPM, clears in ~60s) AND the daily quota (RPD); `gemini.py`
   treated *any* 429 as a terminal "daily quota exceeded" and aborted AI
   translation to Google mid-movie. During a burst of chunk translations a long
   title routinely trips the per-minute limit, so AI would quit partway even with
   the daily quota untouched. Fix: `gemini._classify_429()` inspects the 429 body
   -- a QuotaFailure naming a per-DAY quota stays terminal (`QuotaExceeded`),
   anything else becomes a new `RateLimited(retry_after)`; `translate._call_gemini`
   backs off (Gemini's own `retryDelay`, 3-65s, up to 5 tries) and retries the
   SAME chunk so AI continues to the end. The exhausted-rate-limit fallback shows
   a distinct "temporary overload" toast instead of the misleading "quota
   exhausted, try again after midnight". Separate-validator reviewed (19-case
   classifier harness + focused re-review); shipped by key-preserving zip surgery
   (pool.py untouched this round).
6. **AI request pacing + Wizdom wrong-subtitle fix — SHIPPED (AI 0.2.381 /
   quickfix 0.1.420).** Two fixes: **(a) Gemini RPM pacing** — free Flash Lite is
   15 requests/min, but chunks were dispatched 3-parallel with no rate limiting,
   so a long title constantly tripped the per-minute limit -> retry-toast spam,
   wasted requests, and the job never finishing cleanly (so the finished AI sub
   never uploaded to the community pool). A process-wide `_gemini_rate_gate`
   (ticket-dispenser: reserve a slot under a lock, sleep outside it) now caps
   request starts to `gemini_rpm`=14/min shared across the ThreadPoolExecutor
   workers and concurrent jobs, and the "rate limited" toast fires at most once
   per job. Net: no 429s, no waste, clean completion -> pool upload restored (so
   re-watches/other users reuse the translation for 0 requests). **(b) Wizdom (and
   all sources) returning wrong-title / unsynced / English-labelled-Hebrew subs**
   — the download path reused ONE shared `Downloaded_subs` folder and `extract()`
   returned the first subtitle-shaped file in it, often a leftover from a previous
   unrelated download; the reference engine cleared the folder before each fetch
   but the bridge dropped that step and then pinned the wrong file in the
   `Cached_subs` cache. Fix: `extract()` returns the file the ZIP itself contained
   (namelist), the shared folder is rmtree'd before every download, and
   `Cached_subs` is bumped to `_v2` with a one-time flush of the poisoned old dir.
   Both separate-validator reviewed (pacing incl. a boundedness stress test;
   Wizdom incl. an old-vs-fixed regression repro); shipped by key-preserving zip
   surgery. Known non-blocking follow-ups: SubSync's audio-probe Gemini calls and
   the `g_extract` gzip path aren't yet routed through the new pacer/namelist fix.
7. **AI translation not finalizing on a content-blocked chunk — SHIPPED (AI
   0.2.382 / quickfix 0.1.421).** When Gemini refused a chunk with
   `PROHIBITED_CONTENT`, the translator could fight the block for minutes and
   never finish — so the fully-translated Hebrew was never cached and never
   uploaded to the community pool, and re-selecting the subtitle re-translated
   the whole title from scratch. The block handling is now quality-first and
   guaranteed to terminate: on a block it (a) retries the whole chunk with the
   NEXT human-subtitle language in the gender-reference chain (e.g. Spanish after
   Arabic — a different language often passes while keeping per-line gender
   correct), (b) if that still blocks, bisects to ISOLATE the offending line so
   every other line keeps its gender reference, and (c) at the single blocked
   line falls back to English-only (still translated, just no gender hint) and
   only as an absolute last resort keeps that ONE source line. A per-chunk
   wall-clock budget is now a pure circuit-breaker whose fallback is English-only
   (split so a large remainder is still translated, never dumped to source), so
   the job ALWAYS completes and uploads. The gender-reference fetch is lazy —
   a title that never blocks still downloads exactly one reference. Two
   independent validator rounds (round 1 found and fixed 5 defects around
   finalization and silently-dropped lines; round 2 confirmed the fixes);
   shipped by key-preserving zip surgery (`pool.py` untouched).
8. **Gender reference: try every language on a block + reach deeper — SHIPPED
   (AI 0.2.383 / quickfix 0.1.422).** Two refinements from real usage data. **(a)
   On a content block, try ALL available reference languages, not one.** The
   0.2.382 fallback tried a single alternate language and, if it also blocked,
   dropped straight to English-only; it now walks the whole aligned chain
   (Spanish, French, Russian, Italian, … after Arabic) before giving up the
   gender reference, so far more blocked lines keep correct gender. **(b) Let the
   reference search reach deeper into the chain.** With up to 3 candidates per
   language and an 8-download cap, Hebrew + Arabic candidates alone could exhaust
   the budget before the search ever reached Spanish — so a title whose Hebrew/
   Arabic subs existed but didn't time-sync fell back to *no* reference even when
   a Spanish/French sub would have aligned. The download budget is raised so the
   search gets through the common gender-marking languages; the everyday case
   (first candidate aligns) still downloads exactly one file. A separate validator
   confirmed correctness and flagged one worst-case latency edge (a pathological
   all-explicit chunk trying many languages per line could hog the shared request
   pacer); fixed by checking the per-chunk time budget *inside* the retry loops so
   the worst case stays bounded. Shipped by key-preserving zip surgery.
9. **Rejected-key clarity + full-chain gender reference — SHIPPED (AI 0.2.384 /
   quickfix 0.1.423).** Two refinements from real usage. **(a) A rejected Gemini
   API key is reported immediately and clearly.** An HTTP 401 (invalid / expired /
   revoked key) used to fall through to a generic error that the translator
   *retried* several times before giving up with an unhelpful reason — wasting
   calls against a key that can never recover. A 401/407 is always a terminal
   auth failure, so it now aborts at once as "API key rejected" (in all three
   Gemini entry points), telling the user exactly what to fix (regenerate the key)
   with zero wasted retries. **(b) The gender-reference search now covers the whole
   language chain.** 0.2.383 raised the download budget to reach the common
   gender-marking languages; it still gave up at a fixed cutoff. It now walks the
   entire priority chain (all reference languages, up to a few candidates each),
   so a title whose earlier languages exist but don't time-sync can still find an
   accurate reference further down — the everyday case is unchanged (the search
   stops at the first sub that aligns, usually one download). A separate validator
   confirmed correctness (the 401 routing was proven with a real-code probe) and
   flagged one non-blocking latency note: on the rare title where *no* language
   aligns, the search now downloads more subtitles before falling back to "no
   reference" — a deeper-search follow-up left for later if it proves slow. Shipped
   by key-preserving zip surgery. **Current behavior supersedes this historical
   full-chain worst case:** 0.2.441 uses the explicit 10-per-language, 15-total,
   30-active-second envelope documented above.
10. **Batched, piggybacked usage telemetry — SHIPPED (AI 0.2.385 / quickfix
   0.1.424).** The add-on's anonymous usage events used to be sent as one network
   request per AI translation. They're now collected into a small **durable queue**
   (persisted to the add-on's data dir, so a short-lived subtitle process never
   loses one) and delivered **without a dedicated request** in the common case:
   they ride along on the community-pool contribution the add-on already sends
   after a shared translation, and anything not carried that way is flushed in a
   single batched request per handful of events. This collapses the per-translation
   request into (usually) zero extra requests — a large cut in redundant traffic to
   the community server, fully transparent to the user (translation and download
   behave exactly as before). Delivery is confirmed by HTTP status so an
   out-of-date or briefly-unreachable install re-queues rather than silently
   dropping events, and each event keeps its own timestamp so the maintainer's
   stats stay time-accurate despite the batching delay. Client-side only; a
   separate validator reviewed it in two rounds (it caught a real event-loss bug on
   auth/version rejections, which was fixed and re-verified before shipping).
   Shipped by key-preserving zip surgery (`pool.py` + `telemetry.py`, credential
   block spliced through byte-identical).
11. **Rebrand, distinguishable menu tiles, and a paid-tier fast mode — SHIPPED
   (AI 0.2.386 / quickfix 0.1.425 / wizard 0.1.31).** Three refinements. **(a)
   Branding.** The update-notification frame now reads "KODI POV IL" (it still said
   "KODI + REAL DEBRID ISRAEL") and its badge is the POV IL icon; the notification
   also leads with a visible update number ("עדכון #N") so users can tell which
   update they're on. Ships through the wizard's own update channel (build.txt →
   the 0.1.31 wizard zip), not the quickfix. **(b) Menu tiles.** The "quick update"
   and "install wizard" home tiles were byte-identical images, so when the skin's
   text label briefly vanishes they were indistinguishable; each now bakes its
   Hebrew label into the image (below the intact POV square). One pair of images
   covers every skin (FEN / Estuary / NOX / Arctic Fuse 3) because the service
   force-syncs them to the live media dir on boot; Arctic Fuse 3's "switch skin"
   tile — which reused the same image — got its own so it isn't mislabelled.
   **(c) Paid-tier fast mode.** A new **`ai_paid_mode`** toggle (Settings →
   Translation, under *Model*; **default OFF**) for users on a *paid* Gemini plan:
   the add-on normally paces requests and limits parallel chunks to stay under the
   free tier's ~15 req/min cap, which only slows a paid key down — turning this on
   removes the pacing and raises parallel chunks (8, up to 16) for much faster
   translation. Leave it OFF on a free key (it would just cause rate-limit retries).
   It does **not** change translation quality — that's the *Model* setting. A
   separate validator reviewed the batch and caught a real bug (paid mode was
   reading the free-tier parallelism default), fixed and re-verified before release.
   Built by key-preserving zip surgery.
12. **Model-aware AI rate limits + a fix for the rebrand not sticking — SHIPPED
   (AI 0.2.387 / quickfix 0.1.426 / wizard 0.1.32).** Two things. **(a) Rate limits
   per model.** The free-tier throttle and the daily-usage counter were both tuned
   only for Flash-Lite (~15 req/min, 500/day). Regular Flash's free tier is far
   tighter (5 req/min, ~20/day), so choosing it caused per-minute rate-limit errors
   and no daily warning. The pacing and the counter are now derived from the selected
   model — Flash-Lite unchanged; regular Flash paced to ~4/min and counted against
   20/day. Paid "fast mode" still lifts the throttle for every model. (A separate
   validator caught that the new per-model counter setting wasn't declared, so it
   would have silently failed to persist — fixed and re-verified before release.)
   **(b) Rebrand propagation.** Item 11's branding was correct in the wizard's own
   update channel but a **quick update** re-extracts the build over the home dir, and
   the copy of the wizard bundled in the quickfix was an old snapshot — so every quick
   update re-imposed the old notification frame and icon on top of the new branding.
   The quickfix now carries the current wizard rebuilt from source (correct frame,
   icon, and skin wiring), and the home tiles drop their stale texture-cache entry so
   the new art shows on the next render instead of after a manual navigation. Built by
   key-preserving zip surgery.
13. **Home tiles finally refresh + more subtitles get gender-accurate AI — SHIPPED
   (AI 0.2.388 / quickfix 0.1.427; wizard unchanged).** Two things. **(a) Tile
   texture cache.** After item 11/12, the "quick update" and "install wizard" home
   tiles were correct ON DISK but Kodi kept drawing the OLD cached bitmap (it caches
   skin textures by path and keeps them resident, so overwriting a PNG in place
   doesn't refresh the screen), and the previous cache-drop couldn't re-trigger once
   the bytes already matched. A one-time, generation-marked cache drop now clears the
   stale tile textures and does a single focus-preserving skin reload on boot, so the
   correct distinct logos actually show. (The marker is persisted-and-verified first,
   so a device that can't save it degrades to a harmless log line, never a reload
   loop; the reload runs off-thread so it can't delay startup.) **(b) Looser
   gender-reference gate.** For gender-accurate translation the add-on aligns a
   reference subtitle (any language) to the source and hands each line its gender
   hint. It was discarding any reference that didn't cover ≥80% of the lines — but
   real usage data showed ~65% of those rejections were correctly-aligned references
   that merely had partial coverage (65-79%). The coverage floor is now 65%: a
   reference that lines up but covers two-thirds of the dialogue is kept and hints
   most lines instead of being thrown away (the alignment-confidence and framerate
   checks are unchanged, so a wrong match is still rejected). Built by key-preserving
   zip surgery; the standalone edition got only the translation change.
14. **Embedded-subtitle → AI translation: perfectly-synced Hebrew — BUILT &
   VALIDATED (AI 0.2.389 / quickfix 0.1.428; wizard unchanged), Phase 1 (staged
   on the feature branch, pending merge to main).** The add-on can now translate
   the video's OWN embedded subtitle track — the English/Spanish/etc. already
   inside the MKV — instead of only external subs. Because an embedded track's
   cue timings ARE the video's timeline, the Hebrew it produces is perfectly
   synced from the first second: no external search, no re-timing guesswork. A
   new self-contained MKV/WebM text extractor reads the embedded track straight
   from the playing file — local or debrid HTTP, using the Cues index + surgical
   Range requests (tens of MB, never the whole file), or a full sequential walk
   for local files — decodes SRT/ASS text, and feeds it to the existing AI
   pipeline. It appears both automatically (when no ready Hebrew exists) and as a
   pick in the subtitle chooser ("תרגום מובנה → עברית"), ranked right after
   Hebrew and above every external sub; English is preferred as the source (best
   translation quality) while gender accuracy still comes from the reference
   chain. Fully fail-open: only text codecs are extracted — bitmap PGS/VOBSUB and
   any failure fall through to the existing external path, so nothing that worked
   before changes. The standalone edition also gained the full sync stack
   (container probe + re-timer), so it re-times subtitles and extracts embedded
   text too. Two separate validation passes found and fixed five correctness bugs
   — including a chunk-boundary and an unknown-size-cluster data-loss bug — each
   verified against purpose-built synthetic MKVs before the release was cut.
   Bitmap-embedded sync (via the embedded track's timestamps), an OCR path, and
   an ffmpeg fast path are planned follow-ups. **Hotfix (AI 0.2.390 / quickfix
   0.1.429):** the first field test showed that extracting over a live debrid
   stream competes with the player on the same CDN token and can trip a rate
   limit that stalls playback — so extraction over HTTP was turned OFF by
   default in the hotfix (it defers to the external path, which still yields AI
   Hebrew); local-file extraction is unaffected. **Streaming re-enabled (AI
   0.2.391 / quickfix 0.1.430):** the HTTP path was rebuilt to be gentle — ONE
   keep-alive connection (pool size 1), coalesced serial byte-ranges instead of
   a fresh fetch per cue, a total-bytes cap and a deadline, and a 429/5xx
   circuit-breaker that stops the moment the CDN pushes back and defers to the
   external path. It can no longer starve the player. A hidden kill-switch
   (`embedded_http_extract`, default on) is the instant manual escape hatch;
   the extractor's truncation-recovery was also hardened after validation found
   a co-located block could silently drop a later cue. Local extraction is
   unchanged. **Made it actually work + backgrounded manual picks (AI 0.2.392 /
   quickfix 0.1.431):** a field test showed extraction still failing two ways.
   (a) A partial-read bug — a single raw socket read returned only a few KB, not
   the requested range, so a "successful" pass parsed 2 cues out of 1568; fixed
   with a fill-loop that reads until the full length or EOF. (b) A too-small
   window and tight caps deferred scattered remuxes; now the Cues index's
   CueRelativePosition (present in most files) is used to fetch just the subtitle
   block — about 18× less data — so a spread file stays gentle on the player,
   with the proven window-scan as the fallback. A validation pass also caught a
   data-loss case where two subtitle lines sharing one cluster collapsed to one;
   fixed by keeping every distinct relpos. Finally, a **manual** pick (chooser or
   native picker) now runs the whole extract-then-translate job in the background
   like a normal AI pick — the dialog closes immediately, a non-modal corner
   progress bar shows extraction %, and the Hebrew swaps in progressively when
   ready, with a toast if it can't be produced. Every change was reviewed by a
   separate validator and exercised against synthetic MKVs before release.
   **Rate-limit resilience + source preview (AI 0.2.393 / quickfix 0.1.432):**
   the next field test showed the relpos path working (all cues targeted) but the
   debrid CDN rate-limiting the token (HTTP 429) partway, which the one-strike
   breaker turned into a give-up. It now backs off (honors Retry-After, with a
   validated non-negative/finite guard so a malformed header can't disable the
   breaker) and retries before tripping, plus a small per-request pace to stay
   under the limiter — so extraction rides out a transient 429 and completes. And
   picking "embedded → Hebrew" now shows the embedded SOURCE track natively and
   instantly (it's already synced to the video) while the Hebrew cooks, instead
   of leaving the stale sub the user picked embedded to replace; the background
   job swaps to Hebrew when ready. The validator caught, and this release closes,
   a malformed-Retry-After breaker-defeat bug and a mis-sourced stream index.
   **Yield to the player (AI 0.2.394 / quickfix 0.1.433):** on a strict provider
   (TorBox) a field test closed the MOVIE — two concurrent extractions' range
   requests on the shared token pushed the CDN over its per-token limit, which
   429'd the player's own video stream to eof. The extractor is now a good
   citizen: a monotonic-TTL cross-process flag runs ONE extraction at a time; a
   player-stall guard aborts the moment the player buffers (its clock stalls >8s
   while playing) to hand the token back; and request pacing is adaptive (starts
   0.2s, widens ×1.5 on every 429 up to 2s — AIMD back-pressure toward a rate the
   provider tolerates) with the pace/backoff sleeps made abort-aware (~1s
   granularity) so the stall-abort can actually fire in time. Validation across
   this pass fixed a negative-clock-skew inversion in the TTL guard (was
   re-admitting a second concurrent run). Honest limit: on a very strict token a
   single extraction may still fall back to the external Hebrew rather than
   always completing — but it no longer closes the movie. Request-count halving
   (1 range read per cue) is the plan-B lever if a strict-token case recurs.
   **Read-size cut (AI 0.2.395 / quickfix 0.1.434):** the next field test (TorBox)
   confirmed the movie now survives (stall-guard fired at 71s) but the player
   stalled from pure BANDWIDTH contention — no 429, so pacing never engaged. The
   relpos fast path was fetching 16KB header + 128KB block (~144KB) per cue for a
   subtitle that's <1KB, so the reads were cut to 8KB + 32KB (~40KB/cue, ~3.6×
   less throughput); 32KB still covers a text block + BlockGroup (validated at the
   boundary — a rarer larger element just falls to the window-scan for that cue).
   Whether this is enough is a provider-headroom question; if a strict token still
   stalls, the real fix is a "spare-bandwidth" mode (extract only from the
   player's leftover capacity, pausing when its buffer dips) — awaiting the
   maintainer's call on that vs an extract-during-pause approach.

   **Track-selection fix (AI 0.2.396 / quickfix 0.1.435):** field log c23c5040
   (TorBox, a Rick&Morty upscale) failed in ~6ms at track selection — NOT
   bandwidth — with `no matching text track (num=None lang=en)`. `_sub_tracks`
   was non-empty, so a subtitle track existed, but `_pick_track` matched none.
   Root cause: the release omits the Language element on its English text sub
   track, and our parser left `lang=''` so `''.startswith('en')` failed. Per the
   Matroska spec a TrackEntry with NO Language element IS English (`eng`; `en`
   for LanguageBCP47) — which is exactly why Kodi surfaced it as `eng`; we were
   stricter than the spec. Fixes in `embedded_extract.py` (Sonnet-validated,
   two adversarial rounds): (a) `_parse_track_entry` now parses `FlagForced`
   (0x55AA) — it was declared and used in the sort but never actually read, so
   `forced` was always False — and defaults an absent Language to `eng`, tagging
   `lang_explicit` so a genuinely-tagged track outranks a defaulted one; (b)
   `_pick_track`'s lang branch prefers explicit-tag matches, excludes forced/
   signs-only tracks from auto-pick (a sparse signs sub is a worse deliverable
   than deferring to the external search), and falls back to the sole non-forced
   text track when nothing matches the language (handles an explicit `und` tag).
   This is orthogonal to the bandwidth question above: it makes extraction
   *start* on files that previously failed instantly; a strict provider may
   still stall mid-extract on bandwidth, which is still the open item.

   **Debrid safety layer (AI 0.2.397 / quickfix 0.1.436):** the track fix let
   extraction START on TorBox (log 78e1c97c: 1688 cues), but it then crawled
   ~2min delivering nothing while TorBox 429'd every request, holding the token
   hot; the moment the user unpaused, the PLAYER's own read 429'd and the movie
   closed. Two Sonnet-validated safety fixes: (a) `embedded_extract.py` fail-fast
   -- `_HTTP_429_STREAK_MAX=6` consecutive 429-needing fetches trip the breaker
   (~20s) instead of a 2-min hot-token crawl; a clean fetch resets the streak so
   Real-Debrid never trips (known gap: a perfectly alternating 429/clean pattern
   never trips -- a ratio counter is the future hardening). (b) `translate.py`
   `_should_abort` aborts the instant playback RESUMES after a pause (`saw_pause`
   latch), handing the token back before the player starves -- the 8s stall guard
   was too slow (player died ~1s after resume). These make the failure fast+clean
   and stop the movie-close; they do NOT make extraction SUCCEED on TorBox.
   **Root cause is now definitive: TorBox rate-limits the token by REQUEST COUNT,
   hard -- ~1700 sequential range requests is hopeless there, paused or playing.
   Real-Debrid (the friend's setup) has no such limit, which is why it works for
   him on both Android and PC.** Maintainer's chosen direction: make it fast AND
   fill in progressively (like the live AI translation).

   **The alignment pivot (AI 0.2.398 / quickfix 0.1.437) -- the feature that
   actually works on TorBox.** Key realisation: the embedded subtitle's TEXT is
   scattered across ~1700 clusters (inherently ~1700 requests -> hopeless on
   TorBox), but its dense cue TIMESTAMPS live in ONE contiguous Cues index (a
   handful of requests). And sync is a timing problem, not a text problem. So
   "embedded translation" no longer extracts the embedded text; it reads only the
   embedded track's dense cue-time skeleton and RE-TIMES an external source sub
   onto that ground-truth timeline, then AI-translates the re-timed source (the
   pipeline preserves timing 1:1) -> synced Hebrew that fills in progressively.
   This directly solves the maintainer's original pain (external subs are often
   unsynced) by re-syncing them to the embedded timing, cheaply. Pieces:
   - `embedded_extract.cue_reference_times()` -- dense cue START times from the
     Cues index ONLY (parses CueTime 0xB3 per CuePoint for the wanted sub track,
     rebased via `_timeline_origin`; no cluster block fetches). Verified: **3
     requests / 163KB** for a ~1700-cue file (vs ~1700 for full extract).
   - `translate._embedded_aligned_source_srt()` -- adapts the flat times to
     `[{start,end}]`, fetches the best release-matched external source via
     `subsync._oracle_candidates`/`_download_oracle`, aligns with the EXISTING
     `sync_align.verify_cues`/`retime`, tries up to 3 candidates, writes a
     re-timed SRT. Fail-open: any miss (no dense Cues index / no external source
     / low-confidence alignment) returns None. Pause-aware abort + a 45s total
     wall-clock ceiling (the flaky-token guard). The embedded_ai branch tries
     this FIRST, then falls back to the full-text `extract_srt`, then to the
     external-subtitle path.
   - `default._extract_progress()` gains a label so the bar narrates
     read->find->sync; then the AI pipeline's progressive chunk swaps take over.
   Why dense beats sparse: the old SubSync file-probe sampled ~33 sparse cues and
   found a SPURIOUS +17s peak (log c23c5040, tight 73% < 93% needed); with
   hundreds/thousands of real cue times the estimate lands on the true offset and
   `_required_tight` no longer applies the sparse penalty. Global-linear only
   (offset+fps) -- a genuinely different CUT is (correctly) rejected as UNKNOWN
   and defers. Three Sonnet rounds, all CONFIRMED-SAFE. Full text extract remains
   the perfect path on lenient providers (Real-Debrid).

   **Cross-language fallback (AI 0.2.399 / quickfix 0.1.438):**
   `_embedded_aligned_source_srt` now returns `(path, used_lang)` and, when the
   PICKED language has no external sub, aligns an external sub in another
   language onto THAT language's embedded cue skeleton (try-order: picked, then
   English, then any language with an external candidate; capped at 3 total
   head+Cues reads; stops at first success). The embedded_ai branch adopts
   `used_lang` as the AI source language so the cache key / prompt / pool tag
   reflect the language actually translated. Field-verified (log 1bd4c4e7:
   Obsession 2160p, 1688 dense cue times in 4 requests / 3.6MB, external English
   CONFIRMED already-synced at offset -27ms, handed to the full gender-aware AI
   pipeline). CONFIRMED-SAFE. Open follow-up: read head+Cues ONCE and slice
   per-track times instead of re-reading per language on the fallback (~3x
   redundant on the fallback path only; the common path is 1 read).

   **Embedded pool labeling + same-source gate (AI 0.2.400 / quickfix 0.1.439 +
   a worker.js change delivered OUT-OF-BAND, NOT committed):** embedded-sourced
   translations now store in the pool under a new `kind='ai_emb'` (the
   embedded_ai payload carries `'embedded': True`; `_pool_kind` becomes
   `'ai_emb'`; both feed only `contribute_once`, not telemetry).
   `list_candidates` surfaces an `ai_emb` variant as "תרגום מובנה AI · מאגר
   קהילתי", sorted FIRST among AI pool items -- but ONLY for the SAME source
   (exact release, `release_match.TIER_EXACT` via new `_is_same_source`); for any
   other release the `ai_emb` variant is HIDDEN entirely (a viewer on a different
   release makes their own). The embedded row drops the match-% (it is, by
   definition, the viewer's exact release). worker.js: preserves the `ai_emb`
   kind (previously collapsed every non-ktuvit to `ai`) and, on a dedup match,
   PROMOTES an existing `ai` variant to `ai_emb` (never downgrades) so history is
   relabeled organically as embedded translations flow in (no bulk relabel is
   possible -- origin was never recorded). pool.py UNCHANGED. Two Sonnet rounds,
   CONFIRMED-SAFE. **worker.js must be deployed to Cloudflare separately (it is
   the local-only pool server; never commit it).**

   **li_filename release parity (AI 0.2.401 / quickfix 0.1.440):** the
   lookup-side `_video_ref` (used by the embedded same-source gate + the pool
   match-%) now derives the release the same way the CONTRIBUTION side does --
   new `_release_from_path()` tries `basename(li_filename)` before
   `basename(filepath)`, ext-stripped, and rejects a debrid URL/token/UUID via
   `pool._is_token_like` (falling through to `filepath`). Without it, a debrid
   replay (tokenized `filepath`, blank picked_release/tagline/label) derived a
   token as the release and wrongly HID the viewer's own embedded pool item.
   Sonnet CONFIRMED-SAFE. **Known follow-up (pool.py-scoped, NOT done):** both
   `_release_from_path` and `pool._release_from` use a blind `rsplit('.',1)`
   extension strip; for a basename with NO real container extension (e.g.
   `Show.S01E01`) this collapses the last dotted token (`-> Show`), which for two
   different releases of the SAME episode bucket can produce a spurious
   TIER_EXACT match (a false-positive "same source"). Narrow (real files carry an
   extension; never seen in field logs) and same-episode timing is usually
   identical anyway, but the proper fix is to swap both sides' blind strip for a
   whitelist-anchored one (reuse `release_match._strip_ext` / `normalize`).
   The maintainer runs the community pool worker OUT-OF-BAND: the repo's
   `pool/worker.js` is a STALE 1.2k-line frozen reference; the LIVE worker is
   ~2k lines. ALWAYS request the current live worker.js before editing it, and
   deliver changes as a file for Cloudflare deploy -- never commit worker.js.

   **Embedded track language matching -- CRITICAL fix (AI 0.2.402 / quickfix
   0.1.441; notification #501):** clicking "תרגום מובנה" in ANY language whose
   2-letter ISO 639-1 code is not a prefix of its 3-letter ISO 639-2/B code was
   silently broken. The picker passes a 2-letter code (`es`, `de`, `nl`, `ja`,
   `sv`, `el`, `zh`, ...) but a Matroska TrackEntry's Language element carries the
   3-letter code (`spa`, `ger`, `dut`, `jpn`, `swe`, `gre`, `chi`, ...), and
   `_pick_track` matched with `track_lang.startswith(lang[:2])` -- so
   `'spa'.startswith('es')` was False and ~20 languages NEVER matched their
   embedded track. The request fell through the cross-language fallback to
   English, whose translation was already cached, so the user saw "מ-cache
   (תרגום קודם)" for a language they never translated (field log 7af3569d:
   Obsession 2026, `es` AND `de` both `no matching track` -> re-read English's
   1688 cue times -> English cache). Fix (embedded_extract.py only): a canonical
   ISO 639-1/2B/2T table (`_ISO639_ROWS`/`_ISO639_CANON`) + `_lang_key()`;
   `_pick_track` now matches on canonical keys, with a prefix fallback kept ONLY
   for codes not in the table (so it also stops the OLD latent false-matches --
   `es`->Estonian `est`, `ar`->Armenian `arm`). The single-text-track fallback is
   tightened to not hand back a lone EXPLICIT different-known-language track
   (would mislabel the source) while still using `und`/unrecognised or
   defaulted-`eng` (lang_explicit=False) tags. Norwegian Bokmal/Nynorsk are folded
   into one `no` bucket (the add-on only ever requests generic `no`; keeping them
   split would have dropped `nob`/`nno` tags the old prefix code matched). Fully
   fail-open (any miss still defers to the external path); translate.py/pool.py
   UNCHANGED (inherited byte-identical; pool key 802ba87a preserved); standalone
   repo bumped (repo/addons.xml + md5 + repo/zips + dist/-latest.zip). 80-case
   test (`test_lang_match.py`), Sonnet CONFIRMED-SAFE (its two non-blocking
   findings -- the Norwegian fold and a dead `_lang_match` disjunct -- were both
   applied). Notification #501 carries the fix note + the DeDuplicate credit,
   emoji-free (the trophy glyph rendered as an empty box on the user's skin).
   **Two user-reported items still OPEN (NOT this fix):** (a) the pooled "תרגום
   מובנה AI · מאגר" item didn't appear because the client's pool UPLOAD queue was
   stuck (field log: `pool drain: failed=1 remaining=28`, uploaded=0) -- the
   ai_emb item never reached the pool; likely env/worker-side, needs the live
   worker checked. (b) only ONE embedded item per language shows even when a file
   has multiple same-language tracks (`list_candidates` de-dups by language code)
   -- that is task #31 (per-track items), which needs the real MKV TrackNumber
   plumbed to `resolve()` so it can target a specific same-language track.

   **Embedded pool item: 100% + relabel-on-re-click (AI 0.2.403 / quickfix
   0.1.442; notification #502):** two client-side (translate.py only) follow-ups
   to the user seeing an embedded pool row with a BLANK % beside a regular "·
   100%" sibling for the same release, and a re-click NOT relabeling the pooled
   entry to embedded. (a) `list_candidates` now shows "100%" on the `ai_emb` row
   -- it is gated to the EXACT source (`_emb_ok` -> TIER_EXACT), so 100% is exact,
   not cosmetic (`release_match` returns TIER_EXACT iff pct==100). (b) An embedded
   translation that hit the translation CACHE was contributed as plain `ai` and
   its one-shot `.shared` marker then blocked any upgrade, so the pool row never
   got the embedded label. Fix: a `_pool_marker(path, kind)` helper returns
   `<path>.emb` for `ai_emb` (else the plain path); ALL THREE ai-contribute sites
   (fresh upload, early-cache backfill, content-hash backfill) route through it,
   so an embedded contribution tracks its OWN `.emb.shared` marker and can UPGRADE
   a file already shared as plain `ai`/`ai_ar` (the Worker promotes a dedup-matched
   entry to `ai_emb`, never downgrades) instead of being swallowed. Non-embedded
   paths are byte-identical (`_pool_marker(p,'ai') == p`); the ktuvit
   mirror/harvest markers are on the downloaded-sub files, not these cache paths,
   so they're unaffected. **Two Sonnet rounds:** round 1 caught that only the
   early-cache site had been patched -- the content-hash backfill (a real sibling
   path this codebase's two-tier cache designs around) still swallowed the upgrade
   (BLOCKER), plus a guaranteed redundant re-share round-trip because the
   fresh-upload seeded only the plain marker; the single `_pool_marker` helper
   applied at all three sites closes both. CONFIRMED-SAFE otherwise (% never a lie;
   marker one-shot holds; kind precedence = `_pool_kind`; fail-open preserved).
   **Correction to the prior handoff note:** the "pool drain stuck (28 items)"
   theory for the missing label was WRONG -- embedded items DO reach the pool via
   the direct `contribute_once` POST (the drain queue is a separate, unrelated
   backlog); the real cause was the backfill kind, fixed here.

   **Relabel actually reaches the Worker + exhaustive synced-source search (AI
   0.2.404 / quickfix 0.1.443; notification #503):** the 0.2.403 relabel still
   didn't land -- `pool._post` has a dedup PRE-CHECK (`if _pool_has_hash(...):
   mark + return`) that skips the upload when the source is already pooled, so
   the `ai_emb` "promote" signal never reached the Worker. Fix (pool.py): the
   pre-check now bypasses for `kind == 'ai_emb'` (both `_post` AND its durable-
   queue twin `_post_sync`, kept consistent so a future author routing embedded
   through the queue can't re-break it); one-shot per file still holds via the
   `.emb` marker, and the Worker dedups by hash so it PROMOTES rather than
   duplicating. **pool.py is the SENSITIVE file: the repo copy carries a
   PLACEHOLDER key (md5 5a7e487ddf83), the REAL key (802ba87a) lives only in the
   release zips -- so the surgery NEVER swaps the repo pool.py; it SPLICES the
   repo's edited CODE with the base zip's real key block and asserts (a) key md5
   still 802ba87a, (b) the fix present in both sites, (c) a round-trip undo of the
   key swap reproduces the repo file byte-for-byte, (d) it compiles.** translate.py
   also: (1) a clear cross-language fallback notification (`_lang_display_he`:
   "אין כתובית מסונכרנת ב<שפה> — מתרגם מ<שפה>") replacing a confusing "from cache"
   when the picked language has no external sub that time-syncs (its only subs are
   CAM/other-release, structurally mistimed -- the sync gate correctly rejects
   them; alignment fixes a linear offset, not structural cut differences); (2)
   EXHAUSTIVE candidate search -- tries EVERY external sub per language (was
   capped at 3) until one syncs, NO download-count cap (user opted to search
   exhaustively over protecting the provider quota), bounded by the 45s deadline +
   abort + <=3-language read cap; stops immediately on the first sync (return),
   so downloads = candidates-until-first-success, and each embedded-track click is
   an INDEPENDENT attempt (the 3-language cap is the per-click FALLBACK chain, not
   a global limit -- clicking N embedded tracks translates all N). (3) To stop the
   exhaustive picked-language search from eating the whole 45s and starving the
   reliable English fallback, a non-exempt language YIELDS (break to next) once it
   has used `_ALIGN_DEADLINE_S - _ALIGN_FALLBACK_RESERVE_S` (30s); `_yield_exempt =
   {'en', try_langs[:3][-1]}` exempts English EXPLICITLY (always gets its turn --
   NOT merely the positionally-last language) plus the last actually-processed
   language. **Four Sonnet rounds** (round 1: pool `_post` + message CONFIRMED;
   round 2 caught that only the early-cache site was patched -- no, that was
   0.2.403; here round 2 caught the exhaustive search could starve English -> added
   reserve; round 3 caught the reserve's `try_langs[-1]` sentinel protected the
   wrong language for 3+ langs -> exempt English explicitly; final CONFIRMED-SAFE).

   **Relabel migration: `.emb` -> `.emb2` marker (AI 0.2.405 / quickfix 0.1.444;
   notification #504):** field log showed the user still on 0.2.403, whose `_post`
   had NO ai_emb bypass -- its dedup pre-check WROTE `<path>.emb.shared` (via
   `mark_contributed`) and returned WITHOUT posting the promote. So every title a
   0.2.403 user clicked got the one-shot marker set but the Worker never got the
   signal, and after updating, `_backfill_pool_async`'s `was_contributed('.emb')`
   would skip the relabel forever. Fix: `_pool_marker`'s ai_emb suffix bumped
   `.emb` -> `.emb2`, so stale `.emb.shared` markers are ignored and the promote
   fires exactly once now (a genuine 0.2.404 promoter gets ONE redundant re-POST
   the Worker dedups; harmless). translate.py-only SWAP -- pool.py INHERITED
   byte-identical from the 0.2.404 base zip (real key 802ba87a + the
   `_post`/`_post_sync` bypass), asserted `out_pool == base_pool`. Sonnet
   CONFIRMED-SAFE. NOTE for a future bump (`.emb2` -> `.emb3`): update ALL the
   marker prose too (three spots: `_pool_marker` docstring, `_backfill_pool_async`
   docstring, and its `_work()` inline comment) -- the 0.2.405 review flagged one
   stale sentence, now fixed, but the pattern recurs on every suffix bump.

   **Embedded pool items ordered by source-language gender accuracy (AI 0.2.406 /
   quickfix 0.1.445; notification #505):** with several embedded translations of
   the SAME release (from different source languages) in the pool, they now order
   by the source language's gender-marking strength, and each label names the
   source it was translated from ("תרגום מובנה AI (ספרדית) ..."). Rationale: Hebrew
   renders speaker gender; the gender-reference chain covers most lines, but on the
   gap lines the AI falls back to the SOURCE text's own gender -- so a source that
   marks predicative gender (Semitic/Romance/Slavic/Indo-Aryan) beats English/German
   (which don't). `_gender_src_rank` -> 0 (strong) / 1 (weak, en/de/nl/...);
   `_ai_sort_key` sorts ai_emb by it, then a normalised (`or 'en'`, region-strip,
   2-letter) source-lang tie-break that matches the rank + label. Client-only: the
   pool already returns `source_lang` per variant (worker.js stores at :678,
   returns in /lookup at :1096) -- NO pool/worker change. Regular AI items keep
   ordering by match-% (g held constant). pool.py INHERITED byte-identical from the
   0.2.405 base. Sonnet CONFIRMED-SAFE (tuple-type safety proven; two cosmetic
   tie-break-normalisation NITs applied). NOTE: "English last" is not literal --
   within the weak tier it's alphabetical (e.g. Dutch `nl` sorts after `en`); the
   design goal (gender-accurate sources FIRST) is what holds.

   **Embedded translations on the owner dashboard (AI 0.2.407 / quickfix 0.1.446;
   NO notification -- telemetry-only, no user-visible change; + a worker.js change
   delivered OUT-OF-BAND):** embedded (`ai_emb`) translations uploaded to the pool
   + Telegram fine but were invisible on the Worker's `/stats` dashboard, because
   the dashboard is 100% telemetry-driven and (a) the telemetry `method` only ever
   carried `ai_ar`/`ai_fallback`/`ai_plain` -- never an "embedded" marker -- and
   (b) the add-on's cache-hit / pool-reuse paths emit no telemetry at all. (The
   dashboard's pre-existing "embedded-Hebrew track lists" card is the unrelated
   `emb:` registry of releases that SHIP a built-in Hebrew track, not ai_emb
   translations.) Two coordinated mechanisms:
   - **Telemetry-integrated (client + worker):** `translate.py` tags each AI
     translation's telemetry event with `emb` (`1 if _pool_kind == 'ai_emb'`).
     Embedded runs the SAME AI+gender pipeline, so it was always counted in the
     method/recent/title stats -- this just MARKS it. worker.js: `emb INTEGER`
     column on `tr_events` (schema ALTER + evStmt, 26/26/26); rollup folds it
     (`ROLL_SCHEMA` 4->5 forces a bounded rebuild; `emb:{n,oks,m}` accumulator +
     per-title `emb` (ok-gated) + `recTail` flag); renders a "מובנה" badge in
     Recent activity, an `emb` column in Top titles, and a "Gender coverage ·
     embedded only" subsection. Current-builds-forward (past rows were never
     tagged; can't backfill telemetry).
   - **Pool-derived (worker only, backfills history):** an `emb_stats` KV blob
     maintained in `contributeCore` on fresh-store + ai->ai_emb promote (deduped
     by Telegram `file_id`; guarded so a `ktuvit` variant is never counted;
     best-effort read-modify-write, same race class as the `up:` counters);
     `GET /backfill-emb?key=<STATS_TOKEN>[&reset=1]` seeds it EXACTLY from the
     existing `v1:` pool keys (paginate via `after` cursor to `done`). Feeds a
     dedicated "Embedded translations" section (total / by-source-language /
     movies-vs-episodes / top titles / recent). Backfilled history is
     release-labeled (the pool variant never stored a title) -- counts exact,
     labels coarser.
   pool.py UNCHANGED -> INHERITED byte-identical from the 0.2.406 base (real key
   802ba87a + the ai_emb bypass; asserted). THREE Sonnet rounds: round 1 caught a
   ts ms-vs-seconds render bug (pool `variant.ts` is `Date.now()` ms, dashboard
   renders seconds -> year-58000 timestamps) + blob-size caps; round 2 (full set)
   caught a **stored-XSS BLOCKER** -- attacker-controlled `season`/`episode` from a
   `/contribute` body reached the owner's `/stats` HTML unescaped via `ep()`
   (STATS_TOKEN exfiltration); fixed by digit-restricting them at the fold sink
   AND `esc()`-ing them in `ep()`. Round 3 CONFIRMED-SAFE (no second sink). Tests:
   41 helper assertions + a 15-assertion render smoke test (mock D1/KV through the
   real updateRoll+renderStats). **worker.js redeploys to Cloudflare separately;
   after deploy, hit `/backfill-emb?key=...&reset=1` once (follow `after` to
   `done`) to seed history, then `/stats?key=...` shows it (backfill clears the
   HTML cache on completion).** Open (pre-existing, out of scope): `/web-upload`'s
   client-side TMDB-search dropdown builds `innerHTML` from TMDB-API titles
   (different threat model; not attacker `/contribute` data; doesn't touch
   STATS_TOKEN).

   **Read-once embedded align + SDH-aware AI translation (AI 0.2.408 / quickfix
   0.1.447; notification #507):** two changes in translate.py + embedded_extract.py
   (pool.py INHERITED byte-identical; the worker is untouched -- no redeploy).
   - **#37 read-once:** the cross-language embedded align used to call
     `cue_reference_times(url, lang=X)` once PER language on the fallback, each
     re-reading the head+Cues. `_read_cue_times` was generalized to a read-once
     core `_read_cue_times_multi(want_tracks) -> {track: ticks}` (buckets each cue
     under every track it indexes); new public `cue_reference_times_multi(langs)`
     reads head+Cues+origin ONCE and slices per track. `_embedded_aligned_source_srt`
     calls it once for `try_langs[:3]`. Happy path costs the same single read;
     fallback no longer pays ~1 read/language. Byte-equivalence of the single-track
     wrapper proven by test.
   - **SDH-aware:** SDH/hearing-impaired subs carry the COMPLETE dialogue (+ speaker
     labels), so they are the most complete AI source and best for gender. Embedded:
     `_parse_track_entry` now reads `FlagHearingImpaired` (0x55AB) + `TrackName`
     (0x536E) from the HEAD (free, TorBox-safe -- it's the cheap head read the align
     already does, NOT the full extract). `_track_is_sdh` = flag OR whole-token name
     ('sdh'/'hearing impaired'; NEVER a bare substring -- 'hi' in 'Highlander' can't
     match; bare 'hi'/'cc' are not markers). `_pick_track(..., prefer_sdh=False)`
     prefers SDH ONLY when translating the track's own TEXT (extract_srt); the two
     `cue_reference_times*` timing-skeleton callers keep the DEFAULT (a Sonnet
     BLOCKER: an SDH track's extra sound-cues would depress the external-sub align
     overlap/vote and could unsync a previously-synced sub -- so the align path is
     byte-identical to pre-SDH via a constant sort element). External: `_is_sdh_ext`
     (provider `is_hi` flag or a whole-token release marker via `release_match.tokens`)
     -> SDH subs sort FIRST in their language group + label "תרגום AI לעברית · SDH
     (מדויק למגדר)". The delivered Hebrew keeps `is_hi=False` (its HI brackets are
     stripped before translation, so Kodi's badge must not mislabel it -- the SDH
     signal is the label text only). THREE Sonnet rounds (#37 SAFE; SDH round found
     the align-path BLOCKER + the is_hi mislabel, both fixed; re-review SAFE). Tests:
     31 SDH assertions (synthetic MKV TrackEntry parse, prefer_sdh on/off,
     order-independence, language-confidence, forced-exclusion, false-positive
     suite) + 16 cue-multi + 12 release-name cases. **Phase 2 (not done): harvest
     speaker-label genders BEFORE strip_hi_annotations drops them -> the real gender
     win.** Phase 3 (not done): content-based SDH classification, cached locally /
     shared via a pool SDH registry.

   **Idan Plus self-heal + SDH Phase 2 (AI 0.2.409 / quickfix 0.1.448;
   notification #508):** two things, both inside service.subtitles.kodipovilai
   (pool.py + embedded_extract.py INHERITED byte-identical; worker untouched).
   - **Idan Plus fix (`idanplus_channels_patcher.py`, NEW; wired into service.py's
     `_run_build_startup_repairs`):** the user's idanplus (plugin.video.idanplus,
     Fishenzon, v3.9.9 -- latest, so "update it" does NOT fix it) showed no
     channels, nothing played, nothing even listed. Root cause: idanplus keeps its
     channel map in `displayChannels.json` as a JSON OBJECT `{chID: chan}` (every
     writer writes a dict), but its `ReadList()` swallows any read/parse error and
     returns `[]` (a LIST) as its empty sentinel. A single corrupt/partial file →
     `items(displayChannels)` = `[].items()` → `'list' object has no attribute
     'items'` (common.py:575/709), and the rebuild path (`displayChannels.get`,
     common.py:556) crashes on the same list so it can NEVER self-repair. Our
     patcher: (1) DATA HEAL (version-agnostic) -- if `displayChannels.json` doesn't
     parse to a dict, back it up (`.povil-bak`) and delete it, so idanplus rebuilds
     from its server (idanplus's own mode-22 reset does exactly `DelFile` on this
     file -> delete→rebuild is native); (2) CODE HARDEN (best-effort, exact-match on
     3.9.9 source, atomic tmp+rename write with a `.povil-orig` backup) -- make
     `GetDisplayChannels` always return a dict and `items()` tolerate a non-dict, so
     a future corruption rebuilds instead of crashing. No-op if idanplus isn't
     installed; a valid dict (incl. the user's my_name/my_index/... customisations)
     is never touched; favorites live in a SEPARATE file and are never inspected.
     Sonnet: SHIP-READY (traced every `items()`/`GetDisplayChannels` caller in
     common.py/main.py/iptv.py/reshet.py -- OrderedDict passes the isinstance gate,
     so it's transparent to real data in both py2 and py3). 41 patcher assertions.
   - **SDH Phase 2 (translate.py + srt.py):** keep ALL-CAPS source speaker prefixes
     ("MABEL:") through `_prepare_source` (`keep_speaker_prefixes=True`) so the
     model matches them to the TMDB cast for per-line זכר/נקבה (the pre-existing
     prompt.py SPEAKER-PREFIX HINT -- was dead code because strip_hi_annotations ate
     the prefixes first), then drops the tag. Two Sonnet BLOCKERS from round 1 fixed:
     (1) the fast_first_chunk interim ENGLISH placeholder no longer shows raw tags --
     `fallback_text` is a display-only `strip_leaked_speaker_prefix(src_text)` copy
     (src_text to Gemini keeps the prefixes); (2) the shipped-Hebrew leaked-tag strip
     is now Hebrew-GATED (`_LEAKED_SPEAKER_RE_HE`, lookahead `(?=[^\n]*[֐-׿])`) at the
     FINAL/pooled output only, so an English caption/chyron/URL the model left
     untranslated ("WARNING:", "PART 2:", "HTTP://") is never eaten; the un-gated
     strip stays on the transient/display + pre-Google-source paths (historical
     behavior, never reaches canonical bytes). Content-hash unchanged (single
     `_prepare_source` on both live+backfill). Sonnet re-review: SHIP-READY, both
     blockers fixed, no new shipped-path defects. 38 speaker-prefix assertions.

   **Hotfix: wizard notification crash + idanplus heal first (AI 0.2.410 /
   quickfix 0.1.449; still notif #508):** the 0.2.409 quick_update.txt was
   PREPENDED with a 2nd entry, but the wizard's `split_notify`
   (window.py ~470) does `_id, msg = link.split('|||')` -- it expects EXACTLY
   ONE `|||` in the whole file (the file is a SINGLE, replaced-each-release
   entry, served live from raw main). Two entries -> `ValueError: too many
   values to unpack` at `auto_quick_update()` every startup, which ALSO
   suppressed the notification popup. LESSON: quick_update.txt is one entry,
   REPLACE it, never prepend; verify against split_notify. Fixed by restoring a
   single entry (verified against the exact parser transform). Also moved
   `_maybe_patch_idanplus_channels` to the FRONT of `_run_build_startup_repairs`
   so a corrupt displayChannels.json is healed before the user can open the
   addon (was ~35 steps in). Only service.py + changelog changed in the addon;
   idanplus_channels_patcher.py + srt.py + translate.py + pool.py +
   embedded_extract.py inherited byte-identical (pool key 802ba87a preserved).

   **SDH Phase 3: content-based SDH classification (AI 0.2.411 / quickfix
   0.1.450; notification #509):** an SDH sub is now also recognised from its
   TEXT, not just a provider flag / release marker. `srt.is_sdh_content` (+
   `sdh_content_stats`) is a DELIBERATELY conservative, zero-false-positive
   classifier: it counts cue entries carrying an SDH marker (a bracketed
   sound/action cue with >=2 letters -- so "[2020]"/"(?)" never count -- an
   ALL-CAPS "NAME:" speaker label, or a music glyph) and returns True only when
   total>=20 AND annotated>=12 AND ratio>=0.12 (a regular sub sits well under a
   couple %). New `sdh_registry.py` is a local, fail-open, capped (800), atomic
   JSON store of releases content-detected SDH. In translate.py: the RAW source
   is classified BEFORE `_prepare_source` strips the markers (ordering is
   load-bearing), and if SDH the normalized release is recorded; `_is_sdh_ext`
   then also consults the registry so a future ranking of that release prefers +
   labels it -- content isn't available when the list is first built. A wrong
   entry is cosmetic only (sort + label; delivered Hebrew is always is_hi=False
   plain dialogue), never corrupts a translation. Sonnet: SHIP-READY (could not
   construct a realistic plain sub that classifies SDH). 19 classifier + 22
   registry assertions. Phase 3b (deferred): share this registry via a
   pool-backed SDH registry so users benefit from each other's downloads
   (heavier -- touches pool.py + the worker).

   **SDH Phase 3b: pool-shared SDH registry + 2 dashboard fixes (AI 0.2.412 /
   quickfix 0.1.451; notification #510; worker redeploy):**
   - **Shared SDH (new `sdh_pool.py`; worker `/sdh` POST+GET):** a release one
     user CONTENT-detected as SDH is shared so everyone's ranking prefers+labels
     it. Reuses pool.py's SIGNED transport WITHOUT modifying pool.py (sign covers
     method+path+anon, not the body) -- so the community key stays byte-identical.
     `contribute_sdh` (share-gated, daemon-thread POST, session-dedup +
     skip-if-already-shared), `refresh_shared_sdh` (use-gated, 3-day TTL, warmed
     from the background service via `_maybe_refresh_shared_sdh`), `is_shared_sdh`
     (reads a LOCAL cache only -- NEVER network on the ranking path; 5s memo gated
     on use_enabled). translate.py `_is_sdh_ext` also consults the shared set.
     Worker: dedicated `sdh_reg` D1 table (`INSERT OR IGNORE`, parameterized,
     `idx_sdh_reg_ts` index, cron prune to newest 4000) -- no pool-`kv` pollution.
     COST NOTE: the pool is ON by default for everyone (settings.xml default=true
     + `_maybe_default_pool_on`/`_maybe_force_pool_share`), so 3b runs for all
     users; kept minimal (once-per-3-day GET + rare deduped POST) since we're near
     the CF free-tier cap. Sonnet: SHIP-READY x2 (design + NIT fixes). 30+19+22
     assertions. Phase 3c (further): none planned.
   - **Dashboard fixes (worker only, delivered out-of-band):** (1) Recent-activity
     + failures now sort by `ts` (was `.reverse()` on id/insertion order, so
     late/backfilled telemetry showed out of sequence). (2) A leaked Kodi infolabel
     token ("VideoPlayer.Label") as a title is blanked via a WHOLE-STRING anchor
     `/^(VideoPlayer|ListItem|Container|System|MusicPlayer|Player|Window|Skin)\.[A-Za-z]+$/i`
     at both ingest points (foldEmbVariant + foldRow) -- a real multi-part release
     (Container.2006, System.Crasher.2019) never matches.

   **SDH false-positive fix + RTL period on Latin tails (AI 0.2.413 / quickfix
   0.1.452; notification #511):** two independent fixes.
   - **`_is_sdh_ext` no longer trusts the provider `hearing_imp`/`is_hi` flag.**
     Providers (OpenSubtitles/Subscene) set it to mean "has sound cues", which is
     NOT "has speaker labels" (what the gender-accuracy claim needs), and they
     mislabel -- the user saw plain subs tagged "SDH (מדויק למגדר)". Now ONLY two
     reliable signals set the SDH label: a whole-token `sdh`/`hearing impaired`
     release marker, or the content-detection registry (Phase 3a local + 3b
     shared). IMPORTANT (answered a maintainer question): this is NOT retroactive
     and did NOT poison the pool -- the flag only ever drove the picker LABEL+SORT
     (`_is_sdh_ext`, ephemeral); the registries/pool are fed ONLY by
     `srt.is_sdh_content` (translate.py:2253), never the flag.
   - **`srt.py` reverse-mode Latin-continuation period:** when a Hebrew sentence's
     final token is a Latin word wrapped onto its OWN line (a username like
     "Modelbehavior36."), `_TRAILING_PUNCT_RE` (Hebrew-required) skipped it so the
     period stayed wrong. Added `_LATIN_TAIL_PUNCT_RE` + cue-Hebrew tracking
     (`cue_hebrew`, reset at cue boundaries) so such a line's trailing punct moves
     to the start too, with dash+open/close-tag groups mirroring the Hebrew path.
     Sonnet x2 (found+fixed 2 SHOULD-FIX: dash/tag mishandling). 23 assertions.

   **RTL "BiDi base" mode -- root-cause RTL fix (AI 0.2.414-0.2.416):** the
   `reverse` mode only moves the sentence period; embedded LTR runs (numbers like
   "50 מייל", English names, quoted English, parentheses) still landed on the
   wrong side because the observed players render Hebrew lines with an LTR BASE
   direction. New `rtl_base` mode wraps each Hebrew line in an explicit RTL
   embedding `RLE(U+202B) .. PDF(U+202C)` so the player's own BiDi gives it a
   right-to-left base and places EVERYTHING correctly. Root cause + fix were proven
   with the `python-bidi` reference engine (LTR-base reproduces the exact bugs;
   the wrap == a true RTL-base render for all observed cases incl. the mixed
   parenthetical). Non-mutating (marks only). Every mode NORMALIZES on read (strips
   BiDi marks + re-derives its own shape), so cached/pool text -- which carries no
   mode metadata -- renders correctly under any mode and switching modes is safe.
   - **0.2.414 (quickfix 0.1.453; notif #512):** shipped as an OPT-IN mode
     (`rtl_punct_mode=rtl_base`, settings option #32227). `_wrap_rtl_base_line`
     wraps Hebrew lines and, crucially, first runs the legacy leading->trailing
     normalization so `reverse`-shaped cache/pool text (period at the START) is
     put back to logical order before wrapping (Sonnet caught this SHIP-BLOCKER:
     otherwise it rendered mirror-backwards). Sonnet x3.
   - **0.2.415 (quickfix 0.1.454; notif #513):** a single-token Latin username
     TAIL of a Hebrew cue (e.g. "Modelbehavior36.") is now wrapped too so BiDi
     moves its trailing period to the RTL-correct (left) side. The wrappable class
     is `_WRAPPABLE_LATIN_TAIL_RE = ^[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*[.,;:!?]\Z`
     -- ASCII letter-first, alnum runs joined by single hyphens, one trailing
     punct. This exact class was PROVEN by an 800k-token adversarial fuzz vs
     python-bidi to reorder ONLY the trailing punct, never the body; anything else
     (leading digit/symbol `7-Eleven.`->`.Eleven-7`, `@handle.`->`.handle@`,
     multi-word `50 miles.`->`.miles 50`, internal symbol/dot, edge/double hyphen)
     is EXCLUDED and left LTR unchanged. Two earlier narrower guards (single-token,
     then `isalnum`) each let a reorder class through -- the char-class regex is the
     robust answer. Sonnet x4.
   - **0.2.416 (quickfix 0.1.455; notif #514):** `rtl_base` is now the DEFAULT
     (settings.xml default + srt.py three fallbacks reverse->rtl_base; labels/help
     reworded; `reverse` kept for players that ignore the marks). Purely a local
     rendering default -- no network/pool/worker impact. Maintainer-approved after
     on-device verification. Because this flip runs `rtl_base` over every existing
     user's `reverse`-SHAPED cache (`_reapply_rtl_fix_in_place` reruns on every
     cache hit), `_wrap_rtl_base_line` gained a cache-repair step: `reverse` had
     relocated a leading dialogue dash "- " to a TRAILING " -" (and the punct to
     the front), which the leading-only normalization couldn't undo -- so a
     two-speaker cue rendered with the dash stranded. The Hebrew-line branch now
     moves a trailing " -" back to a leading "- " when `_LEADING_PUNCT_RE` matches
     `st[:-2]` (that regex skips a leading open-tag run, so `<i>`-wrapped cues are
     handled too; a genuine trailing interruption dash "שלום -" has no leading
     punct so it's left alone). Sonnet x2 (found+fixed a tag-blind SHIP-BLOCKER);
     169 assertions + 3.7k-shape dash fuzz + 800k-token username-tail fuzz across
     the series, all vs the python-bidi reference engine. Known residual (pre-
     existing, out of scope, rare): a reverse-relocated trailing ELLIPSIS ends up
     mid-line under `rtl_base` -- the dash is fixed but the "..." placement is the
     same imperfection as 0.2.415, since `_ELLIPSIS_RE` can't tell a genuine
     leading ellipsis from a relocated one.
   **Large-source translate fix + progress logging (AI 0.2.417 / quickfix
   0.1.456; notif #515):** a user reported clicking embedded (SDH) translation --
   the "AI מתרגם" toast showed but NO Hebrew ever appeared. Log trace: the thread
   logged `Starting translation src_len=152554` (a 152KB SDH source) then went
   totally silent -- translate.py had NO per-chunk logging, so the run was a black
   box; the result was discarded as empty/echoed. Leading cause: with
   `whole_subtitle_request` ON, a 152KB source goes as ONE Gemini request whose
   Hebrew output overflows the 65535-token cap -> truncated -> whole result
   dropped as empty, and whole-request mode shows no progressive display. Fix in
   translate.py: (1) after reading `whole_subtitle_request`, if it is ON and
   `len(src_text) > 80000`, log a WARNING and force `whole_subtitle_request=False`
   (fall back to chunked -- the guard sits before ALL downstream uses so it
   cascades: max_output_tokens 16384, chunk_blocks, parallel, prev_context, and
   per-chunk `progressive_cb` all re-enable). (2) Added a dispatch-summary INFO log
   (chunk count / mode / parallel / paid / src_len) + a first-chunk-returned log,
   so a future stall is diagnosable from the log. NOTE: the whole-request cause is
   a HYPOTHESIS (the reporter's exact settings were unknown); the change is a safe
   guard + observability either way -- if the guess is wrong, the new logs pin the
   real cause (the same session's log also showed heavy network contention: TorBox
   CDN streaming + 28 stuck pool uploads, which can starve the Gemini API calls).
   Sonnet: SHIP-READY (cascade correct, no regression, progressive re-enabled).

   **Bisection milestone logging (AI 0.2.418 / quickfix 0.1.457; notif #516):** a
   fresh report of the same embedded-SDH stall arrived with `whole_subtitle_request`
   confirmed OFF by the reporter -- so 0.2.417's whole-request guard did NOT apply
   and the real cause was still open. The log showed `Starting translation
   src_len=152554` then silence, never reaching the 0.2.417 dispatch summary. Added
   four INFO milestone logs across the *pre-dispatch* path in translate.py
   (`resolving cast metadata`, `cast ready (N members); building prompt`, `N blocks
   parsed, gender_ref=...`) to pin exactly which pre-dispatch step goes silent.
   Diagnostic only, no behaviour change. Sonnet: SHIP-READY.

   **False Hebrew-passthrough: English source shown untranslated in a loop (AI
   0.2.419 / quickfix 0.1.458; notif #517):** the 0.2.418 milestones showed the
   worker logging `Starting translation` then NONE of the milestones. The FIRST
   hypothesis was a `notify()` stall on a GUI wedged by heavy extraction (the three
   statements before the first milestone are `notify()` / `language_detect.detect()`
   / `get_setting()`, and the decoder WAS starving). That was WRONG, and the reporter
   supplied the disproof: the player stayed fully responsive (seek/pause/resume), the
   screen showed the untranslated ENGLISH, and -- decisively -- on the SAME movie in
   the SAME session the RUSSIAN embedded track translated perfectly (full milestones +
   43-chunk dispatch + first-chunk-returned) while only the ENGLISH track died
   silently. A responsive GUI + a peer translation succeeding rules out any hang; the
   silence is a FAST silent RETURN, not a stall. Root cause: the "source already
   Hebrew -> pass through" sanity check at translate.py used
   `language_detect.detect(src_text[:8000]) == 'he'`, and `detect()` returns 'he' on
   an ABSOLUTE count (`he_count > 30` anywhere in the first 8000 chars) -- so an
   English/SDH sub carrying a little Hebrew (a "translated by..." credit line) was
   judged "already Hebrew" and passed through UNtranslated. detect() checks `he`
   BEFORE `cy`, which is why English (some Hebrew -> 'he') looped but Russian (-> 'ru')
   translated. The passthrough writes `src_text` to the translation cache path UNGATED
   (every real path is `_is_mostly_hebrew`-gated), so the untranslated English got
   cached; the next attempt read it, judged it non-Hebrew (`Discarding non-Hebrew
   cached translation (empty/echoed)`), and re-ran -- an endless no-op that reads as
   "says it's translating but never does". Fix: the check now uses
   `_is_mostly_hebrew(src_text, min_ratio=0.60)` over the WHOLE source (not a
   head-sample, so a localized Hebrew credit/header block can't skew the ratio), only
   passing through when Hebrew genuinely dominates; a mostly-English/mixed source
   translates as expected. The passthrough is also no longer silent (INFO log).
   Verified with a unit harness (English w/ Hebrew credit -> translate; real Hebrew ->
   passthrough; even a 20x-inflated Hebrew header stays "translate"; whole-source scan
   ~8ms/152KB). BUNDLED hardening (NOT the cause, but validated + kept as
   defence-in-depth): `kodi_utils.notify()` now fires the GUI toast on a short-lived
   `pov-notify` daemon thread with a bounded pending-count, so a genuinely wedged GUI
   can never stall a caller; plus a `language ok, mode=...` milestone log. Sonnet:
   passthrough-ratio + notify hardening both validated SHIP; the `_is_mostly_hebrew`
   denominator widening (count letters of ANY script, not just ASCII, so a non-Latin
   source + a Hebrew credit line can't read as "100% Hebrew") and the dead
   `language_detect` import removal were the passthrough reviewer's own
   recommendations, implemented and unit-tested across all three callers.

   **SDH music-note garble: a cp1255 mis-decode of a UTF-8 source (AI 0.2.420 /
   quickfix 0.1.459; notif #518):** users saw an ugly 3-char garble `ג™×`
   (gimel + trademark + multiplication) at the start/end of SDH song lines
   instead of a music note, and it was even translated-through into the shared
   pool (field: an embedded/SDH translation of a Michael Jackson biopic).
   ROOT CAUSE: `subs_engine/extract_sub.convert_to_utf()` blindly decoded EVERY
   downloaded subtitle as cp1255 and rewrote it UTF-8. An English SDH sub is
   pure ASCII except the note `♪` (U+266A, bytes E2 99 AA); ASCII is identical
   in both encodings, so only the note was mangled -- cp1255 maps E2 99 AA to
   `ג™×` -- and the AI faithfully preserved the non-word garble. (A file
   carrying a byte UNdefined in cp1255 raised and was left as UTF-8, which is
   why only some subs broke.) This affected EVERY downloaded sub, not just
   embedded -- any UTF-8 source whose only non-ASCII bytes are cp1255-defined
   (the note, and typographic `’ – — … •`). Two client-only fixes (translate.py
   / pool.py / kodi_utils.py all INHERITED byte-identical; pool key 802ba87a
   preserved): (a) ROOT -- `convert_to_utf` now decodes `utf-8-sig` FIRST and
   falls back to cp1255 only when strict UTF-8 fails (a genuine cp1255 Hebrew
   file's 0xE0-0xFA letter bytes are never valid UTF-8, so it still converts
   correctly; a real UTF-8 file is preserved, note intact); leaves the file
   untouched if both fail (the historical fail-open). (b) READ-REPAIR --
   `srt.repair_music_mojibake()` restores `ג™×`-style garble to the note at the
   top of `fix_rtl_punctuation` (the canonical read-normalizer run on every
   cache hit AND the `kind=='pool'` download path via `_reapply_rtl_fix_in_place`)
   -- so lines ALREADY cached/shared to the community pool are repaired on read
   for everyone who downloads them, no re-upload/worker change. Covers the whole
   note family ♪♫♬♩♭♮♯. SURGICAL: a compiled regex `(?<![א-ת])ג™[×«¬©­®¯]` --
   anchored to a NON-Hebrew-letter left boundary because an SDH note is a
   standalone glyph at a word/line boundary, never a word's final letter -- so
   it repairs the genuine garble but never eats the trailing gimel of a real
   word (e.g. a gimel-final brand name followed by stacked trademark symbols).
   THREE things validated computationally over TWO Sonnet rounds: round 1 (full
   diff) proved the root fix can't mishandle real cp1255 Hebrew (structural
   UTF-8 impossibility) + the map is byte-exact (incl. the invisible U+00AD
   flat-note tail) + BOM/empty/newline/idempotency, and found ONE NIT -- the
   original blind `str.replace` could corrupt a contrived `"סמסונג™®"` ->
   `"סמסונ♮"` and the "never in Hebrew" comment overclaimed; round 2 confirmed
   the regex-anchoring closes that collision (50 gimel-final variants + all 5
   Hebrew final forms) with ZERO regressions on 13+ genuine SDH boundary shapes
   incl. the user's real cue, KeyError impossible by construction, linear perf.
   Both rounds SHIP. ~44 local unit assertions also pass. Known accepted
   trade-off: a note glued to a Hebrew word with NO separator (`"לאחורג™×"`) is
   left unrepaired -- authored SDH always delimits the glyph with a space, and
   byte-level corruption preserves the original spacing, so this never occurs in
   practice while the false-positive it guards against is real. Standalone repo
   bumped (repo/addons.xml + md5 + repo/zips + dist/-latest.zip). worker.js
   UNTOUCHED (no redeploy).

   **Cloudflare invocation cut + telemetry ordering + dashboard-correctness +
   music-note-on-store (AI 0.2.421 / quickfix 0.1.460; notif #519; + a worker.js
   change delivered OUT-OF-BAND):** the Worker hit ~101k requests/day, just over
   the 100k/day free tier. A comprehensive invocation audit (client + worker)
   found the dominant, invisible cost driver:
   - **THE 426 badge bug (client, he_sub_match.py):** the source-screen Hebrew-%
     badge's pool `/lookup` was built with ONLY a User-Agent header -- no
     x-pov-v/x-pov-sig -- so the Worker's poolAuth (which checks VERSION before
     signature) rejected EVERY call with HTTP 426. Verified live (curl: 426 with
     just UA; 401 with a version header + no sig). Effect: the badge never got
     pool data (silently broken feature) AND it burned ~2 invocations/title (both
     call sites; the _ok-gated 15s memo never armed), default-on for 100% of
     installs, driven by the frequent BROWSE action (source-window open), not just
     playback -- almost certainly the bulk of the 101k. Fix: `_pool_lookup` now
     signs via `pool._get` (the service-process warm can import pool); the
     POV-side synchronous peek in `release_names` (POV's restricted interpreter
     can't sign, always 426'd) is DROPPED -- the signed warm fills the same disk
     cache its poll-loop already reads, so first-entry UX is unchanged and pool
     data returns to the badge. Positive side effect the reviewer found: the bug
     kept `ktuvit_checked` stuck at 0 -> `kt_active` always true -> every warm
     spawned the live-Ktuvit top-up; the fix restores that throttle too.
   - **Badge cache TTL (client):** `_pick_ttl` returned the SHORT (8h) ttl for
     has-names titles whenever `kt_active` (defaults true for any recent title),
     so a popular title with Hebrew re-hit /lookup every 8h for nothing. Now
     has-names is cached 48h (`_LOCAL_MED`) while Ktuvit-active / 7d when stable,
     regardless of kt_active; no-names raised 8h->24h. Accepted coupling: the
     live-Ktuvit re-poll floor rises 8h->48h (badge is advisory; the real fetch
     path pool.lookup keeps its own 90s cache).
   - **Telemetry ordering (client, translate.py):** `_emit(True)` ran AFTER
     `pool.contribute_once`, so a fresh translation's telemetry was queued too
     late to ride its OWN /contribute piggyback -- it waited for the NEXT
     contribute or the periodic /ev flush, so the last/only translation of a
     session reached the pool (Recent embedded) but never the telemetry-fed Recent
     activity view (the user's "English מייקל missing from Recent activity"), and
     it caused extra standalone /ev flushes. Fix: emit BEFORE the contribute so
     every event rides its own upload (idempotent guard keeps it single) -- fixes
     completeness AND cuts /ev invocations. Reviewer confirmed no race (the queue
     write is synchronous and completes before the daemon thread is spawned).
   - **Worker (worker.js, delivered out-of-band):** (a) MUSIC-NOTE REPAIR-ON-STORE
     -- `repairMusicMojibake` (mirrors 0.2.420's client srt fix, boundary-anchored
     regex `(?<![א-ת])ג™[×«¬©­®¯]`) runs on `body.srt` in contributeCore AND on the
     lazy result-hash backfill's downloaded content, so old-client garbled uploads
     are cleaned at the store and dedup stays consistent old-vs-new. (b) DASHBOARD
     data-correctness (from a separate full section-by-section audit): version gate
     `String(r.v) >= TELE_MIN_VER` -> numeric `verCmp` (a string >= wrongly folded
     ancient "0.2.9" and, the real time-bomb, would silently DROP a future
     "0.10.0"/"0.2.1000"); `ROLL_SCHEMA` 5->6 forces a clean rebuild that purges
     the mis-folded rows; the d1/h1 trailing SQL drops its broken `v >= '...'`
     filter (no-op on real data, removes the same time-bomb). Recent-embedded now
     sorts by ts (was `.reverse()` on backfill-scan order) and its 40-cap evicts
     the OLDEST-by-ts (was a blind shift() that could drop the newest live row).
     Top-embedded-titles per-title `src` is no longer OVERWRITTEN (a title
     translated from EN + RU -- e.g. "מייקל" -- showed one language beside a count
     of 2; now marks 'mixed'). recTail/failTail retention evicts oldest-by-ts (was
     FIFO). Disclaimers added clarifying the telemetry(Recent activity) vs
     pool(Embedded) distinction. /stats self-reload 120s->600s.
   TWO separate Sonnet validators (client + worker), BOTH SHIP. Each SHOULD-FIX
   applied: client (stale _pool_lookup/_memo docstrings, dead `timeout` param, the
   Ktuvit-coupling comment); worker (repair the backfill's `existing` before
   hashing so old-garbled vs new-clean dedup; stale schema comment). Deferred (all
   documented): the list_candidates autosub-vs-native double-lookup guard (#3 --
   medium-confidence, playback-bounded, needs a sensitive pool.py cross-process
   memo); the merge of pool-embedded into Recent activity (B fixes the root; a
   merge mixes telemetry+pool data models); a music-note backfill of EXISTING
   Telegram files (expensive re-upload changing file_ids; client read-repair
   already fixes display); and dashboard NITs F (abuse-watch 1000-key cursor), G
   (season/episode digit-constrain at the /ev ingest -- non-exploitable, render
   esc()'d), H ("no data yet" copy keyed on delivered vs attempted). `_seed_from_pool`
   is now dead (harmless) -- future cleanup. pool.py INHERITED byte-identical (key
   802ba87a; standalone SWAPs only translate.py since he_sub_match is POV-only).
   **CONFIG the maintainer applies at deploy:** redeploy worker.js to Cloudflare,
   and change the cron in wrangler.toml `*/2 * * * *` -> `*/15 * * * *` (720->96
   scheduled invocations/day; the rollup also self-updates on /stats loads, so the
   cron is optional). No /backfill needed (ROLL_SCHEMA=6 rebuilds automatically;
   repair-on-store is automatic).
15. **Fewer pool requests (Tier 2) + a regression guard, a "don't redo a pooled
   embedded translation" UX fix, and an owner-dashboard embedded-titles pass —
   SHIPPED (AI 0.2.422 / quickfix 0.1.461; notif #520, and AI 0.2.423 / quickfix
   0.1.462; notif #521; + worker.js out-of-band).**
   - **Tier 2 lookup-sharing (client; 0.2.422):** within one playback the badge
     warm (he_sub_match `_pool_lookup`) and autosub's `pool.lookup` both hit
     `/lookup` for the same title. `_pool_lookup` now routes through
     `pool._lookup_raw`, so both SHARE pool.py's 90s in-process `_LOOKUP_CACHE` --
     the second is a cache hit (no Worker request). One request per playback
     instead of two in the common case (same tmdb key). Reviewer confirmed
     cache-key parity + 426 signing preserved.
   - **pool.py negative-cache guard (client; 0.2.422) — the reviewer's BLOCKER,
     fixed before ship:** `_lookup_raw` cached `{}` for 90s on BOTH a reachable
     "no results" answer AND any transient error (network/timeout/parse). Once the
     warm shares that cache with autosub (Tier 2), a warm-side blip could poison it
     and hide a real pool subtitle from autosub -> wasted retranslation. Fix: a
     `cacheable` flag -- a transport failure is NOT cached (a genuine reachable
     negative still is). Scoped entirely to pool.py; also fixes a latent bug that
     already affected autosub. pool.py is KEY-BEARING: shipped via key-splice (repo
     edited code + the base zip's real key block; proven to differ from the prior
     release ONLY inside `_lookup_raw`; md5 802ba87a preserved). Sonnet SHIP.
   - **Don't regenerate a pooled embedded translation (client; 0.2.423):**
     `list_candidates` now SUPPRESSES the local "translate embedded -> Hebrew (AI)"
     generator for a source language the pool already holds an embedded (`ai_emb`)
     translation for THIS EXACT release (`_pool_has_emb`, gated on the same
     `_emb_ok`/TIER_EXACT same-source predicate the pool listing uses). The instant
     "· מאגר קהילתי · 100%" pool item already covers it, so the local extract+AI
     pipeline isn't re-run for a one-click result. Same-source only (never
     suppresses when the pool can't actually serve your release); no-op when the
     pool is off; `have_hebrew` stays correct (the suppressing variant was already
     listed by the pool loop). pool.py + he_sub_match INHERITED byte-identical this
     round (0.2.423 swaps only translate.py). Sonnet SHIP (7 adversarial checks).
   - **Worker owner-dashboard (worker.js, delivered out-of-band):** (a) EMBEDDED
     titles -- "Top/Recent embedded" now LIST the actual source languages
     ("English, Russian") instead of collapsing to "mixed" (a per-title `langs`
     map, backward-compatible; old blobs still render, a `reset=1` backfill
     repopulates), and resolve a HEBREW display title from each row's tmdb/imdb id
     via TMDB (cached in D1 through the POOL shim; fixes the bare "#id" labels).
     Owner-only + 15-min page cache, so it costs a handful of TMDB SUBrequests per
     recompute (NOT Worker invocations) -- and the resolver caps uncached ids/render
     and forces `tmdbFetch` to a SINGLE try there (default 3 elsewhere) so a 429
     burst on the shared public key can't blow the 50-subrequest budget or starve
     the live `/contribute` enrichment path. (b) Prior deferred dashboard NITs F/G/H
     done (abuse-watch ranked by a direct D1 query with fail-open shim fallback;
     season/episode digit-constrained at the /ev ingest; "no data" copy keyed on
     attempted-not-delivered). (c) Recent activity is now TELEMETRY-ONLY: the
     pool-embedded rows were briefly merged in (the deferred "safety net") but
     rendered as blank no-version/method rows the maintainer found to be clutter, so
     they were removed -- every embedded translation is already counted under
     "Embedded translations" (the pool-derived view). Storage note: the live Worker
     runs on D1 (`env.POOL` is a D1-backed KV shim, `makeD1Store`), so all of this
     lands in D1, not KV. FIVE Sonnet validators across these worker changes, all
     SHIP (one FIX applied: the tmdbFetch retry-budget). Requires at deploy:
     redeploy worker.js + run `/backfill-emb?key=…&reset=1` once to populate the
     new per-title langs/id/he-title fields for historical rows.
   - **DEFERRED — per-track embedded translate actions (#4):** currently one
     "translate embedded" action per source LANGUAGE (dedup by code in
     `list_candidates`). Offering one per genuinely-distinct track (full vs forced
     vs SDH) is blocked by three compounding obstacles found by reading the resolve
     path: Kodi's `getAvailableSubtitleStreams()` usually returns just the language
     (no forced/SDH flavor to tell two same-language tracks apart); the embedded_ai
     resolve extracts by LANGUAGE, not by the picked track; and Kodi's subtitle
     stream_index != the container's MKV track number. A correct implementation
     needs flavor-parsing (subs_engine_bridge) + a stream-index->track mapping +
     changes to BOTH the align and extract paths -- a real mini-project in the core
     playback path, for a benefit that is inert whenever the container doesn't label
     its tracks. Left as-is by maintainer decision.
16. **Local RTL delivery repair + request-safe pooled sources + outline-only
   subtitle defaults (AI 0.2.443 / quickfix 0.1.485 / notification #543).**
   This release closes the known `rtl_base` legacy-cache punctuation gap without
   rewriting the community pool.
   - **Immutable source, disposable display copy:** `subs_engine_bridge.py`
     keeps the canonical provider/pool SRT unchanged and returns a sibling
     `.povil-rtl.srt` only for playback. Pool hashing, sharing and the `.shared`
     marker always resolve back to the immutable source. New provider sources
     receive a local `.logical-v1` marker; unmarked pre-migration v2 cache files
     are treated as legacy. Display copies and sidecars are excluded from cache
     source counts.
   - **Punctuation compatibility:** `srt.fix_rtl_punctuation` now accepts an
     explicit legacy-engine flag. For positively identified legacy content it
     restores a dialogue dash stranded at the logical end after displaced
     punctuation and restores legacy-relocated ASCII/Unicode ellipses to the
     logical end before applying the RTL base wrap. Fresh logical/local/AI text
     preserves a genuine leading ellipsis. This distinction cannot be inferred
     losslessly from text alone: an old relocated trailing ellipsis and a genuine
     authored leading ellipsis have identical bytes. The accepted compatibility
     rule is therefore deliberately aggressive only for positively legacy-tagged
     old Ktuvit/cache content.
   - **No pool rewrite or provider storm:** pool rows carry source metadata into
     resolution. A pooled source is fetched once through `/sub`, then cached
     locally by its result hash; display repair never mutates or re-contributes
     it. Harvest normalizes Ktuvit release names through the same Worker release
     normalization (including removal of a trailing `.srt`) and both asynchronous
     and durable synchronous contribution paths suppress `/contribute` when the
     request-cached `/lookup` already contains that exact release. There is no
     cache-version bump, purge, provider refetch, mass download, mass re-upload,
     Worker deployment or pool backfill in this release.
   - **No-box subtitle presentation:** `hebrew_build_ui_patcher.py` performs a
     one-time, retry-safe JSON-RPC migration only when the complete 20-setting
     subtitle-style fingerprint exactly matches build 0.1.101. It changes
     `subtitles.backgroundtype` from box to outline and reduces the black border
     from 41 to 25; every other style value remains fixed. The exact target is a
     no-op and any customized profile is preserved wholesale. The migration
     handles Kodi 21's boolean `result:true`, verifies readback and records
     pending/applied/preserved in hidden schema-v1 state. This setting is global
     to Kodi, not skin-specific. Authored ASS/SSA styles remain authoritative
     while `subtitles.overridestyles=0`.
   - **Packaging/privacy gate:** standalone/versioned/latest/repository packages
     are byte-identical (SHA-256
     `a211ec2ce995b5b31daa7b017ae78bea7968681c380932e881a993b4e83853f9`);
     the repository metadata MD5 is
     `9982625828a9febfa78960ed16eefb0d`. Quickfix 0.1.485 is a surgical copy of
     0.1.484 with exactly eight intended MoranSubs members replaced (SHA-256
     `add70dbedc8b2bcaa41ed5ca4f2b8964b32dc63e0d75f9cd02766fe59026923a`);
     member order/metadata and all other 1,925 members are unchanged, no
     `guisettings.xml` is carried, and the protected pool block is inherited
     byte-for-byte. The local packaging helper remains ignored. `pool/worker.js`
     is untouched and no streaming/private artifact is in scope.
   - **Validation:** dedicated suites cover logical vs legacy dash/ellipsis
     handling, Unicode ellipsis, interruption dashes, idempotence, python-bidi
     visual positions, immutable delivery sources, one-fetch pool caching,
     release dedup including a no-network synchronous guard, exact old/target/
     customized subtitle fingerprints, boolean JSON-RPC success and retry after
     failure. The normal embedded/gender, hidden-settings and platform-package
     regressions also remain release gates. Two independent read-only reviews
     returned SHIP; the leading-ellipsis ambiguity above is the explicit
     maintainer trade-off.
   - **Verified publication record (2026-07-25):** Phase 1 shipped through PR
     #390 / merge `1a84b887e741f78eacbe92381744cdc66e4eedf8`; Pages run
     `30159954536` succeeded. Raw and Pages artifacts, repository metadata,
     mutable `build.txt` and immutable `build_versions/543.txt` were exact at
     16:38:09 Israel and remained exact after the full cache gate at 16:43:44,
     while notification 542 stayed live. Phase 2 changed only
     `quick_update.txt` in PR #391 / merge
     `9e0d3fb7784524cd81f5a02197d2067259f0446d`; Pages run `30160446230`
     succeeded. Notification 543 (SHA-256
     `293b67d72e535574b0ce5e136048ae16a0e92368f09d36abdd139aca550cb629`)
     was byte-exact on Raw and Pages at 16:52:39 and again after a 334-second
     cache gate at 16:58:13. No Worker, credential, streaming payload or local
     packaging helper entered either release phase.

17. **A translated line frozen on screen — SHIPPED (AI 0.2.444 / quickfix
   0.1.486 / notification 544).** Two users reported one Hebrew line welded to
   the screen while the rest of the dialogue came and went underneath it; a
   different line each re-translation, and clearing the add-on cache did not
   help.
   - **Root cause:** the translator hands the model whole SRT entries
     *including their timecode lines* and stitches the reply back verbatim. The
     only validation on that reply is an ENTRY-COUNT check, so a single mistyped
     digit in a timestamp the model was merely asked to copy ships straight to
     the player. One hour digit is enough: `00:41:22 --> 01:41:24` is a
     60-minute cue. Re-translating produced a *different* frozen line because the
     model mistyped a different entry, which is why a cache clear appeared to do
     nothing.
   - **Primary fix — the model is never trusted with timing.**
     `srt.restore_block_timings()` gives every translated entry its SOURCE index
     and timecode back. Pairing is positional but *verified* before it is
     trusted: TOTAL start-timestamp agreement is required, because equal entry
     counts are necessary and not sufficient (a stray blank line can split one
     cue and drop another, keeping the count intact while shifting everything
     after it). On any disagreement it falls back to matching each output entry
     to the source entry with the same start; duplicate starts are ambiguous and
     are left untouched on both paths rather than risk swapping text.
   - **Backstop — deliberately conservative.** `srt.clamp_cue_durations()`
     bounds each cue's end for what pairing cannot cover (an entry count that
     legitimately differs, or a pathological cue in the SOURCE subtitle). The
     ceiling is 3 minutes absolute, or the next later-starting cue plus 10
     seconds of overlap grace. That is tuned to never damage a correctly
     authored subtitle at the price of leaving a corrupt cue a few seconds long:
     real subtitles contain 90-second credit cards, long title cards over silent
     scenes, and intentional overlap (a location sign held across several
     dialogue lines, ASS-converted dual-speaker tracks). An earlier 25-second
     ceiling truncated all four and was rejected. Starts are never moved.
   - **Nothing already accepted becomes rejected.** The clamp rewrites timecode
     lines only. Over 400 randomised subtitles including degenerate ones, entry
     count, text bytes and Hebrew ratio are invariant — and those are the only
     three things any gate in the pipeline inspects. No subtitle that passes
     today can start failing.
   - **Subtitles already translated and shared are repaired on delivery.** Pool
     dedup is by source hash, so a poisoned variant is never re-translated and a
     server-side rewrite would not reach anyone; the repair therefore lives at
     every point where bytes are handed to the player. Three separate delivery
     bypasses were found one at a time across four review rounds — the cache-hit
     path and the progressive path in `default.py`, the pool path
     (`_reapply_rtl_fix_in_place`), and finally `_rtl_delivery_copy`, which
     serves `resolve()`'s `passthrough` branch for a subtitle saved ALONGSIDE
     THE VIDEO. That last one matters disproportionately: it is a common Kodi
     configuration and the one place the startup migration cannot reach, since
     that walks `cache/translated/` only. Its "nothing changed" shortcut had to
     move too, or a clamp-only repair would have returned the original path.
     `CACHE_RTL_FIX_VERSION` is bumped 4 -> 5 so the one-shot backfill re-runs
     for every existing install.
   - **The standalone edition nearly shipped without half of it.** The packager
     does not ship `service.py` in the standalone package; `copy_common()`
     overwrites it from `SLIM_SERVICE`, a separate embedded copy inside
     `tools/build_ai_subtitles_packages.py`. That copy still carried the old
     marker version and the unclamped repair, so the repository-channel add-on —
     what most users install — would have received the forward fix and the
     delivery repairs but not the retroactive backfill. Caught during packaging,
     mirrored, and now covered by a static guard.
   - **Deliberately NOT clamped:** `subs_engine_bridge._render_hebrew_rtl_copy`,
     which renders third-party engine downloads. Those bytes never pass through
     the model, so this failure cannot arise there; the add-on already treats
     third-party timing as more trustworthy elsewhere (subsync uses a
     foreign-language human subtitle as the oracle it corrects AI timing
     against), and third-party SRT formatting is far more varied. The reasoning
     is recorded in that function's own docstring so a future stuck-cue report
     against an engine download starts from the decision rather than from
     scratch.
   - **Packaging/privacy gate:** standalone versioned/latest/repository packages
     are byte-identical (SHA-256
     `b4622c8e388ee5ad30b947f318ccb4a51a1084f1e4ebdd75530b9c73ae9a4b50`); the
     build edition versioned/latest are byte-identical (SHA-256
     `31ca4de60c56bfb38925fb7a0331258b4003f9544981a89cf1fd48c105a6443a`); the
     repository metadata MD5 is `a9f174e85be04986850d154842868d7e`. Against
     0.2.443 no package gains or loses a single member and exactly seven differ.
     Quickfix 0.1.486 is a surgical copy of 0.1.485 with the MoranSubs subtree
     replaced (SHA-256
     `e7ef583dcec199a4e4cbf418f9497108dfefba8c5dd64445074523d56f284e0b`); member
     order and metadata are preserved and all other 1,926 members are unchanged.
     The protected pool block is inherited byte-for-byte and was cross-checked
     identical across every shipped version from 0.2.363 on before it was
     carried forward; the build refuses to proceed if those disagree. The local
     packaging helper remains absent and ignored, no credential enters tracked
     source, `pool/worker.js` is untouched and no streaming or private artifact
     is in scope.
   - **Update reachability.** Build-edition users do not have the repository
     add-on installed, so Kodi never auto-updates MoranSubs for them and the
     quickfix is their only route — which is why every subtitles release ships a
     matching quickfix (0.2.441/0.1.481, 0.2.442/0.1.482, 0.2.443/0.1.485). All
     five routes were resolved to the concrete bytes a client fetches and
     asserted to contain the fix: repository channel, both direct-install links,
     `build.txt`, and the immutable `build_versions/544.txt`.
   - **Validation:** 76 checks over the real functions and real files — the
     reported failure reproduced then fixed, positional pairing defeated by a
     6.7% tail shift, duplicate starts, rapid exchanges where a minimum duration
     must not re-create overlap, CRLF preservation, out-of-order neighbours,
     fail-open on junk, and every delivery path driven end to end. Plus a static
     guard, swept over the whole add-on with two reasoned exemptions, asserting
     no function applies the RTL fix without also bounding cue durations; proven
     non-vacuous by re-introducing each bypass. The suite was re-run against the
     bytes extracted from the shipped zip, not the source tree. Four independent
     read-only review rounds; the last returned SHIP with no blocking findings.
   - **Verified publication record (2026-07-26):** Phase 1 shipped as
     `c15dd3c` (add-on 0.2.444, quickfix 0.1.486, `build.txt` and the immutable
     `build_versions/544.txt`), fast-forwarded onto main from
     `0b4d139878d6dda72a1d43c6aae7ccd21461cc42`. Pages served the new repository
     metadata 100 seconds after the push. Every artifact a client actually
     fetches was downloaded in full and compared byte-for-byte, not merely
     probed for a status code: Pages `repo/addons.xml`, its MD5 and the
     advertised zip; Raw `build.txt`, `build_versions/544.txt`, both direct
     install zips and the 33 MB quickfix. All exact at 17:10:27 Israel and still
     exact at 17:16:12 after a 345-second cache gate, with notification 543
     deliberately left live throughout. Phase 2 changed only
     `quick_update.txt` in `f373944`; notification 544 (SHA-256
     `3ba4ae961231fff7c313240ac0d6be1eb8a09d2ec1a5ac13ed903975abc5ae9f`) was
     live on Raw 120 seconds later and byte-exact on both Raw and Pages at
     17:27:09 after a 348-second gate, alongside a full re-verification of the
     phase-1 surface. Every component version named in the note was cross-checked
     against what is actually published rather than carried over from the
     previous note -- which is how a draft still reading `quickfix 0.1.485` was
     caught before it went out. No Worker, credential, streaming payload or local
     packaging helper entered either release phase.


18. **Embedded rows lost with autosub off, leaked Arabic, and a banner on live TV
   — SHIPPED (AI 0.2.445 / quickfix 0.1.487 / notification 545).** Three field
   reports, three unrelated causes, plus a fourth answered by an upgrade.
   - **One switch governed two features.** The picker's embedded rows -- both
     "[מובנה] XX" and "תרגום מובנה → עברית (AI)" -- are built from a snapshot of
     the file's subtitle streams taken at play start, before any external
     subtitle is loaded; that timing is what lets the picker tell an embedded
     track from an AI translation we loaded ourselves. The only producer of that
     snapshot sat inside `autosub_on_play`, behind its `engine_autosub` gate, so
     a user who turned OFF "auto-search and apply Hebrew on play" silently lost
     every embedded row as well. Split: `snapshot_on_play()` does nothing but
     poll and store, and runs whenever the engine is on; the search still obeys
     its setting. Verified against the field log -- zero `embedded baseline`
     lines across 10,103 lines, where the same user's earlier log has one per
     playback. The pick path never depended on that setting.
   - **The gender reference leaked into the output.** `prompt.py` gives the
     model real Arabic lines from a human translation OF THE SAME ENTRY as a
     gender oracle, and a one-shot migration forces that feature on for
     everyone. The prompt says in capitals to take "the gender and NOTHING
     else"; there was no post-processor behind that instruction, unlike the
     analogous speaker-prefix leak. `srt.strip_leaked_arabic()` closes it.
   - **HARD GUARANTEE, and the reason the function is written narrowly:** no cue
     is removed, no LINE is removed, and no line loses its Hebrew -- only Arabic
     characters are deleted from a line that also has Hebrew. The character
     classes are disjoint by construction, so the regex cannot consume a Hebrew
     character; the "did the Hebrew survive" check is a net under that, not the
     guarantee. A leak occupying a WHOLE line is deliberately left: structurally
     it is indistinguishable from an on-screen sign, and a stray visible line is
     a defect a user can report where missing dialogue is not. An earlier
     revision dropped such lines and was reverted after review found it deleting
     a genuine Arabic sign.
   - **Provenance is now a single rule.** The repair deletes text, so it must
     not run on bytes the AI never wrote -- and that was found missing THREE
     times in a row, each time after the previous fix was declared complete:
     Ktuvit rows mirrored into the pool, the Google Translate fallback (which
     writes into `cache/translated/` beside real AI output), and files of
     unknown origin saved next to the video. The cause was structural: a check
     written at a call site protects that call site. `srt.may_carry_arabic_leak`
     is now the only home of the rule and all six repair paths route through it;
     the two translator sites carry an explicit `our-own-output` marker rather
     than being exempt by assumption. Applied retroactively --
     `CACHE_RTL_FIX_VERSION` 5 -> 6 re-runs the backfill -- so subtitles already
     stored with the leak are cleaned on delivery.
   - **Nothing is re-uploaded.** Verified by AST, not by grep: no repair
     function calls `contribute`. The pool key is `sha1(source_text)`, so
     repairing the Hebrew cannot change it; the `.shared` sidecar survives the
     walk (which touches `*.srt` only); `contribute_once` returns early on that
     marker; and the Worker dedups by source hash regardless. Telegram receives
     only what `contribute` sends.
   - **A banner flashed on live TV.** The zero-duration check that recognises a
     live stream ran AFTER the overlay was drawn, so an Idan Plus channel showed
     a search that had already been cancelled -- the report was exactly "the
     search was cancelled but the message still pops up". The three existing
     live guards miss it because an IPTV plugin resolves to a plain http:// URL.
     Moved ahead of the overlay, and out of `STATE['busy']` so a live channel
     cannot block autosub for the next item played. Its grace period was widened
     5s -> 13s to match what the old ordering effectively gave, after review
     showed the move had silently narrowed it.
   - **Three-letter language tags** (spa, ger, dut, jpn, swe, cze and ~15 more)
     have matched since 0.2.402; the reporting users were on 0.2.397, so their
     upgrade is the fix. Confirmed by diffing the shipped zips: the relevant
     files are byte-identical between 0.2.397 and 0.2.444, so no coupling was
     introduced after 0.2.397 -- that recollection could not be reproduced.
   - **Packaging/privacy gate:** standalone versioned/latest/repository
     byte-identical (SHA-256
     `1fbd312e7bf062da9cfc2c977592334d447484b5c5957f06a995b2edc6535ab8`); build
     edition versioned/latest byte-identical (SHA-256
     `7721976793ed6a0715728c19d2acadff006e5a2d86074c6952ec13f1604c10be`);
     repository metadata MD5 `e7281281e47686ea9cb4683c9e39c738`. Against 0.2.444
     no package gains or loses a member and exactly eight differ. Quickfix
     0.1.487 (SHA-256
     `fbd4c9e45d773ea30068ca39f5fc1868fc3f2e2dc7211cb59fb5f76e727c8e9c`) is a
     surgical copy of 0.1.486: member order and metadata preserved, 8 of 1,933
     members differ and all 8 are inside the add-on, no new compile failures.
     The protected pool block is inherited byte-for-byte and was cross-checked
     identical across 64 shipped versions before being carried forward. No
     credential enters tracked source, `pool/worker.js` is untouched, and no
     streaming or private artifact is in scope.
   - **Validation:** 132 cue-timing and 41 snapshot checks, a 110-check release
     gate and a 19-check update-path audit that resolves every install route to
     the concrete bytes a client fetches. Five independent review rounds, one of
     which BLOCKED the release. Two lessons are now enforced mechanically: a
     function may not apply the RTL fix without also bounding cue durations and
     consulting the provenance rule, or it must carry a marker naming whose
     bytes it holds; and the pool branch's provenance argument is checked by
     EVALUATING it, after review defeated a source-text check with
     `True or <expr>` -- a regex over source can always be out-manoeuvred by
     phrasing, an assertion over a value cannot.
   - **Verified publication record (2026-07-26):** Phase 1 shipped as `861ec6b`,
     fast-forwarded onto main from `5bec4af`. Pages served the new repository
     metadata 160 seconds after the push. Every artifact a client fetches was
     downloaded IN FULL and compared byte-for-byte -- Pages `repo/addons.xml`,
     its MD5 and the advertised zip; Raw `build.txt`, `build_versions/545.txt`,
     the direct-install zip and the 33 MB quickfix. All exact at 22:15:02 Israel
     and still exact at 22:21:05 after a 363-second cache gate, with
     notification 544 deliberately live throughout. Phase 2 changed only
     `quick_update.txt` in `2f0ccb0`; notification 545 (SHA-256
     `4e160e5a8b8e96788fcf4a776e42840deaaf48b0ffe545d7a7df5bd44653f02e`) was
     live on Raw 255 seconds later and byte-exact on both Raw and Pages at
     22:31:51 after a 340-second gate, alongside a full re-verification of the
     phase-1 surface. Every component version in the note was cross-checked
     against what is actually published rather than carried over from 544. No
     Worker, credential, streaming payload or local packaging helper entered
     either release phase.
   - **Follow-ups deliberately NOT taken, recorded so they are not lost:** the
     `.google` sidecar can be evicted by `cache.prune()` independently of its
     `.srt` sibling (its mtime is set once at creation while the subtitle's is
     refreshed on every cache hit), so provenance can silently lapse for titles
     still being watched -- the fix touches cache eviction and does not belong
     inside a release. An AI translation the user saved NEXT to the video is now
     unreachable by any Arabic repair, since nothing there identifies it. And a
     line beginning with a non-RLE/PDF bidi control can strand a space inside
     the wrapper -- pre-existing in `_wrap_rtl_base_line`, unrelated to this
     release.

19. **Backend/infra follow-ups** are tracked in the maintainer's private notes,
   not here (this file is public and carries no backend or pool internals).

## What shipped 2026-07-26 → 2026-08-01 (notifications 546–563)

The numbered "Open items" list above stops at notification 545. This section
carries the record forward. Versions are add-on / quickfix / build.

### POV started fighting back (549–556)

POV self-updates independently of this build, and 6.07→6.08 moved several
things this add-on had been patching. The lessons, in order:

- **A kill switch first.** `_pov_patching_off` turns off every change this
  add-on makes to POV. It exists so a POV-side breakage is one setting away
  from being ruled out, instead of a support conversation.
- **Never ship POV's own files.** A quickfix was overwriting a newer POV with
  the copy frozen inside our package. The quickfix builder now refuses to
  include any `plugin.video.pov` member, and `tools/test_quickfix_package_scope.py`
  asserts it.
- **Our additions must never empty POV's source list.** An AIOStreams provider
  that cannot answer used to swallow the entire scrape. `provider.aiostreams`
  is a takeover in POV (`active_internal_scrapers()` returns early on it), not
  a filter, so shipping it `true` with no credentials plants "No Results" on
  every title. The full build now ships it `false`.

### The two-phase gated release (used for every notification since)

1. Commit and push the artifacts and `wizard/assets/build_versions/<N>.txt`,
   leaving `quick_update.txt` at the PREVIOUS number.
2. Fetch every URL a real Kodi client would fetch — Raw and Pages both — and
   compare **byte for byte** with what was built. Confirm the live note still
   reads the previous number.
3. Only then commit the notification bump.

Gate scripts live in the maintainer's scratchpad, one per release. Pages lags
Raw by a few minutes; poll rather than assume.

### Releases

| Version | What it fixed |
| --- | --- |
| 0.2.449–0.2.455 / qf 0.1.491–0.1.497 | POV kill switch; AIOStreams no longer swallows the scrape; quickfix stops shipping POV's files; subtitle encoding converted to UTF-8 however it arrived; cp1255 fallback accepted only when it yields Hebrew; one congestion event no longer punished six times |
| 0.2.456 / qf 0.1.498 / build 0.1.103 | MDBList home tiles appear on the first restart |
| 0.2.457 / qf 0.1.499 / build 0.1.104 | `provider.aiostreams` shipped `false`, so a fresh install no longer starts with the takeover armed |
| 0.2.458 / qf 0.1.500 | POV names the source it could not resolve instead of failing silently |
| 0.2.459 / qf 0.1.501 | AI subtitle text cleaned where it is CREATED, not only on delivery |
| 0.2.460 / qf 0.1.502 | POV 6.08 scraper/debrid timeout floor |
| 0.2.461 / qf 0.1.503 | Kodi's own Hebrew strings self-heal; 43 dropped settings; two revived POV patchers; MDBList QR title |
| 0.2.462 / wizard 0.1.36 / qf 0.1.504 / build 0.1.105 | FENtastic widget includes; DialogSeekBar; POV reads the shortcut folders the build ships |

### Things worth not rediscovering

- **`<control>` and add-on settings.** `AddonSettings.cpp` registers exactly
  nine control types (`toggle spinner edit button list slider range title
  colorbutton`). `label` is NOT among them for add-on settings, so
  `CreateControl("label")` returns nullptr and `Setting.cpp:156` drops the
  whole setting. `visible="false"` is only read by the version-0 parser. The
  correct way to declare a hidden marker setting in a `version="1"` file is
  `<level>4</level>` with no `<control>` — `SettingLevel::Internal`, which is
  Kodi's own idiom. Level never gates get/set from Python. This is what the 43
  dropped settings were.
- **POV serves settings from a cached blob.** Every read goes through the
  `pov_settings` window property. A cross-add-on write is invisible until that
  property is cleared — `xbmcgui.Window(10000).clearProperty('pov_settings')`.
  Any patcher that writes a POV setting must clear it and read back.
- **POV 6.08's `ExternalManager.results()`** spends `scrapers.timeout.1` on TWO
  sequential phases (providers, then debrid cache checks), and `final_sources`
  is populated only inside the loop over COMPLETED debrid threads. One slow
  debrid therefore discards every torrent found. `tpe.shutdown(False)` is
  non-blocking, so the late threads still write to the providers cache — which
  is why the second attempt is instant and successful. Three debrid backends
  also read the same setting as their per-request HTTP timeout.
- **Patchers go stale silently.** Several matched an exact shape POV later
  reformatted; they reported `unmatched` and did nothing for months. There is a
  sweep script in the scratchpad that runs every patcher against a fresh POV
  and prints a STALE count; run it whenever POV ships a new version. Anchor on
  shape or adjacency rather than a pinned line where possible.
- **Kodi tolerates a raw `&` in skin XML.** It does not tolerate a missing
  closing tag — that rejects the whole window.
- **`navigator.db` is stored as Python repr, and POV reads it with
  `json.loads`.** Both readers swallow the failure: shortcut folders render
  empty and `get_list` returns None, which makes `get_main_lists` rebuild the
  menu from POV's defaults over the build's. Neither logs anything.
  **Do not convert the database.** Six patchers in this add-on match on the
  repr spelling, and one of them rewrites its row back to repr on the next step
  of the same startup, undoing the conversion permanently. The fix belongs on
  POV's read path — `pov_navigator_read_patcher` adds an `ast.literal_eval`
  fallback to both readers and writes nothing.
- **POV source patches do not take effect in the session that applies them.**
  POV declares `<reuselanguageinvoker>true</reuselanguageinvoker>` and has
  already imported its modules by the time the repairs run. `pov_reload`
  exists for this, but `reload_if_patched()` is called earlier in `main()` than
  `_run_build_startup_repairs()`, which is where every `note_patched()` lives —
  so it has never fired. In practice this costs nothing, because the quick
  update that delivers the patch restarts Kodi anyway. Left alone deliberately;
  changing it would start cycling POV mid-session for every patcher at once.
- **The Wizard's extractor and "fresh install".** `extract.all(..., ignore=...)`
  — `ignore is not None` does NOT mean "quick update". `startup.py`'s
  fresh-build auto-install passes `ignore=True` as well, to bypass the skip of
  the Wizard's own files. A preserve rule keyed only on `ignore` therefore
  fires on a brand-new install, where there is nothing to preserve. Preserve
  rules must ALSO require the file to already exist on disk.
- **A Wizard fix does not apply on the quick update that delivers it.** Python
  does not reload a module because its bytes changed on disk, so the run that
  writes the new `extract.py` still uses the old one. Anything that must repair
  an already-broken device needs a second mechanism — here, the add-on
  restoring the files at service startup.
- **Package releases: re-run Deploy GitHub Pages LAST.** The APK download links
  are served from the `gh-pages` branch, not from the release. See
  `APK_RELEASE.md`.

### What shipped 0.2.474 / wizard 0.1.41 (Account Manager + the search switch)

Four changes that only make sense together, which is why they went out in one
release rather than one skin at a time:

1. POV's "חיבור שירותים" screen authorises the debrid accounts through Account
   Manager, so one connect reaches every add-on. See the Account Manager
   section above for the three rows that deliberately stay POV-native and why.
2. Account Manager installs itself once on every device, existing installs
   included, because (1) silently degrades without it.
3. A POV/Umbrella search switch on all four skins at once. See the
   search-engine switch section above.
4. Two home tiles ("מנוע החיפוש", "Umbrella") on FENtastic/Estuary/NOX and the
   matching two rows in AF3's submenu + power menu, all gated on Umbrella
   being installed.

Things worth not rediscovering from this batch:

- **A favourites tile that exists only in the user's file is lost on the first
  skin switch.** `update_favourites_xml_file()` copies
  `media/builds_favourites_xml/<skin>/favourites.xml` OVER
  `userdata/favourites.xml`, and the sidecar then reads the loss as a
  deletion and never restores it. The quickfix builder cannot reach `media/`
  (it only replaces members under `addons/service.subtitles.kodipovilai/`), so
  `_seed_umbrella_tiles()` writes the tiles into the SEEDS from the add-on
  instead. Any future tile needs the same treatment.
- **AF3 does not use Kodi favourites for its home**, so a favourites tile is
  invisible there. AF3's equivalent is a row in
  `skinvariables-shortcut-homesubmenu.json` / `-powermenu.json`, delivered by
  the 3-way merge in `af3_home_patcher` (new canonical rows are appended for
  existing devices; user deletions are never resurrected).
- **A "seen" sidecar key means the tile reached the DISK.** Stamping it inside
  the inserter, before `ensure_patched()` writes the file, turns a failed
  write into a permanent skip. Same rule as the "done marker" one above.
- **A gated tile has TWO ways into favourites, and both need the gate.** The
  per-tile inserters check `_umbrella_installed()`, but
  `_install_canonical_home()` — the near-empty-home rescue — writes the whole
  fixture VERBATIM, so it shipped the Umbrella tile to devices with no
  Umbrella. Anything conditional added to the fixture must also be dropped in
  `_drop_umbrella_tiles()`'s equivalent for that condition. The rescue path is
  easy to forget because it only fires on a broken install.
- **An auto-install marker records "we did this once", not a version.** Keying
  `acctmgr_auto` on `ACCTMGR_PACK_VERSION` looks tidier and is wrong: the next
  version bump stops matching on every device and forces a reinstall,
  including on somebody who removed the add-on on purpose — the one thing the
  marker promises not to do. Keeping the pack current is not that function's
  job; Account Manager updates itself from its developer's repo.

### What shipped 0.2.475 (the Hebrew match badge in Umbrella, and two guards)

`umbrella_subtitle_match_patcher` is the port of `pov_subtitle_match_patcher`
to Umbrella's own source window, sharing `he_sub_match` so a title warmed from
either add-on shows its badge in both. It ports almost line for line because
Umbrella's window has the same shape as POV's down to the loop signature, and
`umbrella.size_label` is the first token of the info line in all twelve layout
variants of `source_results.xml` -- so one property carries the badge on every
layout, with no skin XML touched.

Three lessons, all of which cost a round of rework and none of which are
Umbrella-specific:

- **A per-row try/except in the host add-on is NOT a backstop for injected
  code.** It drops the ROW. Our badge call is identical for every row, so
  anything that makes it raise once makes it raise for all of them and the
  source list comes back EMPTY -- which reads as "the scrapers broke". POV's
  wrapper is `except: pass`, so it does not even log. Both patchers now
  compute the badge inside a guarded `_sm_pfx`, and the four failure modes
  (label_prefix arity change, label_prefix raising, module missing, import
  failing) all yield an empty badge instead. Any future injection into a
  third-party loop needs its own guard, not the host's.
- **Anchor a revert on MARKERS you control, never on the text of the block's
  own body.** The old body-anchored regex could not match a malformed block,
  and `.*?` then ran to the NEXT block's body text and deleted the upstream
  code in between. It also meant changing the body silently broke the revert,
  leaving the old block in place while the loop anchor cheerfully inserted a
  second one. Both patchers now use START/END markers with a middle that
  cannot cross another marker of ours.
- **Migrating a shipped patcher means the OLD form has to stay
  removable.** Every device carries a v6 block, and v6 has no END marker, so
  the legacy body-anchored regex is kept purely to remove it. v7's fallback
  line deliberately continues past `set()` so the legacy pattern is
  structurally unable to match a v7 block and half-remove it.

Also in this release: the four MDBList writes into POV's settings -- the last
bare cross-add-on `setSetting` calls in the add-on -- now go through
`addon_settings_safe`. Connect keeps two calls on purpose, because one call
would write all four keys before reporting that the token failed, which is the
"watched-status points at MDBList with no key" state the gating exists to
prevent.

### The Hebrew keyboard layout can vanish from `locale.keyboardlayouts`

Field report: the on-screen keyboard offered only English QWERTY, in POV, in
Umbrella and in Kodi's own search alike -- so a Kodi setting, not an add-on.
Settings -> Interface -> Regional -> Keyboard layouts had only English ticked,
while **Hebrew QWERTY was still present in the list to tick**. Ticking it by
hand worked immediately.

That "still present" is the whole diagnosis: the layout exists on the device,
the SETTING had lost it. Which also rules out the two things it looked like.
It was reported right after using the new search-provider tile, and that tile
does not write a single Kodi setting -- it writes skin files and calls
`ReloadSkin()`. And the quickfix ships no `guisettings.xml` at all, so an
update cannot have overwritten it. The timing was coincidence.

The real defect was ours and it was the RECOVERY, not the cause: both keyboard
seeds lived inside `hebrew_build_ui_patcher`'s once-per-device
`_prefs_already_seeded()` block, so once the layout went missing for any
reason nothing would ever put it back, and the user simply could not type
Hebrew. That block was conflating two different things:

- **which** layout is active is a preference -> still seeded once, hands off
  after that;
- **whether** the Hebrew layout is available at all is infrastructure on a
  Hebrew build, the same category as the skin-strings repair that already runs
  every start -> now checked on every startup and restored if absent.

`_ensure_hebrew_layout_available()` is additive: it appends Hebrew only when
missing and leaves the order, the active layout, and any layout the user added
alone. The old seed wrote a fixed two-item list, which silently dropped a
third layout a user had chosen. It also **reads the value back** and only
claims success when Hebrew really landed -- Kodi validates a setting against
the options that exist right now and silently keeps the old value otherwise,
the same trap as `CAddonSettings::Load` one level up, so the write can
"succeed" and change nothing.

Cause of the original loss: still unproven. The likeliest mechanism is a
startup ordering race -- Kodi loads settings before the language resources
that provide keyboard layouts have registered them, finds a stored value that
is not (yet) a known option, prunes it, and writes the pruned list back on
exit. That fits every observation, and it is also why the repair belongs in
our service: it runs long after the add-ons are up, so by then the layout is a
valid option and the write sticks. If it recurs, the WARNING now names which
of the two cases it is.

#### Undeclared settings DO persist — an old note here said otherwise

Written down because this repo asserted the opposite for months, and a
validator went and read Kodi's own C++ to settle it.

`Addon.setSetting()` on an id that is NOT in the add-on's settings.xml does
not silently vanish. `CAddon::UpdateSetting()` creates a hidden internal
`CSettingString` through `AddSettingWithoutDefinition()`, registers it in the
same settings-manager tree as any declared setting, and `SaveSettings()`
serialises the whole tree with no "was this declared" filter -- so it reaches
disk. `CAddonSettings::Load()` does the mirror image on the way back in,
recreating an unknown id it finds in the stored values. Hidden markers written
this way survive a restart on Kodi 19+.

Two things this does NOT contradict, and they are the ones that actually bit:

  * Kodi silently drops a `setSetting` into ANOTHER add-on for an id that
    add-on does not declare. That is a different code path and it is real --
    it is why Account Manager's writes of `mdblist.api` and `resume.source`
    into Umbrella are no-ops.
  * `CSettingString` still rejects an EMPTY `<default>` unless the setting
    declares `<allowempty>true</allowempty>`, which is what made 27 of our own
    settings log an error on every settings load.

So: declare markers for consistency and so the next reader can find them, not
because an undeclared one would be lost. About ten markers in this add-on are
still undeclared (`_ktuvit_on_v4`, `_builtin_engine_rollout_v2`,
`_pool_share_force_v1` and friends); they work, and they are a tidiness item
rather than a bug.

### What shipped 0.2.476 → 0.2.482 (notifications 579–585)

| Version | What it fixed |
| --- | --- |
| 0.2.476–0.2.477 / qf 0.1.521–0.1.522 / note 580 | The Hebrew keyboard layout restores itself whenever it goes missing; the "send log" tile points at the Wizard's own uploader |
| 0.2.478 / qf 0.1.523 / note 581 | Umbrella's Hebrew search (first attempt); the POV discover patcher's `tmdb_api.py` anchor repaired |
| 0.2.479 / qf 0.1.524 / note 582 | The Hebrew search fix made to actually reach the device (CRLF); Kodi's 20s playlist timer stops raising "playback failed" on a deliberate cancel |
| 0.2.480 / qf 0.1.525 / note 583 | Umbrella's MDBList routed to Umbrella's own authorisation; AM's settings window stops landing on top of our question |
| 0.2.481 / qf 0.1.526 / note 584 | POV's search-history crash (maincache column order surviving a 5.x upgrade); one MDBList authorisation for POV and Umbrella |
| 0.2.482 / qf 0.1.527 / note 585 | One Trakt authorisation for both; Umbrella actually READS from the connected service; the season list opens on a poster view; Hebrew season names; 27 settings stop erroring on every settings load |

#### Test against what SHIPS, not what upstream publishes (0.2.478 → 0.2.479)

The Hebrew-search fix shipped as a complete no-op and the user had to report
the same bug twice. The patcher anchored on `^class TMDb:\n`, which is what
upstream Umbrella looks like — but the pack this build ships carries
`indexers/tmdb.py` and `windows/source_results.py` as **CRLF** while
`modules/sources.py`, `menus/movies.py` and `menus/tvshows.py` are LF. In
Python's MULTILINE mode `$` matches before `\n`, never before `\r`, so the
anchor could not match the file on any real device.

Two rules came out of it, and both have caught later bugs:

- Every anchor is now built from the file's own detected EOL, and every
  patcher harness runs a CRLF copy as well as an LF one.
- `\r?\n+` is wrong for "one or more newlines": it eats one CRLF and then
  stalls on the `\r`. It has to be `(?:\r?\n)+`. That form was already
  wrong in a revert path nobody had exercised.

#### Kodi's own dialogs and settings (0.2.479, 0.2.481, 0.2.482)

- **"Playback failed" on a deliberate cancel.** `PlayListPlayer.cpp` raises it
  when a run of failed plays exceeds `playlisttimeout` (default 20s), and
  `Reset()` does NOT clear `m_iFailedSongs` — so opening a source list, waiting,
  and backing out counted as a failure and popped a dialog. Merged
  `<playlisttimeout>0</playlisttimeout>` into `advancedsettings.xml`. Detection
  parses the XML tree: a validator found that a substring test would read a
  COMMENTED-OUT example as "already set", forever.
- **Kodi silently drops `setSetting` for a setting the target add-on does not
  declare.** This is why Account Manager's writes of `mdblist.api` and
  `resume.source` into Umbrella are no-ops — neither exists in Umbrella's
  settings.xml. Verify every id against the real file before writing it.
- **`CSettingString` rejects an EMPTY `<default>`** unless the setting also
  declares `<constraints><allowempty>true</allowempty></constraints>`. 27 of our
  hidden marker settings had an empty default without it, so Kodi logged an
  error on every settings load — roughly once a minute, since constructing
  `xbmcaddon.Addon()` re-validates the whole file.

#### SQLite TEXT affinity and POV's search history (0.2.481)

Search screens crashed with `'int' object is not iterable` on any device
upgraded from POV 5.x: the `maincache` table kept the 5.x column order while
6.x writes positionally, so everything saved afterwards went into the wrong
column. TEXT affinity converts numbers to strings on the way in, and TEXT
always sorts above INTEGER, which is what made it look like a sorting bug.
`pov_maincache_schema_fix` rebuilds the table in 6.x order, copying only rows
whose `expires` is genuinely an integer. It refuses to run when the file is
absent — `sqlite3.connect()` creates an empty database, and a zero-byte
`maincache.db` in POV's profile is a new way to break POV.

#### One authorisation, two add-ons (0.2.481 MDBList, 0.2.482 Trakt)

Both services were being connected twice, once in POV and once in Umbrella.
They are not the same problem:

- **MDBList.** An access token authenticates the USER; any client may present
  it. So POV's token is handed to Umbrella as-is. Umbrella is deliberately
  given NO refresh token, because a refresh token is bound to the client that
  issued it and Umbrella posts its own client id. POV owns the refreshing.
- **Trakt.** A token is bound to the APPLICATION: every call carries a
  `trakt-api-key` header and Trakt rejects a token issued to a different app.
  Umbrella supports exactly this as a documented feature — the "Use Custom
  Trakt API Keys" switch — so Umbrella is pointed at POV's Trakt application
  through its own setting. `trakt.authed.clientid` must be set too, or
  Umbrella compares it against `traktClientID()`, decides its own credentials
  are foreign, and drops them.
- **Trakt refresh tokens are single-use.** Once Umbrella runs as POV's
  application it refreshes on its own and rotates the pair. Pushing POV's older
  copy back over it would leave Umbrella holding a retired refresh token, and
  its next refresh clears the whole authorisation and tells the user to
  re-authorise. So when Umbrella's token differs and expires LATER, POV is the
  stale side and we adopt Umbrella's pair instead.

#### Connecting a service is not the same as USING it (0.2.482)

Umbrella showed every episode unwatched while POV showed the ticks, on a
device where everything said "connected". `indicators.alt` (watch history) and
`scrobble.source` (scrobble and resume) are each a single CHOICE — 0 local,
1 Trakt, 2 Simkl, 3 MDBList — and Umbrella ships both at 0. Connecting a
service never changes them.

`umbrella_watch_source` claims them, and the rules are all scar tissue:

- **Once per key**, so somebody who puts one back to Local keeps it.
- **Only from the shipped 0.** A validator caught an earlier version reversing
  a deliberate answer: Umbrella's own `traktAuth()` ASKS about indicators, and
  declining leaves the setting at 0, indistinguishable from never-asked. Only
  claiming from 0 is what protects an answer already given.
- **Not gated on "first connect".** That was the first shape and it only ever
  helped a device connecting for the first time — everybody already connected,
  which is everybody who reported the missing ticks, would have kept Local.
- **The marker records WHAT we wrote, not merely that we wrote.** MDBList is
  preferred over Trakt, and ordering the two calls is not enough: the instant
  trigger on POV's Connect Services screen fires the MDBList mirror alone,
  from its own process, while the timer fires both. So MDBList may replace a
  Trakt value **of our own making**, and the preference holds whichever service
  was connected first. A Trakt value we did not write is recorded as "wrote
  nothing" and is never replaced.
- **Settle on the no-write path too, and merge rather than overwrite.** The
  no-write path is taken on almost every pass; leaving it unrecorded meant the
  "once" rule never took hold. And a merge that let "not ours" win over a
  concrete value would lose a claim permanently.

#### Per-season posters were never the problem (0.2.482)

Reported as "works in NOX, not in Estuary or FENtastic". It works everywhere:
POV gives every season its own TMDb poster on `poster`, `icon`, `thumb`,
`season.poster` AND `tvshow.poster`; TMDb returns a distinct poster per season
under `language=he` (checked live against six shows, none returns null); and
Estuary, FENtastic and NOX resolve posters through a byte-identical
`PosterVar`, while Arctic Fuse 3 prefers `ListItem.Art(poster)` outright.

The screenshot settled it: the screen was FENtastic's Advanced List (630) — a
column of season labels beside one landscape still, with **no poster anywhere
in the layout**. A poster the layout never draws is indistinguishable from a
poster that is missing.

`pov_seasons_view_seed` therefore writes POV's OWN `views.db` row — the same
row POV's "Set View" writes — with that skin's poster view. Points worth
keeping:

- POV's `views` table is `(view_type TEXT, view_id TEXT, UNIQUE(view_type))`
  with **no skin column**, so one number is applied in every skin and the same
  number means different layouts. 51 is Poster in Estuary, FENtastic and NOX
  (all three inherit Estuary's numbering); Arctic Fuse 3 numbers its own and
  wants 512. The marker therefore records what we wrote **per skin**.
- POV loads `views.db` into window properties exactly once, from its own
  service at Kodi start, and `set_view_mode()` reads only the property — so the
  row has to be published to `Window(10000)` as well, or it sits unused until
  the next restart.
- Forced once per skin over whatever is there, on the maintainer's
  instruction: a row already present is not evidence anybody chose it, since
  the screen had been landing on numbers from other skins. After that one say,
  a view the user moves to is theirs.
- POV's "Reset All Views" does `DELETE FROM views` **and** clears every `pov_*`
  property without changing the skin, so the per-session memo that avoids
  reopening the database has to compare the window property too, not just the
  skin.

#### Four validator passes, seven blockers, four of them regressions

The 0.2.482 batch went through four adversarial passes. Three of the four
rounds of fixes introduced a fresh blocker of their own:

- gating the kill switch in the keeper loop, while leaving the one path that
  writes POV settings ungated;
- adding a memo to save database opens, which disabled the feature's own
  self-heal;
- recording claims only after a successful write, so a partial write lost the
  claim.

The common shape in every one: **inferring from one side of an interface
without checking the other.** Budget for a pass per round of fixes, not one
pass per feature.

#### 0.2.483 / qf 0.1.528 / note 586 — MDBList recovers from a 401

Field report: "MDBList session expired — please re-authenticate in settings"
recurring, cleared only by reconnecting the account. The log shows POV itself
getting `401 .../sync/last_activities` twice within eight seconds of startup,
from two different POV sync threads — so it is POV's token being rejected, not
just the copy Umbrella holds.

POV refreshes on a CLOCK CHECK only (`mdbl_expires()`), and `call_mdblist()`
treats a 401 as just another `RequestException`: it logs and returns None.
Once the stored token stops being accepted while `mdblist.expires` still looks
fine, there is no way back — every call fails, the sync monitor backs off half
an hour, and only reconnecting by hand helps. Umbrella has had the reactive
refresh-and-retry from the start; POV never had it.

`pov_mdblist_reauth_patcher` adds it, deliberately NOT on the API-key path
(a `mdblist.token` with no `mdblist.refresh` beside it is an API key and there
is nothing to refresh). It also serialises `mdbl_refresh()` behind a window
property: MDBList rotates the refresh token, and POV starts two sync passes
seconds apart at every startup, each calling `mdbl_expires()` — so two
refreshes with the same rotating token is the normal case here, and the loser
can leave a token stored that the server has already replaced.

`umbrella_mdblist_token_patcher` handles the popup, which was ours: Umbrella
captures its Authorization header once at import, and we deliberately leave its
refresh token empty, so after POV rotates it keeps sending the old token and
has nothing to renew. Its refresher now re-reads `mdblist.token` first and
adopts a newer one — all the common case needs, since somebody else did the
refreshing. The dialog is dropped: in this build MDBList is connected in POV,
for both add-ons, so "re-authenticate in settings" points at a screen that
cannot fix it.

#### 0.2.484 / qf 0.1.529 / note 587 — Trakt recovers from a 401 too

The same defect, in the file next door, found because the MDBList fix landed on
a real device and the log showed `TraktMonitor - Failed. Error from Trakt` two
lines above `MDBListMonitor - Success`. `trakt_expires()` refreshes on a clock
check only and `call_trakt()` swallows a 401 as a `RequestException`, so a
rejected token is permanent there too. `pov_trakt_reauth_patcher` is the
sibling of the MDBList one — same five-anchor discipline, same cross-thread and
cross-process refresh lock, same refusal to touch the API-key-shaped state
(empty `trakt.refresh`).

Two things about `call_trakt` are NOT true of `call_mdblist`, and both cost a
blocker:

- **It recurses through a POP.** `if isinstance(path, dict): return
  call_trakt(str(path.pop('path')), **path)` empties the CALLER's dict. After
  the rename that inner call lands on the wrapper, so the pop happened once and
  the outer retry re-entered with an empty dict: `KeyError: 'path'`, 3/3 runs,
  out of a background sync thread, on exactly the revoked account the patch
  exists to rescue. The wrapper now resolves the dict form itself, on a copy,
  before any retry logic. Documented in the header as "harmless" for a whole
  round first — a comment asserting a behaviour nobody executed.
- **It is handed to a ThreadPoolExecutor** (`executor.map(call_trakt, args)`),
  which is why the status flag is thread-local rather than a module global.

The other blocker was in `service.py`, not the patcher: both `ensure_patched()`
calls shared one `try`, so an exception out of the MDBList patcher skipped the
Trakt one entirely — reproducing this round's own field symptom from a hiccup
on the other side of the pair, behind a WARNING that read as if it were only
about MDBList. **One `try` per patcher.** Anything that applies a list of
independent repairs in a loop wants the same rule.

### Why every update closed Kodi, and what replaced it (2026-08-12)

The quick update force-closed Kodi on **every** release. On Android — where
most of these devices are — nothing brings Kodi back, so each release cost
each user a manual relaunch. The reason turned out not to be the files:

```
plugin.video.pov               <reuselanguageinvoker>true</reuselanguageinvoker>
plugin.video.umbrella          <reuselanguageinvoker>true</reuselanguageinvoker>
service.subtitles.kodipovilai  <reuselanguageinvoker>true</reuselanguageinvoker>
```

Kodi keeps **one Python interpreter alive per add-on and reuses it**. A module
already imported stays imported, so editing POV's `.py` on disk changes nothing
until that interpreter is destroyed. Our patchers already delete the target's
`.pyc`; memory simply beats disk. Force-closing Kodi was the blunt way to drop
those interpreters.

Disabling an add-on destroys its invoker, so they can be dropped one at a time:
`UpdateLocalAddons()` → cycle our own service (it restarts from the NEW code and
re-runs every third-party patcher) → **wait for it to report a finished pass** →
cycle the add-ons it patched → `ReloadSkin()`.

**The wait is on a VERSION, not a flag**, and that is the part worth keeping. A
boolean cannot distinguish "the new service finished" from "the old service,
still running from before the update, finished its own pass" — and acting on
the second reloads POV against half-written files. `service.py` publishes its
own version to a window property only after every step has been through; an
aborted pass deliberately publishes nothing, and the property is cleared at the
start of each pass so a stale value from the previous instance cannot satisfy a
waiter.

Anything that does not fully take falls back to the force-close, so the worst
case is unchanged. An add-on the user disabled by hand is left alone rather
than silently re-enabled.

**This does not take effect on the release that ships it.** The new wizard code
arrives in the package, but the update is executed by the OLD wizard, which
does not know about it. That is inherent to changing the update mechanism
itself; the quiet behaviour starts one release later.

**Still open on the update flow:** ask instead of force-closing when a restart
IS genuinely needed (with a countdown, defaulting to No); auto-relaunch on
Windows/Linux only — the code is already in `restart_kodi()`, commented out —
because Android, Android TV, iOS and webOS have no reliable way to relaunch
Kodi, which is exactly why "don't quit" is the answer rather than "come back".

### The watched tick in the Poster view (2026-08-12)

Reported as "no tick on the poster". Present in every other view — List,
Shift, Wall, InfoWall, WideWall, WideInfoWall — and missing only in the
build's default, in POV and Umbrella alike, for movies and for seasons.

Three explanations were ruled out **before** touching anything, and the order
matters because each was cheaper than the next:

- **Not the data.** POV computes watched state in ONE place
  (`menus/movies.py` → `get_watched_status_movie`), and that same function
  feeds the home widget, which does show the tick.
- **Not a cache.** A full Kodi restart changed nothing.
- **Not POV-versus-Umbrella.** The skin draws every video list, whichever
  add-on produced it — which is also why the same fix covers both.

The cause: `skin.fentastic`'s Poster view builds its tiles from
`InfoWallMovieLayout`, and that include carries no watched control at all. It
exists only in `BigInfoWallMovieLayout`, which the other views use.

The control is inserted into the VIEW, not into the shared layout. One edit
there instead of four would draw a **second** tick in every view that already
has one, because several stack both layouts. `skin.povil.nox` is left alone —
its Poster view is already correct — and a skin with no verified recipe is not
patched on a guess: a wrong coordinate ships a tick floating over artwork on
every device. Estuary and Arctic Fuse 3 still need their own recipe.

The patcher parses the XML before writing. Kodi silently refuses a skin file it
cannot parse and the user gets an empty screen with nothing in the log pointing
at us, so a bad edit must never reach disk.

### Account Manager Lite: what its author confirmed (2026-08-11)

Answers to the report filed against AM Lite 1.1.5a, verified against its
shipped code rather than taken on trust:

- **The force-close after `traktAuth`/`traktReSync` is deliberate and stays.**
  AM rewrites the Trakt handling inside the add-ons it supports and bypasses
  their own authorisation, so they must restart to rebuild their Trakt
  databases; a dialog could be dismissed or stolen by another add-on, a hard
  exit cannot. Reasonable for AM — but not something a build's main connect
  screen can do, which is why Trakt stays on POV's native connect here.
- **`control.updates_off()` is NOT permanent**, which is what an earlier
  comment in this repo claimed. `startup.py run_addon_updates()` calls
  `autoupdate_on()` and then `UpdateAddonRepos()`, so add-on updates come back
  on the next start; it only parks them until AM's own startup work is done.
- **Declining the "create your sync list now?" prompt falling off the end of
  its branch** was accepted as a bug and is fixed for their next release.
- The "no sync list" check is a safeguard for an incomplete revoke; once Trakt
  is authorised the button becomes "Edit Sync List".

Still worth watching, with the trigger now pinned down. Every startup AM logs
`No Trakt auth found - resetting services to defaults` (because Trakt is on POV
here, not AM) and walks `restore default service` / `restore default API keys`
for Umbrella and POV. Every one of those `no changes needed` lines is a correct
no-op **while AM Lite's own master `trakt.token` is empty** — a third,
independent store from POV's `trakt.token` and Umbrella's `trakt.user.token`,
and it only fills if somebody runs Account Manager's OWN "Connect Trakt" flow.

The moment it is not empty, AM's `ensure_defaults()` flips to "authed" and the
next startup's `trakt_sync.Auth().trakt_auth()` overwrites POV's
`trakt.client_id/client_secret/token/refresh/expires/trakt_user` and Umbrella's
`trakt.user.token/refreshtoken/token.expires/user.name/authed.clientid/isauthed`
with AM's own app's pair — while leaving `trakt.clientid` and
`traktuserkey.customenabled` (our custom-app switch) in place, which is exactly
the client-id/token mismatch Umbrella's own `re_auth()` treats as foreign
credentials and clears. So: connecting Trakt inside Account Manager on a device
that already has it through POV is the one action that breaks this arrangement.
Support note, not a code fix — nothing in this build's own flow does it.

### Known, deliberately not fixed

- POV's `menu_editor.shortcut_folder_add_item` does
  `list_items = json.loads(choice_list)` with no `try/except`, on the raw text
  from `get_shortcut_folders()`. Every shortcut folder the build ships is repr,
  so "Add to a Shortcut Folder" from any Trakt/TMDB/MDBList/Discover context
  menu raises. POV is inconsistent with itself here — `navigator.py`'s folder
  list uses `eval()` on the same text and works. Pre-existing, unreported by
  users, and out of scope for the release it was found in.
- The `.google` provenance sidecar can be evicted by `cache.prune()`
  independently of its `.srt` sibling, so provenance can lapse for titles still
  being watched. The fix touches cache eviction.
- **A subtitle-match SETUP block whose END-marker LINE is lost, while its start
  marker and body survive, cannot be removed by either revert.** The
  END-anchored form has nothing to anchor on, and the legacy form is
  structurally unable to match a v7 block -- which is the same property that
  keeps it from half-removing a healthy one. `ensure_patched()` then inserts a
  second SETUP in front of the orphan. Left alone on purpose: it needs damage
  from OUTSIDE this code (our own write is atomic, proven by failure
  injection), the result compiles and works, and it stabilises at two blocks
  rather than growing -- the cost is the setup running twice per window open.
  The fix would be a third regex bounded by the loop line, which is more risk
  on a migration path than the defect it removes. What WAS fixed is the
  reporting: that run used to return `'unchanged'` because `MARKER in original`
  is a substring test rather than a statement about what happened, so a real
  write was invisible in the log and POV's reload was skipped. A status has to
  describe what the run did.

## The "last ten updates" tile, and six rounds of getting it wrong

The tile itself is three lines of XML. Deciding whether it may be re-seeded
took six review rounds, every one of which found something real, including in
the fix from the round before, and twice including in the round that had just
declared itself done. Worth reading before touching
`recent_updates_tile_patcher.py`.

The problem: the wizard's `update_favourites_xml_file()` copies a static
per-skin `favourites.xml` over the user's own on every skin switch, so the
tile disappears through no fault of theirs and must come back. A tile the user
deleted must NOT. From `favourites.xml` alone those two are indistinguishable,
and five designs proved it (the module header lists them).

The answer is that the writer knew all along: the wizard leaves a MARK every
time it replaces the file, and the patcher records that mark when it seeds.
Mark changed -> the wizard did it -> restore. Mark unchanged -> the user did ->
never again.

It was a COUNT for three of those rounds, and the count is what rounds four and
five killed. To increment a count you first have to read it, and every way of
reading it wrong still yields a perfectly ordinary number -- just a smaller
one. A corrupt copy read as nothing, so the wizard rewrote a device's count of
4 as 1, healing the damage into a clean and wrong number before the reader
could ever notice it was damage; the reader, comparing against the 4 it had
recorded, watched the number climb back past 4 over the next few skin switches
and concluded that the user had deleted a tile the wizard itself had removed.
A uuid4 mark is written and never read, so nothing can rewind it, and the only
question ever asked of it -- "is this still the mark I saw?" -- has no
wrong-but-plausible answers. What it gives up is that a count BELOW its own
snapshot was provably impossible and therefore catchable; a mark restored to an
earlier value just looks like a mark. That needs `addon_data` rolled back for
the mark but not for the record beside it, which no Kodi button does and no
backup tool does by halves -- against corruption, which an SD card does on its
own.

What the rounds added, each of them load-bearing:

  * BOTH facts are kept in BOTH add-ons' `addon_data`. Kodi's per-add-on
    "Clear data" button wipes exactly one folder and exists on every add-on,
    so a single copy of either the record or the count could be taken by one
    click, and losing the count reads as "never replaced" -> every wizard
    removal becomes a user deletion.
  * The record is written BEFORE the tile and only becomes `offered` once the
    tile is really in the file. An absent record has to mean "never offered"
    for a first run to seed at all, so a tile must never be able to outlive
    its record. `seeding` is what tells a power cut apart from a deletion, and
    the retry is BOUNDED -- an unfinished seed that can never finish would
    otherwise undo every deletion the user makes, forever.
  * Seeding requires EVERY copy to land. One copy is not the mechanism with a
    scratch on it, it is the mechanism with its redundancy gone.
  * PRESENT-BUT-UNREADABLE IS ITS OWN ANSWER, everywhere, and every place that
    collapsed it into one of the other two cost somebody their tile. The mark
    reads as absent / a value / damaged; the record reads as absent / legible /
    damaged. A copy that cannot be read gets no vote while one that can
    disagrees -- the version that let a single corrupt copy outvote a healthy
    one saying "offered" needed nothing but ordinary flash wear, and latched
    the moment it happened.
  * The two copies are compared AS A PAIR against the pair that was recorded,
    never copy against copy. A copy whose write once failed sits there holding
    an older mark forever, and against a single recorded value that stale copy
    reads as "different" -- which is the reading that puts a deleted tile back.
  * When no copy of the mark can speak, the snapshot is RE-BASELINED to what it
    says now and the anchors decide this one start -- and their verdict is NOT
    recorded. A recorded deletion is permanent: it is the first thing every
    later start checks and it never looks at the mark again. That weight
    belongs to a fact, not to a guess read off favourites that a skin seed may
    itself contain. Re-baselining is what stops damage keeping the question
    open forever, so it becomes one start of "cannot tell" instead.
  * THE FILE OUTRANKS THE RECORD. `ensure_patched` checks whether the tile is
    actually in `favourites.xml` before it checks whether the record says the
    user removed it. A tile that is present cannot be a tile they removed, and
    asking the record first meant an unreadable one returned "removed" with the
    tile plainly on screen -- and the repair that could have fixed the record
    while the tile was there to prove what it should say was unreachable from
    that moment on.
  * THE WIZARD MARKS BEFORE IT COPIES, the same order the reader uses for its
    own record and for the same reason. The two steps are not atomic: a power
    cut between them, or an ENOSPC that the mark writer swallows by design
    while the big copy has already landed, leaves the file replaced with
    nothing to say so -- and that is unrecoverable. Reversed, the leftover is a
    mark with no replacement behind it, and the tile is still in the file, so
    the reader re-baselines onto it before it can be read as a replacement.
  * An EXHAUSTED seed gives up without recording anything. Out of attempts, the
    branch below is written for a tile that was offered and has gone missing,
    and "nobody replaced the file" is perfectly true of a tile that never
    reached `favourites.xml` -- which is what two interrupted seeds leave. It
    used to answer that by telling the user they had deleted something they had
    never seen. Note that rolling the record BACK is not the fix either: that
    reads as "never offered" next start and seeds again, which is the retry
    loop the attempt limit exists to end.

## Kodi's unknown-addon window kills an add-on's own service

`Addons.SetAddonEnabled` flips the enabled flag at once and Kodi finishes
loading the add-on a couple of seconds later -- but it starts the add-on's
service script at the FIRST of those moments. POV reads a setting at module
import (`tmdb_api`), so inside that window the whole import chain dies and
`POVMonitor` never starts: no Trakt sync monitor, no premium notification, for
the rest of the session. Field log 2026-08-13 21:40, with our own "cycled POV"
line landing three tenths of a second after the crash.

`pov_addon_window_patcher.py` teaches POV's `addon()` to wait the window out.
Two things about it are not optional:

  * It runs FIRST in `main()`, ahead of every patcher that can arm a cycle.
    It sat in the build-repairs pass until a review pointed out that pass runs
    AFTER `pov_reload.reload_if_patched()`.
  * The wait uses the abort monitor, not `sleep`. It runs inside POV's service
    startup and Kodi force-kills a script that will not stop within 5 seconds.

Verify the anchor against a REAL 6.08.x POV, not the 5.12.04 in our build zip
-- POV auto-updates itself on first launch, and 5.12.04 does not even have the
crashing import.

## The window patch covers ONE of POV's two Addon() call sites

`pov_addon_window_patcher.py` rewrites POV's `addon()` helper in
`resources/lib/modules/kodi_utils.py` so it waits out the seconds in which
Kodi calls a just-re-enabled add-on unknown. That is the call site the field
log died on. It is not the only one.

The same file builds an `Addon()` **at module scope**, on the line that runs
when anything imports it -- `addon_object, window, execJSONRPC = Addon(), ...`
in the 6.08.06 copy devices actually run, and an equivalent line in the copy
this build ships. `get_setting`, `set_setting` and `make_settings_dict` in the
same file each construct their own as well.

**These are exposed the same way, and Kodi's source says so plainly.** From
`xbmc/interfaces/legacy/LegacyAddon.cpp`, the constructor with no id fills the
id in from the calling script and then runs the identical check:

    if (id.empty())
      id = getDefaultId();
    ...
    if (!CServiceBroker::GetAddonMgr().GetAddon(id, pAddon, OnlyEnabled::CHOICE_YES))
      throw AddonException("Unknown addon id '%s'.", id.c_str());

So `Addon()` and `Addon(id='plugin.video.pov')` end at the same line, with the
same enabled-only filter. There is no version of this where the bare one is
safe and the other is not. The field log happens to show `kodi_utils` importing
cleanly and dying later at `addon()`, which says the module-scope line was
outside the window on that boot -- one sample about timing, not a property of
the code.

**Not fixed in 0.2.492, deliberately.** The fix that covers all of them is to
anchor on `from xbmcaddon import Addon` and shadow the name with a retrying
wrapper, so every use in the file inherits it. That is a wider change to a
third-party file that auto-updates itself, and the current patch fails safe
when POV moves under it -- it reports `unmatched` and changes nothing -- while
a name-shadowing patch has more ways to be subtly wrong against a version
nobody has seen yet. It is the right next step, with its own anchor-uniqueness
and compile checks, and it should not ride along at the end of a release.

What ships is a strict improvement on nothing, and the README says only what it
does: it covers the failure that was reported, not every instance of the class.

## Account Manager forces Kodi's global auto-update on, every boot

Confirmed from the shipped pack, not inferred: `startup.py`'s
`run_addon_updates()` calls `control.autoupdate_on()`, which sets Kodi's
`general.addonupdates` to 0 (install automatically) over JSON-RPC, then runs
`UpdateAddonRepos()`. Its gate is a Trakt token, and `StartupManager()` runs
every boot.

So on any device with Trakt connected through Account Manager, Kodi may
replace Umbrella, POV and the rest from their own repos. Our ~49 third-party
patchers are self-healing and re-apply at the next start, so this does not
lose them permanently. What it does risk is an upstream change that MOVES an
anchor: 80 places return `unmatched` rather than guess, and the feature then
disappears with only a WARNING nobody reads. The maintainer has said they are
fine with auto-update; making `unmatched` visible instead of buried is the
follow-up worth doing.

## CLOSED: the two blockers, and the three the review found after them

Both original blockers were the same shape -- **the snapshot went stale against
a counter that had been reset, and the code judged on a pair of numbers that no
longer meant the same thing** -- so rather than patch the two instances, the
number went. See the tile section above for the mark that replaced it. What
each of the five turned out to need, since the fixes are not obvious from the
symptoms:

  1. THE WRITER ROLLED THE COUNT BACK. Not fixable in the reader: the writer
     healed the corruption into a clean, wrong number before the reader could
     see there had been any. Fixed by removing the read -- a mark needs no
     previous value.
  2. CLEAR DATA ON THE WIZARD, THEN A DELETION, THEN A SKIN SWITCH. The
     deletion was seen and deliberately not recorded, because a count of zero
     could not be told from a wiped one. With a mark, "no file at all" is a
     value with a meaning, so the deletion is recorded and the later switch
     cannot reopen it.
  3. ONE CORRUPTED RECORD COPY OUTVOTED THE LEGIBLE ONE, which needed nothing
     but ordinary flash wear on one file.
  4. THE WIZARD COPIED THE FILE AND THEN MARKED IT, so a power cut between the
     two left a replacement nothing could see.
  5. AN EXHAUSTED SEED INVENTED A DELETION for a tile that had never once been
     in `favourites.xml`.

...and a sixth, found by the fuzzer within an hour of its oracle being
repaired: `ensure_patched` asked the record whether the user had removed the
tile BEFORE asking whether the tile was in the file.

...and a seventh, which was the SIXTH ONE'S OWN FIX, caught by the next review
the same day. Moving `has_tile` in front of the removal check meant the repair
below it -- which fires on any record that is not `offered` -- rewrote a
RECORDED deletion to "offered" whenever the tile was in the file for any
reason. A per-skin seed carrying the tile is such a reason, and seeding it on
all four skins is open work in this repo; on the devices that got it, the
user's deletion would have been erased and the next skin switch to a seed
without the tile would have put the tile back. A removal somebody actually
wrote down is now left strictly alone; only the INFERRED one -- the module's
own guess when no copy of the record is legible -- is still overridden by a
tile that is really there.

### The fuzzer was reporting zero because half of it was switched off

`x_fuzz_orderings.py` sets `ever_deleted_and_seen = True` two lines above the
`not ever_deleted_and_seen` that guards INV2 -- the invariant that catches an
untouched user being told they deleted the tile, which is the exact harm the
whole feature is about. The moment INV2's other clauses could be true, this
line had already falsified its first one. **INV2 could not fire for any input,
ever**, and 15,625 orderings reported "violations: 0" with it disabled. It also
indexed the prefix with `seq.index(step)`, which finds the FIRST `'boot'` in
the tuple no matter which one the loop is standing on.

Both repaired, and the action set widened past atomic actions -- every original
action was all-or-nothing, so no interruption could be modelled and none of
blockers 3-5 was reachable even with a working oracle. It now runs 16,807
orderings over {switch, switch_unmarked, corrupt_seen_wiz, clear_wizard,
clear_svc, delete, boot} with INV1 and INV2 both at zero.

**Read this before trusting any green fuzz run in this repo**: an oracle that
cannot fire looks exactly like an oracle that found nothing.

The same lesson came back one level deeper. Every fuzzer here wrote its
`switch` action with a TILE-FREE seed and had no action that re-adds the tile
by hand, so `has_tile()` could only ever become true through the patcher's own
seeding call -- structurally blind to a tile arriving in `favourites.xml` from
anywhere else, which is where the sixth and seventh bugs both lived. Both were
caught by hand, with 16,807 green orderings running alongside.
`x_fuzz_seeded_tile.py` closes it with `switch_seeded` (a per-skin seed that
carries the tile) and `readd` (the user re-favourites it), and it takes
`TILE_ADDON_DIR` so it can be pointed at an older revision **and made to go
red on demand** -- against `c2f6a3f` it reports 46 violations, against HEAD
zero. Do that to any fuzzer here before believing it.

### Four residuals, deliberately not fixed

The first two go the safe direction -- a tile somebody never sees again. **The
third does not**, and this section listed only the safe ones until a review
pointed that out.


  * A MARK WRITE THAT FAILS OUTRIGHT while the favourites copy succeeds --
    `addon_data` unwritable, `userdata` fine -- leaves a replacement nobody can
    detect, and the reader will eventually read it as a deletion. It cannot be
    fixed by failing the skin switch: a bookkeeping file is never worth the
    thing the user actually asked for. It is modelled in the fuzzer as
    `switch_unmarked` and excused by name, so the shape of what cannot be
    caught stays written down instead of being rediscovered.
  * NO LEGIBLE COPY OF THE RECORD ANYWHERE (one wiped by "Clear data", the
    other corrupted) reads as a deletion. Nothing is left that knows whether
    the tile was ever offered, and this is the direction the feature chose from
    the start: the cost of being wrong this way is a tile somebody never sees
    again, the other way it is a tile they cannot get rid of. The fuzzer
    excuses it by checking the filesystem, not the action names, so the
    exception cannot quietly widen.
  * BOTH RECORD COPIES ABSENT reads as a fresh install and re-offers the tile
    -- including to somebody who deleted it, if they happen to click "Clear
    data" on both add-ons, however far apart. This one goes the WRONG way, and
    it cannot be closed without closing fresh installs with it: "no record at
    all" has to mean "never offered" or nothing could ever seed. `t_clear.py`
    test 6 and the fuzzer's `accepted_resets` carve-out both call it the user
    asking for a reset, which is a fair reading of two deliberate wipes, but it
    is a reading and not a fact.
  * `_sidecar()` PREFERS THE WIZARD-FOLDER COPY with no freshness comparison,
    so a copy that stays readable but stops accepting writes shadows a
    correctly-updating one forever, and "whatever this start cannot settle, the
    next one can" stops being true under that one fault. It fails safe -- the
    seed refuses on one copy and returns `write_failed` rather than deciding
    anything -- so it is a broken promise rather than a lost tile. Fixing it
    means comparing the two legible copies and preferring the fresher, which
    needs something in the record to order them by; worth doing, not worth
    doing in the same pass as the fix that found it.

## Pre-marker installs are frozen out of every app update, permanently

`kodi_version_update_check` returns early on the AUTOMATIC path whenever
`_marked_platform_release()` is None -- which is every package through `.47`,
since `system/povil-release.txt` first shipped in `.48`. Wizard 0.1.35 added
that in `3979e13` for a real reason: 0.1.34's bridge classified any unmarked
install as `.47`, so a routine quick update was followed, for every legacy
user at once, by a dialog demanding they hand-reinstall the whole application.

The mitigation was right and it is also blunt: those installs will never be
told automatically about ANY future package, including one that matters, and
they are exactly the population that has never updated the app. Their only way
out is the manual menu item, which still works and still uses the `.47` bridge
(so it reports "21.3-povil.47" to somebody who may be on `.43` -- the number is
the bridge, not a reading).

**What makes this worth revisiting now**: the fault in 0.1.34 was not that the
installed version was unknown. It was prompting at all for a package nobody
needed -- and `NO_AUTO_APP_PROMPT_TARGETS` now handles exactly that, precisely,
by naming the release rather than muting a population. With that in place the
blanket skip could be relaxed to "prompt an unmarked install too, for releases
that are not on the suppression list". Deliberately NOT done in this release:
it un-mutes a whole population that is currently quiet, which is not something
to slip into a train that has already been validated and is about to leave.

## Smaller, also open

  * Four more written-and-undeclared marker ids the settings test cannot see,
    because they are passed as module constants rather than literals:
    `_fen_widgets_seeded`, `_ui_prefs_seeded`, `_pov_scraper_tune_state`,
    `_pov_torbox_usage_patch_version`. No functional risk (undeclared ids
    persist), so this is completeness, not a bug.
  * `tools/test_platform_packages.py` is RED, and I had this wrong. I called it
    "drift to be settled before packaging". It is not drift and there is
    nothing to settle: `test_wizard_rebuild_from_clean_checkout` copies the
    CURRENT wizard source into a clean tree and rebuilds the LAST RELEASED
    version from it, so the moment anyone edits `wizard/source/**` for the next
    version, the rebuilt zip stops matching the released manifest's SHA-256 and
    the test goes red. By design. It goes green again in the packaging commit
    itself, which writes the 0.1.46 manifest and moves the pins -- exactly what
    `aef40a7` did for 0.1.45. Twelve lines carry a version, all in that file:
    lines 226, 250, 275-276, 318, 321, 323, 325, 349, 363-364, 367 -- the
    0.1.45 ones become 0.1.46 and the 0.1.44 ones become 0.1.45. So it is a
    packaging STEP, not a blocker standing in front of packaging.

## A correction I had to make about myself

Two commits on this branch declared 17 one-shot markers in `settings.xml` and
justified it with the claim that Kodi drops a write to an undeclared id. That
claim is false, and the section above titled "Undeclared settings DO persist"
had already settled it from Kodi's own C++ two days earlier -- naming several
of the same markers and calling them a tidiness item rather than a bug. I
audited my way to the same list and drew the opposite conclusion without
reading what was already here.

The declarations stayed (house style, and this section says so too). Every
place that asserted the false reason was corrected in `bfdd288`. The lesson is
narrower than "read the docs": this file is the record, and re-deriving
something it already answers is how a settled question gets unsettled wrongly.

## Working style

- Be certain before shipping: read the code, reproduce with a unit test.
- Iterate on real Kodi logs; SubSync's `verdict for ...` diag line is the
  primary tuning signal.
- Communicate with the maintainer in Hebrew; keep docs in English.
