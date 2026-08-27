# NOX Skin (4th skin) — Implementation Plan & Widget Mapping

Status: STAGES 1–4 BUILT (shipped in wizard 0.1.20 / build 0.1.47 /
quickfix 0.1.155 + dist/Kodi-POV-IL-NOX-skin-pack.zip). STAGE 5 (device
render/RTL test) pending — to be done by the user on a real device.

## What shipped
- `skin.povil.nox` v1.0.0: rebranded + scrubbed Estuary MOD. font.py
  side-loader deleted; all foreign plugin calls (plugin.program.Anonymous,
  Settingz-Anon) neutralized/mapped; AnonymousTV branding scrubbed.
- Home widgets remapped: novix→POV (130, mechanical, same TMDB scheme),
  telemedia→idanplus (81, best-effort TV/VOD), drax/flashstream/misc→POV
  (76), watchnixtoons→otaku (3). Final home targets are only pov/idanplus/
  otaku/youtube — all shipped addons. Zero new XML parse errors.
- Hosted as a single on-demand pack `dist/Kodi-POV-IL-NOX-skin-pack.zip`
  (~24 MB). NOT bundled in the base build/APK.
- Wizard (0.1.20): generic `_ensure_packs_installed()` shared by AF3 and
  NOX; `ensure_nox_installed()`; `NOX_PACKS`; Switch-Skin entry
  "סקין NOX - עברית מלאה (ניסיוני)"; first-launch skin list updated.

## Known limitations (v1, refine after device test)
- `script.embuary.info` is NOT bundled — only used by DialogVideoInfo
  (not the home), so the skin loads fine; the enhanced info dialog may
  show empty fields. Add the addon to the pack later if desired.
- telemedia→idanplus is best-effort: Israeli rows collapse to idanplus
  TV/VOD entry points, not their exact sub-catalogs (their content was
  proprietary, no equivalent).
- Base is Nexus-era Estuary on Omega: watch for per-control glitches.

---
(Original planning analysis below.)

## Goal

Add a 4th, on-demand skin to the build — the "NOX" look the user likes —
installed only when the user picks it from the wizard's **Switch Skin**
menu, exactly like Arctic Fuse 3 (AF3). It must not bloat the base build
for users who never select it.

## Key finding: what "NOX" actually is

