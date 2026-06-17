# MoranSubs — unifying DarkSubs + the AI addon into one addon

> Status: **PLAN / design — not started.** This document is the agreed design we
> iterate on before any code is written. Nothing here is implemented yet.

## 1. Goal (from the maintainer)

One subtitle addon — **"MoranSubs"** — instead of two separate ones
(`service.subtitles.All_Subs` "DarkSubs" + `service.subtitles.kodipovilai`
"AI subtitles"). DarkSubs becomes *part of* the addon, not a separate addon.

Requirements:
- **Human subtitles stay first** (DarkSubs' role today) — the primary option.
- **AI / community-pool Hebrew show below**, clearly marked as AI.
- **Embedded Hebrew** stays the top pick (101%, as DarkSubs does today).
- **No cross-addon hooks** — remove the fragile machine-translate hook
  (`RunScript` + `.ai_done` sentinel), the `reuselanguageinvoker` reload cycle,
  and the 12 self-healing `darksubs_*` patchers. Everything in one process.

Accepted trade-off: we **fork** DarkSubs (absorb its code), so we stop getting
its upstream updates automatically and must re-sync manually.

## 2. Current state (what we're merging)

**DarkSubs (`service.subtitles.All_Subs`)** — a Kodi `xbmc.subtitle.module`:
- `autosub.py` — service that watches playback, auto-fetches, and does
  **embedded-track detection** (Player API; `[LOC]`, sync 101, auto-place
  Hebrew). This is the part that already handles embedded Hebrew correctly.
- `resources/modules/engine.py` — source **aggregation + sorting** (Hebrew /
  Telegram-MT / English / other groups), `machine_translate_subs()`,
  `download_sub()`.
- `resources/modules/sub_window.py` — the **custom pyxbmct picker** (the styled
  list with flags / % / `[LOC]` seen on screen).
- `resources/sources/*.py` — providers (OpenSubtitles, etc.).
- `telethon_dependencies/` — **Telegram client (telethon)** for Israeli subtitle
  channels. Large dependency.
- `reuselanguageinvoker=true`.

**AI addon (`service.subtitles.kodipovilai`)** — also a `subtitle.module`:
- `default.py` (search/download), `service.py` (startup + patchers),
  `translate.py` (Gemini engine + `list_candidates` + `resolve`), `gemini*.py`,
  `pool.py`, `cache.py`, `srt.py`, `source_capture/source_memory`,
  `he_sub_match.py`.
- The 12 `darksubs_*` / `dark_subs_integration.py` patchers + `darksubs_reload`
  (the coupling we want to delete).

**Build references to `service.subtitles.All_Subs`** that must be repointed:
- FENtastic OSD subtitle button (`RunScript(service.subtitles.All_Subs,
  sub_window_unpause)`), `DialogButtonMenu` (open/clear DarkSubs), settings
  relabels, the AI addon's patchers, `_ensure_darksubs_enabled`.

## 3. Target architecture

**Keep the addon id `service.subtitles.kodipovilai`; rebrand the display name +
icon to "MoranSubs".** Changing the id would make Kodi treat it as a new addon
and lose every user's settings (Gemini key!), the pool key context, and re-do
the subtitle.module registration. The id is internal; only the shown name
changes. `service.subtitles.All_Subs` is then **retired** (its code vendored in).

MoranSubs module layout (proposed):
```
service.subtitles.kodipovilai/           (display name: MoranSubs)
  default.py            -> single search/download entry, in-process
  service.py            -> startup (no darksubs_* patchers, no reload cycle)
  resources/lib/
    sources/            <- VENDORED from DarkSubs (opensubtitles, telegram, ...)
    aggregate.py        <- ported engine.py: gather + sort all sources
    embedded.py         <- ported autosub.py embedded detection ([LOC], 101%)
    translate.py        <- existing Gemini engine (direct call, no IPC)
    pool.py, gemini*.py, cache.py, srt.py, he_sub_match.py ... (existing)
    picker (decision below: native dialog vs vendored sub_window.py)
```

### The unified list (the heart)
One `search` builds and sorts ONE list:
1. **Embedded Hebrew** (Player API) — top, "101% [LOC] תרגום מובנה בעברית".
2. **Human Hebrew** (OpenSubtitles / Telegram / providers) — by match %.
3. **🤖 Community-pool Hebrew** (AI + manual uploads) — below human, marked.
4. **🤖 "Translate to Hebrew"** for any non-Hebrew source — below, marked.
5. English / other (and embedded English, demoted).

Picking a "translate" entry calls the Gemini engine **directly in-process** —
no `RunScript`, no sentinel file, no 300 s poll, no addon reload.

## 4. Phasing (safe, reversible, each phase shippable)

- **Phase A — Rebrand (cosmetic, ~trivial).** Display name + icon → MoranSubs.
  No functional change. DarkSubs still present and working. Ship, verify name.
- **Phase B — Vendor DarkSubs source-fetching into MoranSubs (parallel).**
  Port `engine.py`→`aggregate.py`, `autosub.py` embedded→`embedded.py`, the
  `sources/`, and the Telegram client. MoranSubs can now fetch human subs +
  embedded + pool + AI translation **entirely in-process**. DarkSubs stays
  installed for fallback/comparison. No hooks removed yet. Heaviest phase.
- **Phase C — Switch the build to MoranSubs as the sole subtitle service.**
  Repoint every `service.subtitles.All_Subs` reference (skins, favourites,
  `DialogButtonMenu`, settings). Retire DarkSubs. Verify coverage matches.
- **Phase D — Delete the coupling.** Remove the 12 `darksubs_*` patchers,
  `darksubs_reload`, the sentinel IPC, `dark_subs_integration`, and the
  `_ensure_darksubs_enabled` net. Final cleanup.

Each phase reaches users via the normal quick-update; B/C are the risky ones and
get the most device testing before C flips the switch.

## 5. Key decisions — RESOLVED

1. **Picker UI: Kodi's native subtitle dialog + a well-organized unified list.**
   The "beauty" comes from the list's organization (sections + coloured badges +
   ordering), which MoranSubs fully controls via the entries it returns, and
   renders on every skin. (A custom pyxbmct window can be added later if we ever
   want pixel-identical chrome across skins, but it's not needed to start.)
2. **Telegram (telethon) sources: KEEP — vendor them in.** More subtitle
   coverage is wanted, so the Israeli Telegram channels stay. We vendor telethon.
3. **Upstream re-sync: not a concern.** DarkSubs (`service.subtitles.All_Subs`,
   v4.7.7) has **no auto-update** at all — no `<repository>` in its addon.xml, no
   self-updater anywhere, not in our repo or the wizard. It's simply bundled in
   the build (530 files; the quickfix only carries the 3 files we patch). So it
   was *already* manually controlled. Absorbing it into MoranSubs changes nothing
   about updates; future DarkSubs bumps are a manual code replacement, exactly as
   today.
4. **Timeline: run Phase B as a long-lived parallel track**, while smaller fixes
   keep shipping.

## 6. Risks & mitigations

- **Loss of upstream DarkSubs updates** → documented manual re-sync (#5.3).
- **Coverage regression** during transition → Phase B keeps DarkSubs installed
  in parallel so we can compare before flipping in C.
- **Telegram/telethon weight & fragility** → decision #5.2 may drop it.
- **Build-reference breakage** (skins/favourites/menus point at All_Subs) →
  mechanical repoint in C, self-healing patchers can ease the transition.
- **Big-bang risk** → strict phasing; C (the switch) only after B is proven on
  device.

## 7. Non-goals
- Not changing the Gemini translation logic, the pool, or the quality gate.
- Not changing the addon id (no settings migration).
- Not dropping human-subs-first behaviour.
