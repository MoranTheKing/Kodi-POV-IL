"""Bumping a patcher's marker must actually reach the devices already patched.

THE BUG THIS EXISTS FOR
-----------------------
Every patcher here rewrites a file inside somebody else's add-on and leaves a
marker comment behind so it can tell "already done" from "not yet". The marker
carries a version -- AI_SUBS_MDBL_LIKE_v2 -> _v3 -- and the version is bumped
precisely when the injected code CHANGES and has to be re-applied.

pov_mdblist_like_patcher gated on the marker FAMILY and returned 'unchanged'
the moment it saw any member of it. So a device carrying v2 was told it was
already up to date, and v3 -- the actual fix -- never landed on a single
machine that had ever run v2. It reported success the whole time.

That was found by hand. This file is the machine that finds the next one.

WHY THIS IS A DYNAMIC TEST AND NOT A GREP
-----------------------------------------
The obvious static rule -- "a versioned marker must come with old-marker
handling" -- is wrong in BOTH directions, measured against stock POV 6.08.12:

  * pov_genre_icons_patcher HAS OLD_MARKERS and still never upgrades, because
    the tuple enumerates exactly one predecessor (v2). Bump v3 -> v4 and v3 is
    not in the list, so it is not recognised, so nothing happens. Every
    hand-maintained OLD_MARKERS list is a bomb with the fuse re-lit on the
    next bump; pov_movie_networks_patcher enumerates v1 and v2 and has the
    same hole at v4.
  * pov_prewarm_patcher has NO old-marker handling of any kind and upgrades
    cleanly, because its rewrite happens to consume its own marker.

So the source text does not tell you the answer. Running it does. This
simulates the bump for real: patch a pristine host, rewrite the patcher's own
marker to the next version, run it again against the host it already patched,
and look at what the device would be left holding.

  UPGRADES        old marker gone, new marker in place -- the fix lands
  NEVER-UPGRADES  second run is a no-op -- the fix reaches nobody, silently
  DOUBLE-INJECT   both markers present -- the old injected code is still live
                  alongside the new one

WHAT MAKES IT A GUARD RATHER THAN A REPORT
------------------------------------------
Of the 28 patchers with a host to measure against, 12 are NEVER-UPGRADES and 9
DOUBLE-INJECT. Failing on all 21 would make this red on day one and it would
be switched off within a week. The damage in those is also already done and
frozen: a patcher sitting at v4 that cannot upgrade is not hurting anyone NEW.

The danger is the next bump. So every marker is PINNED below with the verdict
it was measured at. Change a marker -- which is what bumping is -- and the pin
no longer matches and this fails, telling you what that patcher's upgrade path
actually does before the release goes out. Fix the upgrade path, re-measure,
re-pin. That is the whole contract, and it fires at exactly the moment the
MDBList bug was born.

A new patcher with a versioned marker must also be pinned, so the shape cannot
enter the tree unclassified.

Run:  python3 tools/test_patcher_upgrade_path.py
      POV_STOCK=/path/to/plugin.video.pov python3 tools/...   (widen coverage)
"""
import importlib
import os
import re
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, '..', 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')
LIB = os.path.normpath(LIB)

# A stock POV tree if this machine has one. The dynamic layer needs a real
# host to patch; the pin layer below does not and always runs.
STOCK_POV = os.environ.get('POV_STOCK') or (
    '/tmp/claude-0/-home-user-Kodi-POV-IL/'
    '70968383-5f01-52a3-afe7-ced1aba28071/scratchpad/pov6812/plugin.video.pov')

# --------------------------------------------------------------------------
# The pins. stem -> (verdict, every versioned marker the module holds)
#
# Measured by the simulation below against stock POV 6.08.12. 'UNPROVEN' means
# this machine had no host for that patcher, so the verdict is not known --
# those are pinned too, so that bumping one still stops here and asks for the
# measurement rather than sailing through.
#
# To re-measure everything:  python3 tools/test_patcher_upgrade_path.py --pins
# --------------------------------------------------------------------------
PINS = {}


def pin(stem, verdict, *markers):
    """One verdict per MODULE, plus every marker it was measured holding.

    The verdict describes the module, not a marker: pov_favorites_refresh_
    patcher carries four markers across two files and upgrades neither. The
    markers are the tripwire -- any change to the set means a bump.
    """
    PINS[stem] = (verdict, set(markers))


