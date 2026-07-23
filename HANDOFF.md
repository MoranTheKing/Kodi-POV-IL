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
6. **ALWAYS bump the `note_id` in `quick_update.txt` (the `<id>` before `|||`),
   not just the footer version.** The wizard live-fetches this file from `main`
   and only shows a notification when the `note_id` CHANGES. Keeping the same id
   and only editing the footer = the release ships but NO user ever gets notified
   (this mistake has recurred — 0.2.426/0.2.427/0.2.428 all silently reused an id).
   Every user-facing quickfix/AI release gets a fresh id + a gentle Hebrew
   title/body. A notification-only fix (e.g. re-announcing) is just a new id +
   push to `main`, no rebuild.
   - **Build-time guard (include in every build script):** fail the build unless
     the working-tree `note_id` is greater than what `origin/main` currently
     serves (the wizard fetches from `main`; the LOCAL `main` ref is stale
     because we push `HEAD:main` without moving it, so compare `origin/main`):
     ```python
     import subprocess
     NF = 'wizard/assets/notification_files/quick_update.txt'
     def _noteid(txt): return int(txt.split('|||',1)[0].split('\n')[-1].strip())
     subprocess.run(['git','fetch','origin','main'], check=False)
     new = _noteid(open(NF).read())
     old = _noteid(subprocess.check_output(['git','show','origin/main:'+NF]).decode())
     assert new > old, 'quick_update note_id NOT bumped (%d) -> no notification will fire' % new
     ```
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

## MDBList integration — status (0.2.425–0.2.432, all shipped)

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
- **REMAINING tiles parity (next, per-skin native widgets)** — favourites already
  cover every skin, but for full parity with how each skin shows OTHER services:
  1. **FENtastic navigator.db native row** — `pov_navigator_patcher.py`
     (MOVIES_PA_V5 / TVSHOWS_PA_V5): add `mdblist_my_movies`/`mdblist_my_tvshows`
     rows pointing at the same two routes. Needs a version-constant bump per the
     patcher's versioning (honors user deletions).
  2. **Arctic Fuse 3 node** — `af3_home_patcher.py` (already writes "הסדרות שלי"/
     "הסרטים שלי" skinvariables nodes): add MDBList nodes there.
  Manager-add + watched/progress sync already done. Continue-Watching (Phase D)
  still deferred (series via /upnext if POV scrobbles episodes; movies stay local).

NOTIFICATION MISTAKE (now guarded): 0.2.426/427/428 first shipped reusing the same
`quick_update` note_id (only footer bumped) -> no notification fired. Fixed at
#525; step-6 build guard now fails a build unless note_id > `origin/main`'s.

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
   by key-preserving zip surgery.
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
16. **Backend/infra follow-ups** are tracked in the maintainer's private notes,
   not here (this file is public and carries no backend or pool internals).

## Working style

- Be certain before shipping: read the code, reproduce with a unit test.
- Iterate on real Kodi logs; SubSync's `verdict for ...` diag line is the
  primary tuning signal.
- Communicate with the maintainer in Hebrew; keep docs in English.
