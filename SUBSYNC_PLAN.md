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
- **Phase S4 — research (optional, later).** Piecewise alignment for recut
  releases (mid-roll recaps, extended cuts) via anchor cues
  (numbers/names/latin tokens that survive translation); NOT audio-based —
  audio decoding is not feasible in Kodi's Python across devices.

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

## 7. Non-goals

- No audio/ffmpeg-based syncing inside Kodi.
- No change to the pool's variant key scheme (source_hash stays).
- No change to the human-first ordering (embedded → human he → pool → AI).