# --- upgrade cleanly: a bump reaches devices already carrying the old one ---
pin('pov_addon_window_patcher', 'UPGRADES',
    'AI_SUBS_POV_ADDON_WINDOW_v1', 'AI_SUBS_POV_IMPORT_WINDOW_v1')
pin('pov_aiostreams_patcher', 'UPGRADES',
    'AI_SUBS_POV_AIOSTREAMS_v2')
pin('pov_mdblist_like_patcher', 'UPGRADES',
    'AI_SUBS_MDBL_LIKE_v3')
pin('pov_prewarm_patcher', 'UPGRADES',
    'AI_SUBS_POV_PREWARM_v2')
pin('pov_remember_source_patcher', 'UPGRADES',
    'AI_SUBS_AUTOPICK_v7', 'AI_SUBS_REMEMBER_SOURCE_v7')
pin('pov_source_quality_patcher', 'UPGRADES',
    'AI_SUBS_QUALITY_FIX_v5')
pin('pov_subtitle_match_patcher', 'UPGRADES',
    'AI_SUBS_MATCH_v7')

# --- never upgrade: the second run is a no-op, the fix reaches nobody -------
# Bumping any of these ships a fix that lands on fresh installs only. Every
# device that ever ran the old version keeps it, and the patcher reports
# success. Before bumping one, give it a gate that recognises the marker
# FAMILY -- a prefix test, never an enumerated list -- and reverts the old
# block before re-applying. pov_mdblist_like_patcher is the worked example.
pin('kodi_playlist_timeout_patcher', 'NEVER-UPGRADES',
    'AI_SUBS_PLAYLIST_TIMEOUT_v1')
pin('pov_bookmark_refresh_patcher', 'NEVER-UPGRADES',
    'AI_SUBS_BOOKMARK_REFRESH_LAST_v1')
pin('pov_build_content_logger_patcher', 'NEVER-UPGRADES',
    'AI_SUBS_POV_BUILD_LOGGER_v2')
pin('pov_favorites_refresh_patcher', 'NEVER-UPGRADES',
    'AI_SUBS_FAV_REFRESH_MANAGE_v1', 'AI_SUBS_FAV_REFRESH_MANAGE_v2',
    'AI_SUBS_FAV_REFRESH_v2', 'AI_SUBS_FAV_REFRESH_v3')
pin('pov_genre_icons_patcher', 'NEVER-UPGRADES',
    'AI_SUBS_POV_GENRE_ICONS_v2', 'AI_SUBS_POV_GENRE_ICONS_v3')
pin('pov_mdblist_reauth_patcher', 'NEVER-UPGRADES',
    'AI_SUBS_POV_MDBL_REAUTH_v1')
pin('pov_menus_patcher', 'NEVER-UPGRADES',
    'AI_SUBS_POV_MY_LISTS_v1')
pin('pov_meta_blank_patcher', 'NEVER-UPGRADES',
    'AI_SUBS_POV_META_BLANK_v2')
pin('pov_navigator_read_patcher', 'NEVER-UPGRADES',
    'AI_SUBS_POV_NAVREAD_v1')
pin('pov_resolve_diag_patcher', 'NEVER-UPGRADES',
    'AI_SUBS_RESOLVE_DIAG_v1')
pin('pov_trakt_reauth_patcher', 'NEVER-UPGRADES',
    'AI_SUBS_POV_TRAKT_REAUTH_v1')
pin('pov_view_mode_patcher', 'NEVER-UPGRADES',
    'AI_SUBS_POV_VIEWMODE_v4')

# --- double-inject: the old block stays live beside the new one ------------
# Measured over three successive bumps: the host still compiles, and carries
# four copies of the injected block (eight where the patcher hits two sites).
# Idempotent guards just re-run; anything that APPENDS -- a context-menu row,
# a list entry -- shows up multiplied on screen.
pin('pov_cache_empty_patcher', 'DOUBLE-INJECT',
    'AI_SUBS_POV_CACHE_EMPTY_v1')
pin('pov_combined_discover_patcher', 'DOUBLE-INJECT',
    'AI_SUBS_POV_COMBINED_DISCOVER_v1')
pin('pov_debrid_resolve_patcher', 'DOUBLE-INJECT',
    'AI_SUBS_DEBRID_RESOLVE_GUARD_v1')
pin('pov_hebrew_genres_patcher', 'DOUBLE-INJECT',
    'AI_SUBS_POV_HEBREW_GENRES_v1')
