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

## autosub live/IPTV guard

`autosub_service.py` skips the auto Hebrew search for live playback: PVR
protocol paths, a non-empty `VideoPlayer.ChannelName`, zero `getTotalTime()`
(5 s grace), and a configurable addon exclusion list `autosub_excluded_addons`
(default `plugin.video.idanplus`). All fail-open.

## Open items (as of this handoff)

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
2. **Anime navigation, POV 6.07 (open):** hard to scroll horizontally + a
   long-press bounces to the Kodi home, ONLY inside anime lists, on a **phone**.
   VERIFIED: POV's anime list-building + context-menu code is byte-identical to
   regular tvshow/movie lists (`build_tvshow_content`) — no anime-specific
   broken action, so it is NOT a POV logic bug. User confirmed it happens on the
   **phone (touch)**; anime submenus route through the identical
   `build_tvshow_list`/`build_movie_list` builders as regular lists, so the
   items inside anime are byte-identical to a regular list. Next diagnostic step
   (pending): an A/B on the SAME phone — long-press an item in a REGULAR POV list
   (e.g. Movies → Popular). If it ALSO bounces to home, it's general Kodi-Android
   touch handling (not anime, not patchable by us); if only in anime, capture a
   debug log of the exact interaction. Candidates otherwise: Kodi touch handling
   of horizontal poster views, or skin-view perf.
3. **iPhone Gemini API-key pairing** — the local-HTTP QR pair server is blocked
   by iOS (Local Network permission / Safari http), so users on iPhone can't
   pair a key the way Android does. A server-assisted pairing path is planned.
4. **Backend/infra follow-ups** are tracked in the maintainer's private notes,
   not here (this file is public and carries no backend or pool internals).

## Working style

- Be certain before shipping: read the code, reproduce with a unit test.
- Iterate on real Kodi logs; SubSync's `verdict for ...` diag line is the
  primary tuning signal.
- Communicate with the maintainer in Hebrew; keep docs in English.
