# SubSync — the "find a SYNCED subtitle" scan feature

> Status: **PLAN / design — not started.** Companion to `MORANSUBS_PLAN.md`
> (which covers merging DarkSubs into MoranSubs; Phase B of that plan is
> already largely shipped — the vendored `subs_engine` + bridge exist and
> `use_builtin_engine` defaults to true).

## 1. Goal (from the maintainer)

The #1 user complaint today: **subtitles don't sync**. Even with the Hebrew
availability badge, unless the Hebrew is *embedded* in the file there is
always a chance the chosen subtitle drifts. Wanted: a **scan feature** that,
for the episode/movie being played, finds a subtitle that is actually
**synchronized**, in this priority order:

1. Hebrew human subtitles (Ktuvit / Wizdom / any provider).
2. The community AI pool.
3. A *matching* English (or other-language) subtitle — which the existing AI
   feature then translates to Hebrew.

## 2. What already exists (verified in code)

The **priority chain itself already runs today** — this feature is NOT about
building the chain, it's about making the chain *sync-aware*:

- `service.py::_autosub_on_play` (service.py:1700) already does, on play:
  embedded Hebrew (auto-select, 101%) → best "ready" Hebrew from
  `translate.list_candidates` (human providers → pool → MT) → gated
  auto-translate of the best-matching English (`engine_ai`).
- `translate.list_candidates` (translate.py:363) already orders the picker:
  embedded he → human he (live + pool-mirrored Ktuvit) → AI pool → MT →
  foreign grouped by language with "תרגום AI לעברית" actions.
- The community pool (Cloudflare Worker + KV + Telegram channel) already keys
  every variant by **source-content hash** (`pool.py:257`), so "same source
  sub = same timing" reuse is exact. `/embedded` and `/ktuvit` registries
  already exist.