pin('pov_mdblist_patcher', 'DOUBLE-INJECT',
    'AI_SUBS_MDBL_MERGE_COLLECTION_v1', 'AI_SUBS_MDBL_NONE_GUARD_v1',
    'AI_SUBS_MDBL_REDACT_v1', 'AI_SUBS_MDBL_SCROBBLE_STOP_v1',
    'AI_SUBS_MDBL_STABLE_IDS_v1', 'AI_SUBS_MDBL_SYNC_GUARD_v1',
    'AI_SUBS_MDBL_WATCHLIST_ONLY_v2', 'AI_SUBS_SORT_RECENT_DEFAULT_v1')
pin('pov_movie_networks_patcher', 'DOUBLE-INJECT',
    'AI_SUBS_POV_MOVIE_PROVIDERS_REVERT_v1',
    'AI_SUBS_POV_MOVIE_PROVIDERS_v1', 'AI_SUBS_POV_MOVIE_PROVIDERS_v2',
    'AI_SUBS_POV_MOVIE_PROVIDERS_v3')
pin('pov_services_patcher', 'DOUBLE-INJECT',
    'AI_SUBS_MYSERVICES_INJECT_v1', 'AI_SUBS_MYSERVICES_INJECT_v10',
    'AI_SUBS_MYSERVICES_INJECT_v11', 'AI_SUBS_MYSERVICES_INJECT_v12',
    'AI_SUBS_MYSERVICES_INJECT_v2', 'AI_SUBS_MYSERVICES_INJECT_v3',
    'AI_SUBS_MYSERVICES_INJECT_v4', 'AI_SUBS_MYSERVICES_INJECT_v5',
    'AI_SUBS_MYSERVICES_INJECT_v6', 'AI_SUBS_MYSERVICES_INJECT_v7',
    'AI_SUBS_MYSERVICES_INJECT_v8', 'AI_SUBS_MYSERVICES_INJECT_v9',
    'AI_SUBS_MYSERVICES_TUPLE_v12')
pin('pov_source_name_patcher', 'DOUBLE-INJECT',
    'AI_SUBS_POV_SOURCE_NAME_v3')
pin('pov_trakt_cache_empty_patcher', 'DOUBLE-INJECT',
    'AI_SUBS_POV_TRAKT_CACHE_EMPTY_v1',
    'AI_SUBS_POV_TRAKT_TABLE_CLEAR_v1', 'AI_SUBS_POV_TRAKT_TABLE_v1')

# --- no host on this machine: pinned so a bump still stops here -------------
# Not a clean bill of health -- an unmeasured patcher. Put the matching stock
# add-on where the patcher looks for it and re-run with --pins to turn one of
# these into a real verdict.
pin('af3_dialog_subtitles_patcher', 'UNPROVEN',
    'AI_SUBS_AF3_HEADER_v1')
pin('af3_discover_pov_patcher', 'UNPROVEN',
    'AI_SUBS_POV_DISCOVER_v1', 'AI_SUBS_POV_DISCOVER_v2',
    'AI_SUBS_POV_DISCOVER_v3')
pin('af3_search_pov_patcher', 'UNPROVEN',
    'AI_SUBS_POV_SEARCH_v1', 'AI_SUBS_POV_SEARCH_v2',
    'AI_SUBS_POV_SEARCH_v3')
pin('all_subs_samefile_patcher', 'UNPROVEN',
    'AI_SUBS_ALL_SUBS_SAMEFILE_v1')
pin('darksubs_embedded_insert_patcher', 'UNPROVEN',
    'AI_SUBS_EMBED_ENG_LAST_v1', 'AI_SUBS_EMBED_ENG_LAST_v2')
pin('darksubs_filename_fallback_patcher', 'UNPROVEN',
    'AI_SUBS_FILENAME_FALLBACK_v2')
pin('darksubs_picker_height_patcher', 'UNPROVEN',
    'AI_SUBS_DARKSUBS_PICKER_ITEM_HEIGHT_v1')
pin('darksubs_picker_label_patcher', 'UNPROVEN',
    'AI_SUBS_DARKSUBS_PICKER_LABEL_SCROLL_v1')
pin('darksubs_subwindow_demote_patcher', 'UNPROVEN',
    'AI_SUBS_SUBWINDOW_DEMOTE_v1')
