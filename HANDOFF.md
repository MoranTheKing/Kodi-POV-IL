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
   assembling zips, and never commit pool credentials to git. The community
   pool client in shipped zips is provisioned at packaging time
   (maintainer-only); the git source intentionally is not. When building a
   quickfix from the previous zip, simply don't touch `pool.py`.
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
  out-of-sync human Hebrew, Arabic, then es/fr/ru/it/pt/pl/uk/hi/cs/ro/el/
  bg/sr/hr/sk/ur/nl), time-aligns it to the source, and feeds per-line
  gender hints to the prompt. Fully fail-open.
- `resources/lib/autosub_service.py` — auto-on-play Hebrew search/apply
  (shared by the full build's service.py and the standalone slim service).
- `resources/lib/subs_engine/` + `subs_engine_bridge.py` — the vendored
  human-sources engine and its MoranSubs bridge.
- `resources/lib/subsync.py`, `sync_align.py`, `mkv_probe.py`,
  `release_match.py` — SubSync (build edition; see `SUBSYNC_PLAN.md`).
- `resources/lib/pov_*_patcher.py`, `<skin>_*_patcher.py` — runtime patchers
  applied by the build's service at boot. Marker-gated, compile-checked,
  atomic writes; a patch that can't apply never breaks POV.

## Shipping a quickfix (checklist)

1. Bump `addon.xml` version + add a `changelog.txt` entry.
2. Sync-logic change? Bump `_VERDICT_VERSION`.
3. Copy previous quickfix zip -> new name; `zip` in ONLY the changed files at
   their in-zip paths (never `pool.py` unless its logic truly changed).
4. Verify: same member set (plus intentionally added files), only intended
   CRC changes, `pool.py` untouched.
5. Point `build.txt` `gui=` at the new zip.
6. Bump the id in `quick_update.txt` + gentle Hebrew title/body.
7. Commit to the working branch, fast-forward `main`, push.

## Working style

- Be certain before shipping: read the code, reproduce with a unit test.
- Iterate on real Kodi logs; SubSync's `verdict for ...` diag line is the
  primary tuning signal.
- Communicate with the maintainer in Hebrew; keep docs in English.