The source is `skin.anonymoustv` (from the AnonymousTV build, downloaded
with the user's own subscription for read-only inspection). Despite the
"nox" nickname, its own `addon.xml` declares it a **modified Kodi Estuary
skin** ("Estuary MOD by Ivar Brandt", source github.com/xbmc/skin.estuary).
It is a "mega-skin" bundling several home layouts; the one the user likes
is `xml/Home_nox.xml` + `Custom_nox_main_menu.xml`.

Facts:
- Base: Estuary for **Kodi 20 (Nexus)**. Our build is **Kodi 21 (Omega)** —
  expect minor compatibility fixes.
- Size: ~24 MB zipped → fits in a SINGLE on-demand pack (unlike AF3's 4).
- Skin `<requires>`: `xbmc.gui`, `script.fentastic.helper` (already shipped).
- Also references `script.embuary.info` (~20 refs) — bundle it in the pack
  or strip those references.
- Hebrew: proper `resources/language/resource.language.he_il/strings.po`
  (196 strings) + Hebrew fonts (Heebo/Noto). RTL relies on Kodi's built-in
  language mirroring + the bundled fonts.

## MUST SCRUB before shipping (security)

`skin.anonymoustv/media/buttons/font.py` contains a side-loader:
- `gdrive()` downloads `n.zip` from `github.com/vip200/victory` into
  `addons/packages`.
- `fix()` force-enables `repository.gaia.2`.
Remove this file (and any `xbmc.service`/startup hook referencing it) and
strip all AnonymousTV branding. Do NOT ship their wizard or any phone-home.

## Skin package design (mirror AF3)

- New addon id: `skin.povil.nox` (label e.g. "POV IL — NOX"). Rebrand
  `addon.xml` id/name/provider; bump version; keep GPL/CC-BY-SA license
  + Estuary attribution (GPL requirement).
- Host one zip at `dist/Kodi-POV-IL-NOX-skin-pack.zip` (raw GitHub URL,
  same `AF3_PACK_BASE_URL` base). Include `script.embuary.info` if kept.
- Wizard wiring (resources/libs/wizard.py), copying the AF3 pattern:
  - Add a `NOX_PACKS`-style list (single pack) with `sentinel` =
    `special://home/addons/skin.povil.nox/addon.xml`, `expected_version`,
    and `addon_ids` (the skin + embuary.info if bundled).
  - Add `ensure_nox_installed()` mirroring `ensure_arctic_fuse_3_installed()`
    (download → extract.all → register+enable in Addons DB → UpdateLocalAddons).
    The DB-register step is CRITICAL: without it Kodi silently falls back
    to Estuary (the same bug AF3 hit).
  - In `build_switch_skin()`: add `'סקין NOX - ...': 'skin.povil.nox'`
    to `skin_mapping`, and call `ensure_nox_installed()` before switching,
    like the `skin.arctic.fuse.3` branch does.
  - Update the Switch-Skin notification text (currently lists 3 skins).
  - Add a `media/builds_favourites_xml/skin.povil.nox/favourites.xml`
    and ensure `update_favourites_xml_file()` handles it.

## Home menu widget mapping (approved: keep their layout, remap to POV/idanplus)

Their `Home_nox.xml` widgets target two content addons we must remap:

### A) plugin.video.novix  →  plugin.video.pov   (NEAR-MECHANICAL)
novix and POV share the SAME TMDB scheme (same `action`/`genre_id`/
`network_id`). Confirmed against our working FENtastic→POV wiring:
- `novix ?action=tmdb_movies_genres&genre_id=N&mode=build_movie_list`
  → `pov  ?action=tmdb_movies_genres&genre_id=N&mode=build_movie_list`
- `novix ?action=tmdb_tv_genres&genre_id=N&mode=build_tvshow_list`
  → `pov  ?action=tmdb_tv_genres&genre_id=N&mode=build_tvshow_list`
- `novix ?action=tmdb_movies_networks&network_id=N&mode=build_movie_list`
  → `pov  ?action=tmdb_tv_networks&network_id=N&mode=build_tvshow_list`
    (POV network browsing is under tmdb_tv_networks; verify per row)
- Genre IDs are TMDB-standard and identical, so values carry over.
Implementation: regex transform `plugin.video.novix` → `plugin.video.pov`,
then verify each distinct action/mode against POV's actual routes (cross-
check with FENtastic's proven paths — see list below).

Proven POV paths already used by FENtastic (reuse these verbatim):
- Movies root:  `?name=32028&iconImage=movies&mode=navigator.main&action=MovieList`
- Shows root:   `?name=32029&iconImage=tv&mode=navigator.main&action=TVShowList`
- Genres:       `?menu_type=movie|tvshow&mode=navigator.genres&name=32470`
- Popular movies: `?action=tmdb_movies_popular&mode=build_movie_list&name=32459`
- Trending shows: `?action=trakt_tv_trending&mode=build_tvshow_list&name=32458`
- TV premieres:  `?action=tmdb_tv_premieres&mode=build_tvshow_list&name=32460`
- Latest movies: `?action=tmdb_movies_latest_releases&mode=build_movie_list&name=32461`
- Networks (TV): `?action=tmdb_tv_networks&network_id=N&mode=build_tvshow_list`
- In-progress:   `?action=in_progress_movies&mode=build_movie_list&name=32476`
- Next episodes: `?mode=build_next_episode&name=32483`
- Connect services: `?mode=myservices` (or navigator.build_shortcut_folder_list)

### B) plugin.video.telemedia  →  plugin.video.idanplus   (BEST-EFFORT)
telemedia is AnonymousTV's proprietary Israeli/IPTV addon (modes 251/254/
261/303/312, with pastebin/m3u/Telegram sources). NO 1:1 equivalent. Map
their Israeli rows to idanplus's top entry points (idanplus uses simple
integer modes, confirmed from FENtastic favourites):
- idanplus TV:    `?mode=1&name=...&url=&module=&moredata=`
- idanplus VOD:   `?mode=2&name=...&url=&module=&moredata=`
- idanplus Radio: `?mode=3&name=...&url=&module=&moredata=`
We cannot reproduce telemedia's exact sub-catalogs; collapse the Israeli
rows to these idanplus entries. Drop any pure-IPTV/proprietary tiles that
have no idanplus equivalent.