pin('estuary_change_source_patcher', 'UNPROVEN',
    'AI_SUBS_ESTUARY_CHANGE_SOURCE_v1')
pin('favourites_personal_tiles_patcher', 'UNPROVEN',
    'AI_SUBS_FAVOURITES_BUILD_SERVICE_TILES_SEEN_v1',
    'AI_SUBS_FAVOURITES_DEBRID_NOTICE_SEEN_v1',
    'AI_SUBS_FAVOURITES_FULL_BUILD_RESEED_v1',
    'AI_SUBS_FAVOURITES_FULL_BUILD_TILES_SEEN_v2',
    'AI_SUBS_FAVOURITES_MDBLIST_RESEED_v2',
    'AI_SUBS_FAVOURITES_MDBLIST_TILES_SEEN_v1',
    'AI_SUBS_FAVOURITES_PERSONAL_RESEED_v1',
    'AI_SUBS_FAVOURITES_PERSONAL_TILES_SEEN_v2',
    'AI_SUBS_FAVOURITES_PERSONAL_TILES_v1',
    'AI_SUBS_FAVOURITES_PREMIUMIZE_RESEED_v1')
pin('fentastic_dialog_subtitles_patcher', 'UNPROVEN',
    'AI_SUBS_DIALOG_HEADER_v1')
pin('fentastic_patcher', 'UNPROVEN',
    'AI_SUBS_NOTIFICATION_WRAP_v1')
pin('nox_change_source_patcher', 'UNPROVEN',
    'AI_SUBS_NOX_CHANGE_SOURCE_v1')
pin('nox_osd_collision_patcher', 'UNPROVEN',
    'AI_SUBS_NOX_OSD_FIX_v1')
pin('skin_dialog_subtitles_patcher', 'UNPROVEN',
    'AI_SUBS_DIALOG_HEADER_v1', 'AI_SUBS_DIALOG_HEADER_v2')
pin('skin_dialog_subtitles_row_patcher', 'UNPROVEN',
    'AI_SUBS_DIALOG_ROW_HEIGHT_v1')
pin('skin_watched_poster_patcher', 'UNPROVEN',
    'AI_SUBS_WATCHED_LIST_v1', 'AI_SUBS_WATCHED_POSTER_v1')
pin('umbrella_mdblist_token_patcher', 'UNPROVEN',
    'AI_SUBS_UMB_MDBL_TOKEN_v1')
pin('umbrella_setup_patcher', 'UNPROVEN',
    'AI_SUBS_UMBRELLA_SOURCE_NAME_v1')
pin('umbrella_source_ux_patcher', 'UNPROVEN',
    'AI_SUBS_UMB_PREWARM_v1', 'AI_SUBS_UMB_QUIETCANCEL_v1')
pin('umbrella_subtitle_match_patcher', 'UNPROVEN',
    'AI_SUBS_UMB_MATCH_v2')
pin('umbrella_tmdb_apikey_patcher', 'UNPROVEN',
    'AI_SUBS_UMB_TMDB_APIKEY_v1')
pin('wizard_patcher', 'UNPROVEN',
    'AI_SUBS_LOGINIT_INJECT_v1')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


# --------------------------------------------------------------------------
# reading the tree
# --------------------------------------------------------------------------
def literal_markers(src):
    """Every AI_SUBS_..._vN name spelled out in the source."""
    return {m for m in re.findall(r'AI_SUBS[A-Za-z0-9_]+', src)
            if re.search(r'_v\d+$', m)}


def has(blob, marker):
    """Is `marker` in `blob` as a whole marker?

    Plain substring is WRONG here: AI_SUBS_MYSERVICES_INJECT_v1 is a prefix of
    ..._v12, so a naive `in` reports every old version as still present the
    moment the counter passes 9. That misread pov_services_patcher -- which
    ships INJECT_VERSION = 12 -- as carrying eleven live markers.
    """
    pat = re.escape(marker.encode('utf-8')) + rb'(?![0-9])'
    return re.search(pat, blob) is not None