- The current playing release name is published by
  `subs_filename_publisher.py` (`Window(10000).Property(subs.player_filename)`
  ← POV's `pov_picked_source_name`), and `subs_engine_bridge._detect_release_name`
  picks the best release string for scoring.

### The actual gap — "sync" today is a *name-similarity guess*

1. The match % is `difflib.SequenceMatcher` over release-name **tokens**,
   computed in **three separate places** that must be kept mirror-identical by
   hand: `subs_engine/engine.py::sort_subtitles` (+resolution & source-word
   ×3 boost), `translate._match_pct` (translate.py:97), and
   `he_sub_match._score` (he_sub_match.py:948). No structured understanding
   of release group / WEB-vs-BluRay / PROPER — a 60% can be perfectly synced
   and a 75% can drift by minutes.
2. **Nothing ever verifies or fixes timing.** `download_sub` does punctuation
   / HI cleanup only. The delivered SRT keeps the source timecodes verbatim.
   The vendored `pysrt` has `shift`, and `srt.py` can parse/compose — unused
   for timing.
3. The one real aligner in the codebase — `arabic_gender.py:89-214`
   (`_estimate_map`: FPS-ratio scale candidates × offset voting histogram;
   `_overlap_rate` confidence gate) — is production-proven but only aligns
   the Arabic gender *oracle* to the source. It never syncs the *output*.

## 3. Key insight

Sync is a **timing-transfer problem**, not a search problem.

For almost every release users actually play, a subtitle that exactly matches
that release exists in *some* language (usually English on OpenSubtitles —
per-release coverage there is near total). An **exact-release sub in any
language is a trusted timing reference ("oracle")** for the video. Once we
have an oracle:

- Any Hebrew sub (Ktuvit sub made for a *different* release!) can be
  **verified** against it and, when a confident linear map exists,
  **auto-retimed** to the current release — pure Python, <1s, no audio, no
  ffmpeg, works on every Kodi device.
- An AI translation inherits its timing from its source sub, so translating a
  release-matched (or retimed) source yields a **synced-by-construction**
  Hebrew sub.

This flips the economics: today Hebrew human subs exist for most titles but
for the *wrong release*, so users fall back to AI. With retiming, those human
subs become usable for every release.

## 4. Architecture — three layers + the scan ladder

### Layer A — one structured release scorer (`release_match.py`)

New module, replaces/backs all three difflib scorers so every surface (picker
%, source-screen badge, autosub thresholds) agrees:

- Parse both names with the **vendored `parse_torrent_title` (PTN)**
  (`subs_engine/_libs/parse_torrent_title`): group, source class
  (WEB-DL/WEBRip/BluRay/HDTV/CAM…), resolution, codec, proper/repack,
  edition, season/episode sanity.
- Tiered score (calibrated, examples):
  - exact normalized name → **100** ("sync guaranteed").
  - same group + same source class (+same edition) → **~92** (in practice
    always synced).
  - same source class, different/unknown group → **~65**.
  - cross source class (WEB vs BluRay), or PROPER vs non-PROPER → **cap ≤40**
    regardless of token similarity (this is the current false-positive source).
  - token-similarity only as a tie-breaker *within* a tier, never across.
- Emits `(score, tier, reasons)` so the UI can say *why* ("אותה קבוצת
  ריליס").
- **Synthesized names are low-trust:** `subs_filename_publisher` sometimes
  *invents* a name (`Title.SxxExx.QUALITYp.mkv`) when POV publishes no real
  release. An "exact match" against a synthesized name is meaningless — the
  scorer must flag such names (no group + synthetic pattern) and never award
  the exact/group tiers against them, and they must never anchor an oracle.
- Wire-in points: `subs_engine/engine.py::calculate_sync_percentage`,
  `translate._match_pct`, `he_sub_match._score` become thin calls into it
  (keeping their signatures).

### Layer B — sync verify & auto-retime (`sync_align.py`) — the heart

Extract + generalize the proven estimator from `arabic_gender.py`:

- `estimate(ref_cues, cand_cues) -> (scale, offset_ms, vote, overlap)` —
  scale candidates from FPS ratios {23.976,24,25,29.97,30}, offset via the
  voting histogram (±600s, 500ms bins, 3-bin peak), overlap-rate gate.
  Confidence gate as in production: `0.90 ≤ scale ≤ 1.11`, `vote ≥ 0.65`,
  `overlap ≥ 0.80`; require ≥ 8 dialogue cues each side; strip
  credit/watermark lines (leading "תורגם/סונכרן על ידי…" blocks) before
  aligning.
- `verify(ref, cand)` → CONFIRMED (|offset| ≤ ~700ms, scale≈1, gate passed)
  / FIXABLE (gate passed, map ≠ identity) / UNKNOWN (gate failed — e.g.
  extended-vs-theatrical cut: correctly refuse rather than mangle).
- `retime(cand_srt_text, scale, offset) -> srt_text` — linear map applied
  via the existing `srt.py` parse/compose (no new deps).

**Reference (oracle) selection**, in order:
1. A sub whose release **exactly matches** the playing release (Layer A
   tier=exact), any language — usually English from OpenSubtitles (the engine
   already fetches all languages).
2. tier≈group+source match.
3. None → Layer B is skipped for this play (behave as today).

**Oracle cross-checking:** a single exact-name sub can itself be mis-synced
or mislabeled on the provider. When ≥2 release-matched subs exist (any
languages), align them to each other first; mutual agreement (map ≈ identity)
promotes them to trusted, an outlier is discarded. With only one candidate
oracle, retime verdicts are recorded at lower confidence until the Layer-C
feedback loop (or a second oracle) confirms them.

**What actually touches the video:** nothing in Layers A/B reads the video's
audio — the anchor to the real file is the release identity (same release =
byte-identical timing for everyone) plus the Layer-C human feedback (a viewer
who watched ≥15 min without touching subtitle delay = ground-truth
confirmation; a settled manual delay = a ground-truth correction). The system
is a chain of evidence with honest confidence tiers, not a mathematical proof
— tiers that can't be backed are labeled "לא מאומת", never upgraded.

Cost: at most **one extra source-sub download** per play (the oracle) + <1s
CPU. Results cached per `(candidate_hash, release_norm)` so each pair is
computed once per device — and once *globally* with Layer C.

### Layer C — community sync registry (worker `/sync`)

Extend `pool/worker.js` + `pool.py` with a tiny offsets index (KV only, no
files):

- Record: `v1:sync:<media>:<candidate-id>:<release-norm>` →
  `{scale, offset_ms, verdict, votes, engine_version}`. `candidate-id` =
  pool `source_hash` for pool variants, or `provider:id` (e.g.
  `ktuvit:<sub-id>`) for live provider subs.
- Devices **contribute** every verify/retime result (same fire-and-forget +
  HMAC pattern as `/contribute`); devices **consume** before computing —
  most users get an instant, pre-verified answer with zero extra downloads.
- **User-feedback signal:** capture Kodi's manual subtitle-delay
  (`Player.SubtitleDelay`) at playback stop when a MoranSubs sub was active;
  a non-zero settled delay is contributed as a weak vote (and a zero delay
  after ≥15 min of playback is a strong "confirmed synced" vote). This is
  the ground truth loop that keeps the whole system honest.
- `/lookup` response gains the sync records for the media so ONE existing
  round-trip serves them (no new request on the hot path).
- **Privacy surface: nothing new.** The pool already receives, per install
  (anon id): what media is looked up, which release names were played
  (`/embedded`, `/ktuvit`), and shared SRTs. A sync record is the same
  category of metadata (media, sub-id, release → offset) with no new content.
  All contribution rides the existing `pool_share` gate; gate off = no sends.
- **Write discipline (Cloudflare KV free tier ≈ 1,000 writes/day):** votes
  must NOT be written per-playback. Contribute only on state change — a newly
  computed retime, the FIRST confirmation of a record, or a manual-delay
  measurement that disagrees with the stored record — deduped client-side
  with `.shared`-style sidecar markers (same pattern as `/contribute`).
  Routine playback of an already-CONFIRMED record writes nothing.

### The scan ladder (rework of `_autosub_on_play` + `list_candidates` order)

For the playing release R (confidence ladder, first hit wins):

| # | Candidate | Sync assurance | Label |
|---|-----------|----------------|-------|
| 0 | Embedded Hebrew track | by construction | `תרגום מובנה · 101%` (exists) |
| 1 | Hebrew human, tier exact/group-match to R | Layer A; verify vs oracle when cheap | `מסונכרן · תואם גרסה` |
| 2 | Pool variant already keyed/verified for R (source-hash or `/sync` CONFIRMED) | by construction / registry | `מסונכרן · מאגר` |
| 3 | Hebrew human for a DIFFERENT release | Layer B retime vs oracle → gate | `סונכרן אוטומטית ✓` |
| 4 | Pool AI variant for a different release | same retime path | `סונכרן אוטומטית ✓ · מאגר` |
| 5 | English/other, tier exact to R | translate (AI) — synced by construction; contribute to pool | `תרגום AI · תואם גרסה` |
| 6 | English/other, no match | retime source vs oracle first, then translate | `תרגום AI · סונכרן` |
| 7 | Nothing | today's behaviour + honest labeling | `לא מאומת` |

Steps 5–6 mean every AI translation contributed to the pool is now
release-correct — the pool compounds in quality over time.

**UX:** runs inside the existing autosub overlay with stage text
("סורק כתוביות בעברית… / מאמת סנכרון… / מסנכרן אוטומטית… / מתרגם…"); the
picker shows the tier badges above instead of a bare %; a manual
"סרוק כתוביות מסונכרנות" action in `subs_chooser` re-runs the ladder with a
visible progress dialog. The source-screen `HEB NN%` badge (he_sub_match)
upgrades to `HEB מסונכרן ✓` when the registry has a CONFIRMED record.

**Notification policy — quiet by default, no toast spam:**
- The verdict for a (sub, release) pair is CACHED — locally and in `/sync` —
  so it is NOT re-checked on every play. The background verify runs only
  when no verdict exists yet (typically once per release, globally, by the
  first viewer). A confirmed pair plays silently forever after.
- Silent events (NO toast): registry-confirmed delivery, exact-match
  delivery, background verify that CONFIRMS the already-playing sub
  (nothing changed for the user — the tier just shows in the overlay's
  final status line and the picker labels, where the % badge lives today).
- One toast, only when something CHANGES for the user: an in-place swap to
  a better sub ("הוחלף לתרגום אנושי מסונכרן") or a retime correction
  applied mid-play. One per playback, max.
- Low-confidence delivery (nothing verifiable found): the honest tier shows
  in the overlay status + picker label — not as a recurring toast.

## 4b. The certainty model — what can honestly reach ~100%

"100% synced" is only meaningful when the evidence is anchored to the
**actual playing file**. Ranked anchors, strongest first:

| Anchor | Certainty | Coverage |
|--------|-----------|----------|
| A. Embedded Hebrew track in the file | 100% by construction | rare |
| B. **File-anchored verify (container probe, §7.3/S4):** candidate aligned against the playing file's own embedded text-track cues | ~100% — the reference IS this file | high: WEB-DL/remux MKVs almost always mux English subs |
| C. Pool variant, same source_hash + viewer-confirmed via `/sync` votes | ~100% statistically (each vote = a human who watched THIS release) | grows with use |
| D. Exact release identity + cross-oracle agreement | very high | high |
| E. Retimed vs oracle (gate passed) | high | — |
| F. No anchor (no embedded track, no matching sub, HLS) | honest "לא מאומת" — physically unverifiable without audio (S5 Gemini-audio covers part) | small |

Implications:
- **Anchor B is the "100%" workhorse and serves human subs FIRST**: whenever
  the playing file carries any embedded text track, every human Hebrew
  candidate can be verified — and retimed — against the file itself before
  (or seconds after) delivery. Because certainty is the maintainer's top
  goal, the container probe should be pulled forward if S2's sub-vs-sub
  verification proves insufficient in the field.
- **Self-healing delivery:** deliver the best candidate immediately, run the
  file-anchored verify in parallel; if a mismatch is detected in the first
  ~minute, swap in the retimed version silently. The user experiences
  "always synced" without waiting on verification.
- **Convergence:** every play adds a vote; for any reasonably popular
  title+release the record reaches anchor-C certainty within days, and every
  subsequent viewer gets a 100%-confirmed answer instantly.

## 4c. Latency budget — nothing gets slower than today's ~5s

Hard rule: **verification NEVER delays the first subtitle.** The user gets a
subtitle in the same ~5s as today; certainty arrives behind it.

- **T-10s→0 (before playback even starts):** the scan begins at SOURCE PICK,
  not at play. The release name is known the moment the user picks a source
  (`picked_release` / `pov_picked_source_name`), and debrid resolve +
  buffering takes seconds anyway — the same window the existing
  `he_sub_match.prewarm` already exploits. Provider search, `/lookup`
  (which now carries `/sync` records), and even the oracle download can
  complete before the first frame renders.
- **T+0–5s:** deliver by ladder from whatever the prewarm produced —
  registry-confirmed pick (zero extra work), embedded, exact-release Hebrew,
  pool fetch (~1–2s). Same perceived speed as today.
- **T+5–60s (background):** the slow tail — oracle verify, retime, container
  probe (a few MB of Range fetches + <1s parse). If it contradicts the
  delivered sub → self-healing in-place swap to the retimed version.
- **At scale:** every verified record lands in `/sync`, so for any title
  people actually watch the FIRST tier already answers "confirmed" — the
  steady state is *instant AND certain*, and the background tail does
  nothing. The slow path is paid once per (release, sub) globally, by the
  first viewer, invisibly.

## 5. Phasing (each shippable via quick_update, standalone-safe)

- **Phase S1 — unified structured scorer (low risk).** `release_match.py` +
  rewire the three scorers + thresholds in the autosub chain (never
  auto-apply a cross-source-class "match"). Pure-Python, fully offline
  unit-testable with release-name fixtures.
- **Phase S2 — verify & retime (the heart).** `sync_align.py` extracted from
  `arabic_gender.py` + oracle selection + retime delivery in
  `translate.resolve` / autosub ladder steps 3–6 + per-device cache.
  Testable offline with SRT fixture pairs (known offset/FPS cases +
  must-refuse recut cases) under `resources/fixtures/`.
- **Phase S3 — community sync registry.** Worker `/sync` (KV), pool.py
  contribute/consume piggybacked on `/lookup`, subtitle-delay feedback
  capture in service.py, badge upgrade in he_sub_match.
  **IMPORTANT (maintainer):** the repo's `pool/worker.js` is deliberately
  STALE — the live worker code exists only on Cloudflare and is newer. Before
  ANY S3 worker edit, ask the maintainer for the current worker.js; do not
  base changes on (or commit updates to) the repo copy.
- **Phase S4 — container-probe reference (video-anchored oracle).** HTTP
  Range probe of MKV/WebM direct streams → embedded text-track cue
  timestamps as a TRUE reference for estimate() (see §7.3). Ships after S2/S3
  prove the sub-vs-sub path.
- **Phase S5 — research (optional, later).** Gemini-audio deep verify
  (§7.4, opt-in) and piecewise alignment for recut releases (mid-roll
  recaps, extended cuts) via anchor cues (numbers/names/latin tokens that
  survive translation). No on-device audio DECODING ever — demux-only.

## 6. Risks & mitigations

- **False retime worse than no retime** → the production-proven triple gate
  (scale window + vote + overlap) refuses rather than guesses; UNKNOWN keeps
  today's behaviour and label honesty ("לא מאומת").
- **HI vs non-HI cue-count mismatch** → dialogue-only filtering before
  alignment (as arabic_gender does) + overlap gate tolerates extra cues.
- **Oracle itself mis-labeled** → oracle requires Layer-A tier exact/group;
  `/sync` votes converge on the truth; user-delay feedback corrects.
- **Extra latency on play** → oracle download only when ladder reaches step
  3+; registry hit path adds zero requests (piggybacks `/lookup`); compute
  <1s. Autosub already runs on a background thread with the overlay.
- **KV growth** → sync records are ~100 bytes; TTL + same 400-style pruning
  discipline as existing caches.
- **Standalone edition** → `sync_align.py`/`release_match.py` are
  build-agnostic lib files; add to `STANDALONE_LIB_FILES` in
  `tools/build_ai_subtitles_packages.py`.

## 7. Prior art: ARVIO "Find Best Match" (ProdigyV21/ARVIO PR #446)

A comparable feature in an Android streaming app (ExoPlayer-based, so it has
two capabilities Kodi Python lacks: live access to embedded-track cue
intervals during playback, and raw audio capture for Gemini). Reviewed from
the PR; what it does:

- Collects cue-visible intervals from the built-in English track while
  playing (+ buffered lookahead), scores external Hebrew candidates against
  those intervals over a handful of cues/scenes, auto-picks the best ≥~80%.
- Embedded preferred-language always wins; a fallback-language embedded must
  not block a later preferred-language external; an explicit user pick
  always overrides auto-logic.
- UX: AI translation starts immediately during the scan; when a synced human
  sub is found it swaps in-place; otherwise the user stays on AI. "You only
  gain."

### Adopted into this plan

1. **Instant-best-then-swap-in-place (Phase S2 UX) — with a quota guard.**
   Don't make the user wait for the ladder; but "instant" prefers ZERO-COST
   options first: embedded → cached translation → pool fetch. **Gemini is
   invoked in exactly the same cases it is today** (the fast human-Hebrew
   scan — a few seconds — came up empty and translation_mode allows it); the
   change is only that the user sees the progressive first-chunk immediately
   instead of waiting, while the SLOW tail of the scan (oracle download,
   verify, retime — tens of seconds) keeps running in the background. When
   that tail lands a verified human sub, `setSubtitles` swaps it in-place
   with a toast ("הוחלף לתרגום אנושי מסונכרן"). The translation still
   completes, is cached and pooled — so the "wasted" quota case is only
   "human sub existed but was found late", bounded by making the human scan
   phase complete BEFORE Gemini starts (ARVIO's `aiFindBestMatchFirst`
   equivalent, our default). Never downgrade.
2. **User-pick-always-wins as a hard rule (Phase S2).** An explicit pick in
   the picker sets a per-file override flag; the ladder never replaces it
   (generalizes today's one-shot `skip_autosub` marker).
3. **Embedded-track cues as a TRUE video-anchored reference (new Phase S4).**
   Kodi's Python API exposes embedded stream names only, not cues — but
   debrid direct links support HTTP Range. A container probe can fetch a few
   MB at several file positions, parse Matroska/EBML clusters, and read the
   **text-subtitle block timestamps** (SRT/ASS tracks store plain text; no
   decoding needed) → a sparse reference timeline across the runtime, enough
   for the same estimate() (offset + scale). This anchors sync to the actual
   playing file, beating any oracle sub. Scope: MKV/WebM direct files (most
   debrid remuxes); not HLS. Pure Python; cache per file hash.

   **Probe mechanics & download budget (never the whole file):**
   - ~1–2 MB from the head: EBML header + SeekHead + Tracks (find the text
     subtitle tracks: codec S_TEXT/UTF8 or S_TEXT/ASS, language, and the
     `forced` flag) + the Cues index position.
   - The Cues (usually a few hundred KB near the end): cluster byte offsets
     by timestamp → we can jump to any minute of the film directly.
   - ~10–20 sample windows of ~4–8 MB spread across the runtime (each window
     covers a few seconds of interleaved data; sub blocks inside carry
     timestamp+duration+text, video/audio blocks are skipped by header). If a
     window lands on a dialogue-free scene (no sub blocks), slide forward.
   - Total: typically **~50–100 MB of ranged reads** (tunable; ≈ under a
     minute of normal streaming buffer), NOT a contiguous "3 minutes of
     video". Runs in the background verify stage; the result (scale/offset/
     verdict) is cached per file hash and shared via `/sync`, so the cost is
     paid once per release globally.
   - **The reference is LANGUAGE-AGNOSTIC.** The aligner never reads cue
     text — only timestamps — so an embedded track in ANY language (source
     language of a foreign film, French, Korean…) is exactly as good an
     oracle as English. Filter: skip `forced`-flagged or cue-sparse tracks
     (forced tracks mark only foreign-line moments — too sparse to anchor);
     prefer the densest text track.
   - Coverage note (maintainer): most MKV releases carry SOME embedded text
     track even when not English; the practical gap is MP4 (no usable text
     tracks), a small minority of today's sources. MP4 files simply stay on
     the oracle-sub anchors (D/E) + community confirmation (C) — verified,
     just not file-anchored.
   - The embedded track is a timing reference ONLY — extracting its full
     text for translation would require scanning the whole file, so the
     TRANSLATION source remains an external sub (any language; Gemini
     translates any→Hebrew), which the probe then verifies/retimes.
   - **Bitmap subtitle tracks anchor too.** Since the aligner reads only
     timestamps, an IMAGE-sub track (PGS `S_HDMV/PGS` on BluRay remuxes,
     VobSub) is a valid timing reference — its display events mark the same
     dialogue moments. We never need OCR. This closes the "BluRay remux with
     PGS-only subs" case that a text-only design would miss.

   **Container matrix (what the probe supports):**
   | Container | Embedded-sub probe | Notes |
   |---|---|---|
   | MKV / WebM | Full (windows method above) | text (SRT/ASS) AND bitmap (PGS/VobSub) timestamps |
   | MP4 / M4V | Full — and CHEAPER | `mov_text`/`tx3g` cue timing lives entirely in the `moov` sample tables (stts/stco): ONE ranged read of moov (few MB, head or tail) yields the COMPLETE cue timeline — no sample windows needed. Most MP4s carry no sub track at all, but when one exists this is the cheapest anchor of all |
   | AVI / TS / M2TS | No text-sub anchor | rare via debrid; fall to anchors C/D/E |
   | HLS / DASH | No single file — no probe | fall to anchors C/D/E |
   The ladder NEVER breaks on an unsupported container — it just loses the
   file-anchor tier and keeps oracle + community verification.
4. **Gemini-audio deep verify (last-resort tier, Phase S5, opt-in).** Kodi
   exposes NO player audio API — but the stream URL is known, so audio can be
   range-fetched and DEMUXED (never decoded) from MKV clusters in pure
   Python. Reality check on codecs: Gemini accepts AAC/MP3/FLAC/WAV/OGG —
   so an **AAC track** can be sent as-is (ADTS wrap) for speech-interval
   timestamps; **AC3/E-AC3/DTS tracks cannot** (Gemini doesn't accept them,
   and on-device decode is impossible). Before giving up on a DTS/AC3 main
   track, check the OTHER audio tracks — releases often mux a secondary
   stereo AAC "compatibility" track, which serves fine. Coverage is
   therefore partial by nature — which is fine: this tier only exists for
   the tiny anchor-F slice (no embedded sub track of ANY kind — text or
   bitmap — AND no matching external sub in any language). If in that rare
   slice the audio is also DTS/AC3-only: honest "לא מאומת" label, and the
   community delay-feedback loop still converges it to confirmed within a
   few viewers. 2–3 × ~60s segments per check, quota-aware, off by default.

### Where this plan is deliberately stronger

- **Global alignment vs a few cues:** scoring a handful of early scenes
  passes subs with progressive FPS drift (23.976↔25) that desync by minute
  30. The voting-histogram estimate uses ALL cues and detects scale, not
  just offset.
- **Fix, don't just filter:** ARVIO selects a sub only if it already matches
  ≥80%; near-misses are discarded. We retime them — turning the (common)
  "right sub, wrong release" case into a win.
- **Compute once, share globally:** ARVIO re-scans on every device/play; the
  `/sync` registry means most users get a pre-verified answer with zero
  extra work, plus the human delay-feedback loop ARVIO doesn't have.

## 8. Non-goals

- No audio/ffmpeg-based syncing inside Kodi.
- No change to the pool's variant key scheme (source_hash stays).
- No change to the human-first ordering (embedded → human he → pool → AI).