### Other addons seen
- `plugin.video.idanplus` — already in our build (some widgets map directly).
- `watchnixtoons2`, `drax`, `flashstream`, `specialfeatures` etc. — not in
  our build; drop or point at the nearest POV equivalent.

## Staging (each stage independently verifiable)

1. Skin package: copy skin.anonymoustv → rebrand id/name → SCRUB font.py +
   branding → fix Nexus→Omega issues → zip as dist pack. (Structural verify.)
2. Widget remap: apply novix→POV transform + telemedia→idanplus in the
   NOX home XMLs; build a he_il-clean labels pass.
3. Wizard integration: NOX pack list + ensure_nox_installed() + switch_skin
   entry + favourites. (Mirror AF3, reuse its DB-register fix.)
4. Hosting + build.txt/version bumps as needed.
5. DEVICE TEST PASS (required): verify it renders, RTL correct, home widgets
   populate from POV/idanplus, switch-skin round-trips, no fallback to
   Estuary. Only after this → wide release.

## Open risks
- Nexus-based Estuary on Omega may need per-control fixes.
- POV network browsing path per-row needs verification (movies vs tv).
- RTL correctness can only be confirmed on a real device.

## Kodi 22 "Piers" readiness (checked 2026-08-27)

NOX IS OURS, and that is the thing worth being clear about before any port
discussion: `skin.povil.nox` v1.0.11 is a rebranded, scrubbed Estuary MOD that
this project hosts itself as `dist/Kodi-POV-IL-NOX-skin-pack.zip` (24.4 MB,
1647 files). Its Kodi 22 support is therefore OUR call, not a third party's --
unlike Arctic Fuse 3, which belongs to jurialmunkey and whose Piers support has
to come from upstream.

WHAT WAS CHECKED, from Kodi's own source at tags `21.3-Omega` and
`22.0b1-Piers` -- not from forum posts, which are unreachable from CI:

```
xbmc.gui            5.17.0 -> 5.18.0
                    <backwards-compatibility abi="5.17.0"/>   <-- decisive
control types       28 -> 28      nothing removed, nothing added
builtin commands    nothing removed; loadskin and playplaylist added
info labels         6 removed, 62 added
```

The back-compat line is the answer to "will it even load": Piers declares
itself compatible down to 5.17.0, and NOX, FENtastic, Estuary and Arctic Fuse 3
are all 5.17.0. Team Kodi did bump their own Estuary to 4.1.0 / gui 5.18.0, but
that is them tracking their own release, not a floor for anyone else.

Of the six info labels dropped, none reaches us: two are internal range markers
with no skin spelling, `ADDON_INFOS` was RENAMED to `ADDON_INFOS_START` (same
value, same derived constants), and of `PLAYER_CUTLIST`, `PLAYER_PROCESS` and
`SLIDESHOW_EXIF_SOFTWARE` our skins use none in a way that breaks --
`Player.Process(...)` is still translated and its family grew from 14 members
to 21. All 305 skin XML files were scanned.

TWO MEASUREMENT ERRORS WERE MADE AND CAUGHT while doing this, both worth
recording because they would have produced confident nonsense:

- A first pass reported "913 info labels removed". Piers changed the
  declaration style from `#define NAME 361` to
  `constexpr uint32_t NAME = 361;` and the regex only matched the former. The
  real number is 6.
- A first pass reported `ADDON_INFOS` "in use in 29 skin files". The pattern
  was `Addon\.\w+`, which matches every ordinary `Addon.Name` in a skin.

WHAT THIS DOES NOT PROVE. Kodi 22 could not be run here -- the Team Kodi PPAs
are stale (newest is a Kodi 21 nightly from 2023, nothing for Ubuntu 24.04) and
building from source is not viable in CI. So nothing above tests RENDERING or
runtime behaviour, which is exactly where the reports of "some skins leave the
interface unresponsive" live. Structurally nothing blocks these skins; only a
real device closes the rest.

STAGE 5 (device render/RTL test) therefore still stands, and now has a second
job: do it on Kodi 22 with a separate 13-character package id so it installs
beside both stock Kodi and the current build.