def runtime_markers(stem, extra_path=None):
    """The marker strings the module actually holds once imported.

    Needed because a marker is not always a literal: pov_services_patcher,
    darksubs_patcher and fentastic_patcher build theirs from an integer
    version constant ('# AI_SUBS_..._v{0}'.format(INJECT_VERSION)), so the
    CURRENT marker appears nowhere in the source text -- only the retired ones
    do, inside OLD_MARKERS. Pinning the literals alone would leave the live
    marker of those three unpinned, which is the one that matters.
    """
    home = tempfile.mkdtemp(prefix='upgmark-')
    try:
        _install_stubs(home, extra_path)
        sys.modules.pop('resources.lib.' + stem, None)
        try:
            mod = importlib.import_module('resources.lib.' + stem)
        except Exception:
            return set()
        found = set()

        def eat(v):
            if isinstance(v, bytes):
                v = v.decode('utf-8', 'replace')
            if isinstance(v, str):
                found.update(m for m in re.findall(r'AI_SUBS[A-Za-z0-9_]+', v)
                             if re.search(r'_v\d+$', m))
            elif isinstance(v, (list, tuple, set, frozenset)):
                for x in v:
                    eat(x)
        for name in dir(mod):
            if not name.startswith('__'):
                try:
                    eat(getattr(mod, name))
                except Exception:
                    pass
        return found
    finally:
        shutil.rmtree(home, ignore_errors=True)


def patchers():
    for fn in sorted(os.listdir(LIB)):
        if 'patcher' not in fn or not fn.endswith('.py'):
            continue
        stem = fn[:-3]
        src = open(os.path.join(LIB, fn), encoding='utf-8').read()
        marks = literal_markers(src) | runtime_markers(stem)
        if marks:
            yield stem, src, sorted(marks)


# --------------------------------------------------------------------------
# running one
# --------------------------------------------------------------------------
def _install_stubs(home, extra_path=None):
    """A Kodi that patchers can run inside, rooted at `home`."""
    for name in list(sys.modules):
        if name.split('.')[0] in ('resources', 'xbmc', 'xbmcvfs', 'xbmcgui',
                                  'xbmcaddon'):
            sys.modules.pop(name, None)

    def _tp(p):
        if not isinstance(p, str):
            return p
        if p.startswith('special://home/'):
            return os.path.join(home, p[len('special://home/'):])
        if p.startswith('special://profile/'):
            return os.path.join(home, 'userdata', p[len('special://profile/'):])
        return p

    vfs = types.ModuleType('xbmcvfs')
    vfs.translatePath = _tp
    vfs.exists = os.path.exists
    sys.modules['xbmcvfs'] = vfs

    xbmc = types.ModuleType('xbmc')
    xbmc.executebuiltin = lambda *a, **k: None
    xbmc.log = lambda *a, **k: None
    xbmc.translatePath = _tp
    sys.modules['xbmc'] = xbmc

    pkg = types.ModuleType('resources')
    pkg.__path__ = []
    lib = types.ModuleType('resources.lib')
    # a real __path__ so `from . import kodi_utils` inside a patcher resolves
    lib.__path__ = ([extra_path] if extra_path else []) + [LIB]
    sys.modules['resources'] = pkg
    sys.modules['resources.lib'] = lib
    pkg.lib = lib

    ku = types.ModuleType('resources.lib.kodi_utils')
    ku.log = lambda *a, **k: None
    ku.logger = lambda *a, **k: None
    sys.modules['resources.lib.kodi_utils'] = ku
    lib.kodi_utils = ku


def _run(stem, home, extra_path=None):
    """Import the patcher fresh and call its entry point. Never raises."""
    _install_stubs(home, extra_path)
    sys.modules.pop('resources.lib.' + stem, None)
    try:
        mod = importlib.import_module('resources.lib.' + stem)
        fn = getattr(mod, 'ensure_patched', None)
        return fn() if fn else 'NO_ENTRY'
    except Exception as e:
        return 'EXC:%r' % (e,)


def _snapshot(home):
    out = {}
    for dp, _, fns in os.walk(home):
        for fn in fns:
            p = os.path.join(dp, fn)
            try:
                out[p] = open(p, 'rb').read()
            except OSError:
                pass
    return out


def _fresh_home():
    home = tempfile.mkdtemp(prefix='upgpath-')
    if os.path.isdir(STOCK_POV):
        shutil.copytree(STOCK_POV,
                        os.path.join(home, 'addons', 'plugin.video.pov'))
    return home


