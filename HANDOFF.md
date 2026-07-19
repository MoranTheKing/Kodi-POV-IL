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
3. **iPhone Gemini API-key pairing** — the local-HTTP QR pair server is blocked
   by iOS (Local Network permission / Safari http), so users on iPhone can't
   pair a key the way Android does. A server-assisted pairing path is planned.
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
15. **Backend/infra follow-ups** are tracked in the maintainer's private notes,
   not here (this file is public and carries no backend or pool internals).

## Working style

- Be certain before shipping: read the code, reproduce with a unit test.
- Iterate on real Kodi logs; SubSync's `verdict for ...` diag line is the
  primary tuning signal.
- Communicate with the maintainer in Hebrew; keep docs in English.