def bump_source(src, markers):
    """The patcher as it would look one version later.

    Two things move, because a real bump moves both: the marker literals, and
    any integer version constant a marker is built from. What deliberately
    does NOT move is a hand-written OLD_MARKERS list -- nobody remembers to
    extend it, and that omission IS the failure mode under test.
    """
    out = src
    for m in sorted(markers, key=len, reverse=True):
        n = int(re.search(r'_v(\d+)$', m).group(1))
        out = re.sub(re.escape(m) + r'(?![0-9])',
                     re.sub(r'_v\d+$', '_v%d' % (n + 1), m), out)
    out = re.sub(r'(?m)^([A-Z_]*VERSION) = (\d+)\s*$',
                 lambda g: '%s = %d' % (g.group(1), int(g.group(2)) + 1), out)
    return out


def simulate_bump(stem, src, override=None):
    """Patch a pristine host, bump the patcher's version, run it again.

    Returns (verdict, first_status, second_status).

    The second run is what a device that already carries the old version
    receives. UNBUMPABLE means the simulation could not move the marker at
    all -- that is a failure of this harness, not a verdict, and it is
    reported rather than pinned so it cannot masquerade as a measurement.
    """
    text = override if override is not None else src
    home = _fresh_home()
    try:
        s1 = _run(stem, home)
        blob1 = b''.join(_snapshot(home).values())
        landed = sorted(m for m in (literal_markers(text) | runtime_markers(stem))
                        if has(blob1, m))
        if not landed:
            return 'UNPROVEN', s1, ''

        tmp = tempfile.mkdtemp(prefix='upgmod-')
        try:
            with open(os.path.join(tmp, stem + '.py'), 'w',
                      encoding='utf-8') as f:
                f.write(bump_source(text, landed))
            # The bump has to have actually landed in the module, or the
            # "second run" is just the first run again and every verdict from
            # it is fiction. This is not paranoia: the first version of this
            # harness rewrote marker LITERALS only, so it silently failed to
            # bump the three patchers that build their marker from an integer
            # constant -- and reported a confident verdict for them anyway.
            if runtime_markers(stem, tmp) == runtime_markers(stem):
                return 'UNBUMPABLE', s1, 'the bump did not move any marker'

            s2 = _run(stem, home, extra_path=tmp)
            blob2 = b''.join(_snapshot(home).values())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        nxt = [re.sub(r'_v\d+$', '_v%d' % (int(re.search(r'_v(\d+)$', m)
                                              .group(1)) + 1), m)
               for m in landed]
        old_left = any(has(blob2, m) for m in landed)
        new_in = any(has(blob2, m) for m in nxt)
        if new_in and not old_left:
            return 'UPGRADES', s1, s2
        if new_in and old_left:
            return 'DOUBLE-INJECT', s1, s2
        if old_left:
            return 'NEVER-UPGRADES', s1, s2
        return 'LOST-PATCH', s1, s2
    finally:
        shutil.rmtree(home, ignore_errors=True)


# --------------------------------------------------------------------------
# --pins: re-measure and print a fresh table
# --------------------------------------------------------------------------
if '--pins' in sys.argv:
    for stem, src, marks in patchers():
        verdict, s1, s2 = simulate_bump(stem, src)
        print("pin('%s', '%s',\n    %s)   # %s -> %s"
              % (stem, verdict, ', '.join("'%s'" % m for m in marks),
                 str(s1)[:40], str(s2)[:40]))
    sys.exit(0)


# --------------------------------------------------------------------------
# 1. the pin layer -- runs on every machine, with or without a host tree
# --------------------------------------------------------------------------
print('=== pins: every versioned marker is classified ===')
seen = set()
for stem, src, marks in patchers():
    seen.add(stem)
    entry = PINS.get(stem)
    check('%s is pinned' % stem, entry is not None,
          'new patcher with a versioned marker -- run with --pins, read the '
          'verdict, and add it to the table')
    if not entry:
        continue
    verdict, pinned = entry
    unknown = [m for m in marks if m not in pinned]
    check('%s markers match their pins' % stem, not unknown,
          'marker(s) %s are not pinned. If this is a version BUMP: this '
          'patcher was measured %s.%s Re-measure with --pins and re-pin.'
          % (', '.join(unknown), verdict,
             '' if verdict == 'UPGRADES' else
             ' The bump will NOT reach any device already carrying the old '
             'version -- fix the upgrade path first, or the fix ships to '
             'fresh installs only.'))

stale = sorted(set(PINS) - seen)
check('no pins for patchers that no longer exist', not stale, ', '.join(stale))

# --------------------------------------------------------------------------
# 2. the dynamic layer -- only where this machine has a host to patch
# --------------------------------------------------------------------------
print()
have_pov = os.path.isdir(STOCK_POV)
print('=== simulated bump %s ===' % ('(stock POV present)' if have_pov else
                                     '(NO host tree here -- see below)'))
exercised = unproven = 0
for stem, src, marks in patchers():
    want = PINS.get(stem, ('?', ()))[0]
    if want == 'UNPROVEN' and not have_pov:
        unproven += 1
        continue
    verdict, s1, s2 = simulate_bump(stem, src)
    if verdict == 'UNPROVEN':
        unproven += 1
        continue
    exercised += 1
    check('%s: %s' % (stem, verdict), verdict == want,
          'pinned %s, measured %s (%s -> %s). An upgrade path that CHANGED '
          'without the marker changing means the host add-on moved under the '
          'patcher.' % (want, verdict, s1, s2))
check('nothing is UNBUMPABLE', 'UNBUMPABLE' not in
      [PINS.get(s, ('', ()))[0] for s, _, _ in patchers()],
      'a patcher whose version this harness cannot move is unmeasured, not '
      'safe -- teach bump_source how to bump it')

print()
print('exercised %d / unproven %d (no host on this machine)'
      % (exercised, unproven))
check('the dynamic layer actually ran on something', exercised > 0,
      'no host tree anywhere -- only the pin layer above proved anything. '
      'Set POV_STOCK to a stock plugin.video.pov to restore it.')

# --------------------------------------------------------------------------
# 3. sabotage -- both layers must be able to fail
# --------------------------------------------------------------------------
print()
print('=== sabotage ===')

# a bump must not slip past the pin layer
check('SABOTAGE: a bumped marker is not silently accepted',
      'AI_SUBS_MDBL_LIKE_v4' not in PINS['pov_mdblist_like_patcher'][1],
      'the pin table already contains the next version, so a bump would pass')

# marker presence must not be a plain substring test. This is the bug that
# made the first run of this harness read pov_services_patcher -- which is at
# INJECT_VERSION 12 -- as still carrying its v1 marker, because "..._v1" is a
# prefix of "..._v12". It reported a confident, wrong verdict.
check('SABOTAGE: _v1 is not found inside _v12',
      not has(b'x # AI_SUBS_MYSERVICES_INJECT_v12\n',
              '# AI_SUBS_MYSERVICES_INJECT_v1')
      and has(b'x # AI_SUBS_MYSERVICES_INJECT_v1\n',
              '# AI_SUBS_MYSERVICES_INJECT_v1'),
      'marker matching is prefix-blind, so every version past 9 misreads')

# the bump must move a marker that is BUILT rather than written out, or the
# three patchers that do that are measured by running them against themselves
built = "INJECT_VERSION = 12\nMARKER = '# AI_SUBS_X_v{0}'.format(INJECT_VERSION)\n"
check('SABOTAGE: a constructed marker still gets bumped',
      'INJECT_VERSION = 13' in bump_source(built, []),
      'bump_source only rewrites literals, so pov_services_patcher, '
      'darksubs_patcher and fentastic_patcher are never actually bumped')

if have_pov:
    # the simulation must be able to say NEVER-UPGRADES about a patcher that
    # is currently fine -- otherwise "UPGRADES" everywhere proves nothing.
    good = 'pov_mdblist_like_patcher'
    src = open(os.path.join(LIB, good + '.py'), encoding='utf-8').read()
    v, _, _ = simulate_bump(good, src)
    check('SABOTAGE: the healthy patcher measures UPGRADES', v == 'UPGRADES', v)

    # break exactly the thing that made it healthy: its family-prefix gate,
    # reduced to the enumerated-list shape that fools pov_genre_icons.
    crippled = src.replace(
        "_MARKER_ANY = '# AI_SUBS_MDBL_LIKE_v'",
        "_MARKER_ANY = '# AI_SUBS_MDBL_LIKE_v3'", 1)
    check('SABOTAGE: the family gate was found to cripple',
          crippled != src, 'the anchor moved -- this case is not testing '
                           'anything any more')
    if crippled != src:
        v2, _, _ = simulate_bump(good, crippled)
        check('SABOTAGE: an exact-version gate is caught', v2 != 'UPGRADES',
              'crippling the family gate still measured %s, so this test '
              'cannot tell the shapes apart' % v2)

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
