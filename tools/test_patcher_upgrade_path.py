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

A module gets the verdict of its WORST marker, because a module that applies
six patches through five entry points -- pov_mdblist_patcher does -- is only as
good as the one that reaches nobody.

  UPGRADES        old marker gone, new marker in place -- the fix lands
  NEVER-UPGRADES  second run is a no-op -- the fix reaches nobody, silently
  DOUBLE-INJECT   both markers present AND a line of real code duplicated --
                  the old behaviour is still live alongside the new
  DOUBLE-STAMP    both markers present but only the COMMENT duplicated; the
                  patcher re-checked its own output and left the code alone
  CLAIMS-PATCHED  reported success and wrote no marker, on a host that IS
                  present -- the anchor has moved and the patch is dead
  LOST-PATCH      neither marker survives -- the feature simply vanishes.
                  Never pin either of these; both are hard failures
  UNBUMPABLE      the harness could not move the version. Not a verdict, a
                  refusal to guess one

HOW BAD IS IT, GIVEN THAT THE HOSTS AUTO-UPDATE
-----------------------------------------------
Measured against POV 6.08.13 and Umbrella 6.7.82 -- the current upstream of
both -- 15 patchers are NEVER-UPGRADES and 6 DOUBLE-INJECT, out of the 36 that
have a host here.

That reads worse than it is, and the reason is worth knowing before anyone
panics at the table below. **Both hosts update themselves on the user's
device**, POV through repository.kodifitzwell and Umbrella through its own
repo. A host update REPLACES the files our markers live in, so the marker
vanishes and the patcher re-applies cleanly at whatever version it is now.
Measured marker by marker: 20 of the 21 write inside the host add-on.

So for those 20, a bump that "never upgrades" is a DELAY, not a permanent
loss: the fix lands on the host's next release. The window is real -- the
changelog promises behaviour the device does not have until then -- but it
closes by itself.

**That safety net is a DEFAULT, not a guarantee, and it is worth saying so.**
It holds only while Kodi's add-on auto-update is on. The build ships it on
(general.addonupdates = 0), but our own wizard offers "never check for
updates" as a supported choice, and anyone who takes it loses the net for all
20 at once, silently. Treat self-healing as what usually happens, never as a
reason to ship a bump that cannot upgrade.

**One has no net at all, and it is the one to fix first.**
`kodi_playlist_timeout_patcher` writes `userdata/advancedsettings.xml`, which
is Kodi's own profile data. No add-on update ever touches it. Bump that marker
and the change reaches nobody who already ran it, permanently.

It is the only one AMONG THE 21 BROKEN. It is not the only patcher in the tree
that writes outside an add-on directory: favourites_xml_patcher
(profile/favourites.xml) and hebrew_build_ui_patcher (profile/guisettings.xml)
do too. Neither is at risk today -- they read the live content, or gate on a
setting we own, rather than on a marker buried in the target -- but refactor
either toward a marker-in-content gate, which is what nearly everything else
here does, and the same permanent trap reappears with nothing watching. So:
before choosing a gate for a new patcher, look at WHERE ITS MARKER LANDS.

WHAT MAKES IT A GUARD RATHER THAN A REPORT
------------------------------------------
Failing on all 21 would make this red on day one and it would be switched off
within a week. The damage in them is also already done and frozen: a patcher
sitting at v4 that cannot upgrade is not hurting anyone NEW.

The danger is the next bump. So every marker is PINNED below with the verdict
it was measured at. Change a marker -- which is what bumping is -- and the pin
no longer matches and this fails, telling you what that patcher's upgrade path
actually does before the release goes out. Fix the upgrade path, re-measure,
re-pin. That is the whole contract, and it fires at exactly the moment the
MDBList bug was born.

A new patcher with a versioned marker must also be pinned, so the shape cannot
enter the tree unclassified.

The other 23 are UNPROVEN: no stock copy of their host on this machine (the
skins, the wizard, service.subtitles.All_Subs). That is an admission, not a
pass -- and on a machine with no host trees at all, nearly everything lands
there, so the run says PARTIAL rather than pretending.

RETIRED is its own verdict for a marker-gated module nothing calls, and those
are kept OUT of the broken counts: a patcher reaching no device at all is not
"the fix lands on fresh installs only", and counting it inflates the risk this
table describes. Two are retired today.

WHAT COUNTS AS A PATCHER HERE IS DELIBERATELY NOT A NAMING RULE.

Marker discovery is not keyed on the AI_SUBS_ prefix: that is a house
convention five wired patchers do not follow (darksubs_patcher,
darksubs_download_sub_patcher, darksubs_embedded_demote_patcher,
pov_resume_cancel_patcher, af3_home_patcher), and keying on it made all five
invisible -- not measured, not pinned, not even counted. Any SHOUTING_NAME_vN
counts now.

Module selection is not keyed on the filename either. It used to require
"patcher" in the name, and pov_torbox_url_fix.py does not have it: it is called
from service.py on every boot, rewrites POV's torbox_api.py, gates on an
exact-match marker, and measures NEVER-UPGRADES. Any module with a versioned
marker and an ensure_*/heal_* entry point is in scope.

And every entry point gets called, not just ensure_patched -- but only the
ones the service really calls. Liveness is asked of the CALL GRAPH, because
shape is not liveness: fentastic_patcher keeps a retired ensure_patched beside
its live ensure_unpatched, and calling both applies the patch and strips it in
the same pass, which read as "the anchor is dead" at a perfectly healthy
anchor. The reverse error is worse -- a false retirement drops a live patcher
out of the measured set -- so a wrapper is chased across the whole add-on, and
a module named as a bare string (service.py dispatches two patchers that way)
counts as live.

WHAT THIS STILL DOES NOT SEE, on purpose or otherwise:

  * modules gating on an UNVERSIONED marker -- six of them, including
    pov_repeat_timer_patcher, which fixes a real auth-thread bug. There is no
    version to bump, so the tripwire has nothing to hold; the risk on their
    second revision is the same, with no convention nudging anyone toward it.
  * pov_navigator_patcher, which rewrites rows in POV's navigator.db by
    comparing them byte-for-byte against a hand-maintained tuple of known old
    versions -- the enumerated-OLD_MARKERS bug in a different costume. Its
    entry points are maybe_fix_*, it has no marker string at all, and
    navigator.db lives in addon_data, so it is not shipped in POV's package
    and a POV update can never wipe it. LESS of a safety net than
    kodi_playlist_timeout_patcher, not more.
  * any patch whose target is created at runtime rather than shipped, since
    _fresh_home only copies what the stock tree contains.

Run:  python3 tools/test_patcher_upgrade_path.py
      POV_STOCK=... UMBRELLA_STOCK=... python3 tools/...   (widen coverage)
      python3 tools/test_patcher_upgrade_path.py --pins     (re-measure)

Refresh a host tree from its own repo before re-pinning -- POV's datadir is
https://kodiyashimaru.github.io/repo/<id>/<id>-<version>.zip, Umbrella's is
under umbrellaplug.github.io/matrix/zips/. Verdicts were identical on POV
6.08.12 and 6.08.13, and on Umbrella 6.7.81 and 6.7.82, so they are not
knife-edge on a single host release -- but that is a measurement, not a
guarantee for the next one.
"""
import importlib
import inspect
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

# Stock host add-ons, if this machine has them. The dynamic layer needs a real
# host to patch; the pin layer below does not and always runs.
#
# addon id -> env var to override with. Anything not found here stays UNPROVEN,
# which is an admission that the patcher was not measured -- never a pass.
_SCRATCH = ('/tmp/claude-0/-home-user-Kodi-POV-IL/'
            '70968383-5f01-52a3-afe7-ced1aba28071/scratchpad/')
STOCK = {
    'plugin.video.pov': os.environ.get('POV_STOCK') or
    _SCRATCH + 'pov6813/plugin.video.pov',
    'plugin.video.umbrella': os.environ.get('UMBRELLA_STOCK') or
    _SCRATCH + 'umb6782/plugin.video.umbrella',
}
DECLARED_HOSTS = set(STOCK)
STOCK = {k: v for k, v in STOCK.items() if os.path.isdir(v)}


def host_version(path):
    """Whatever the host add-on calls itself, for the banner.

    Both hosts auto-update on the user's device -- POV through
    repository.kodifitzwell, Umbrella through its own repo -- so a verdict is
    only worth what the tree it was measured against is worth. Printing the
    version is how a fixture that has quietly gone stale becomes visible.
    """
    try:
        head = open(os.path.join(path, 'addon.xml'), encoding='utf-8').read(400)
        return re.search(r'version="([0-9.]+)"', head).group(1)
    except Exception:
        return '?'

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
pin('umbrella_setup_patcher', 'UPGRADES',
    'AI_SUBS_UMBRELLA_SOURCE_NAME_v1')
pin('umbrella_source_ux_patcher', 'UPGRADES',
    'AI_SUBS_UMB_PREWARM_v1', 'AI_SUBS_UMB_QUIETCANCEL_v1')
pin('umbrella_subtitle_match_patcher', 'UPGRADES',
    'AI_SUBS_UMB_MATCH_v2')

# --- never upgrade: the second run is a no-op, the fix reaches nobody -------
# Bumping any of these ships a fix that lands on fresh installs only, until the
# host add-on's next release wipes the marker and the patcher re-applies. Give
# it a gate that recognises the marker FAMILY -- a prefix test, never an
# enumerated list -- and revert the old block before re-applying.
# pov_mdblist_like_patcher is the worked example.
#
# kodi_playlist_timeout_patcher is the one here with NO safety net: its marker
# goes into userdata/advancedsettings.xml, which no add-on update replaces.
#
# pov_mdblist_patcher is here on the WORST of its six markers: three upgrade
# after a fashion and three (MDBL_NONE_GUARD, MDBL_WATCHLIST_ONLY,
# SORT_RECENT_DEFAULT) reach nobody. Run --pins for the breakdown.
pin('kodi_playlist_timeout_patcher', 'NEVER-UPGRADES',
    'AI_SUBS_PLAYLIST_TIMEOUT_v1')
pin('pov_bookmark_refresh_patcher', 'NEVER-UPGRADES',
    'AI_SUBS_BOOKMARK_REFRESH_LAST_v1')
pin('pov_favorites_refresh_patcher', 'NEVER-UPGRADES',
    'AI_SUBS_FAV_REFRESH_MANAGE_v1', 'AI_SUBS_FAV_REFRESH_MANAGE_v2',
    'AI_SUBS_FAV_REFRESH_v2', 'AI_SUBS_FAV_REFRESH_v3')
pin('pov_genre_icons_patcher', 'NEVER-UPGRADES',
    'AI_SUBS_POV_GENRE_ICONS_v2', 'AI_SUBS_POV_GENRE_ICONS_v3')
pin('pov_mdblist_patcher', 'NEVER-UPGRADES',
    'AI_SUBS_MDBL_MERGE_COLLECTION_v1', 'AI_SUBS_MDBL_NONE_GUARD_v1',
    'AI_SUBS_MDBL_REDACT_v1', 'AI_SUBS_MDBL_SCROBBLE_STOP_v1',
    'AI_SUBS_MDBL_STABLE_IDS_v1', 'AI_SUBS_MDBL_SYNC_GUARD_v1',
    'AI_SUBS_MDBL_WATCHLIST_ONLY_v2', 'AI_SUBS_SORT_RECENT_DEFAULT_v1')
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
pin('pov_resume_cancel_patcher', 'NEVER-UPGRADES',
    'AI_POV_RESUME_CANCEL_v1')
pin('pov_torbox_url_fix', 'NEVER-UPGRADES',
    'AI_SUBS_TORBOX_URL_v1')
pin('pov_trakt_reauth_patcher', 'NEVER-UPGRADES',
    'AI_SUBS_POV_TRAKT_REAUTH_v1')
pin('pov_view_mode_patcher', 'NEVER-UPGRADES',
    'AI_SUBS_POV_VIEWMODE_v4')
pin('umbrella_mdblist_token_patcher', 'NEVER-UPGRADES',
    'AI_SUBS_UMB_MDBL_TOKEN_v1')

# --- double-inject: the old block stays live beside the new one ------------
# Measured over three successive bumps: the host still compiles every time, and
# carries four copies of the injected block. Most duplicate idle code -- guards
# and early returns that just re-run. pov_services_patcher is the one that
# shows: it lists every service four times in the connect-services screen.
pin('pov_cache_empty_patcher', 'DOUBLE-INJECT',
    'AI_SUBS_POV_CACHE_EMPTY_v1')
pin('pov_combined_discover_patcher', 'DOUBLE-INJECT',
    'AI_SUBS_POV_COMBINED_DISCOVER_v1')
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
pin('umbrella_tmdb_apikey_patcher', 'DOUBLE-INJECT',
    'AI_SUBS_UMB_TMDB_APIKEY_v1')

# --- double-stamp: only the marker COMMENT duplicates, the code is fine -----
# These test the injected code itself rather than trusting the marker, find it
# already correct on the second run, and re-stamp only the comment. Harmless,
# and kept as its own verdict because calling it DOUBLE-INJECT reads far worse
# than the truth and would bury the ones that really do duplicate behaviour.
pin('pov_debrid_resolve_patcher', 'DOUBLE-STAMP',
    'AI_SUBS_DEBRID_RESOLVE_GUARD_v1')
pin('pov_hebrew_genres_patcher', 'DOUBLE-STAMP',
    'AI_SUBS_POV_HEBREW_GENRES_v1')
pin('pov_movie_networks_patcher', 'DOUBLE-STAMP',
    'AI_SUBS_POV_MOVIE_PROVIDERS_REVERT_v1',
    'AI_SUBS_POV_MOVIE_PROVIDERS_v1', 'AI_SUBS_POV_MOVIE_PROVIDERS_v2',
    'AI_SUBS_POV_MOVIE_PROVIDERS_v3')

# --- retired: marker-gated, and called by nothing ---------------------------
# Kept out of the broken counts on purpose: a patcher that reaches no device is
# not "the fix lands on fresh installs only", and counting it inflates the risk
# the table describes. Still PINNED, so re-arming one trips the tripwire and
# forces a measurement first -- which is when it would start mattering.
# pov_build_content_logger_patcher's call site exists but its wrapper is
# commented out of service.py's steps tuple (and it has no compile() gate, so
# fix that before re-arming). fentastic_dialog_subtitles_patcher is referenced
# nowhere at all.
pin('fentastic_dialog_subtitles_patcher', 'RETIRED',
    'AI_SUBS_DIALOG_HEADER_v1')
pin('pov_build_content_logger_patcher', 'RETIRED',
    'AI_SUBS_POV_BUILD_LOGGER_v2')

# --- no host on this machine: pinned so a bump still stops here -------------
# Not a clean bill of health -- an unmeasured patcher. The skins, the wizard,
# and service.subtitles.All_Subs (the darksubs_* family). Put the matching
# stock add-on where the patcher looks for it and re-run with --pins to turn
# one of these into a real verdict.
pin('af3_dialog_subtitles_patcher', 'UNPROVEN',
    'AI_SUBS_AF3_HEADER_v1')
pin('af3_discover_pov_patcher', 'UNPROVEN',
    'AI_SUBS_POV_DISCOVER_v1', 'AI_SUBS_POV_DISCOVER_v2',
    'AI_SUBS_POV_DISCOVER_v3')
pin('af3_home_patcher', 'UNPROVEN',
    'POV_AF3_PLOT_AUTOSCROLL_v2', 'POV_AF3_TOUCH_CLEANUP_v1')
pin('af3_search_pov_patcher', 'UNPROVEN',
    'AI_SUBS_POV_SEARCH_v1', 'AI_SUBS_POV_SEARCH_v2',
    'AI_SUBS_POV_SEARCH_v3')
pin('all_subs_samefile_patcher', 'UNPROVEN',
    'AI_SUBS_ALL_SUBS_SAMEFILE_v1')
pin('darksubs_download_sub_patcher', 'UNPROVEN',
    'AI_DOWNLOAD_SUB_ELIF_v1', 'AI_DOWNLOAD_SUB_ELIF_v2')
pin('darksubs_embedded_demote_patcher', 'UNPROVEN',
    'AI_EMBEDDED_DEMOTE_v1', 'AI_EMBEDDED_DEMOTE_v2')
pin('darksubs_embedded_insert_patcher', 'UNPROVEN',
    'AI_SUBS_EMBED_ENG_LAST_v1', 'AI_SUBS_EMBED_ENG_LAST_v2')
pin('darksubs_filename_fallback_patcher', 'UNPROVEN',
    'AI_SUBS_FILENAME_FALLBACK_v2')
pin('darksubs_patcher', 'UNPROVEN',
    'AI_TRANSLATE_HOOK_v1', 'AI_TRANSLATE_HOOK_v2',
    'AI_TRANSLATE_HOOK_v3', 'AI_TRANSLATE_HOOK_v4')
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
pin('fentastic_patcher', 'UNPROVEN',
    'AI_SUBS_NOTIFICATION_WRAP_v1')
pin('nox_change_source_patcher', 'UNPROVEN',
    'AI_SUBS_NOX_CHANGE_SOURCE_v1')
pin('nox_osd_collision_patcher', 'UNPROVEN',
    'AI_SUBS_NOX_OSD_FIX_v1')
pin('pov_container_refresh_crash_fix', 'UNPROVEN',
    'AI_SUBS_POV_WIDGET_REFRESH_v1')
pin('skin_dialog_subtitles_patcher', 'UNPROVEN',
    'AI_SUBS_DIALOG_HEADER_v1', 'AI_SUBS_DIALOG_HEADER_v2')
pin('skin_dialog_subtitles_row_patcher', 'UNPROVEN',
    'AI_SUBS_DIALOG_ROW_HEIGHT_v1')
pin('skin_watched_poster_patcher', 'UNPROVEN',
    'AI_SUBS_WATCHED_LIST_v1', 'AI_SUBS_WATCHED_POSTER_v1')
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
# Any SHOUTING_NAME_vN. NOT 'AI_SUBS...' -- that prefix is a house convention
# most patchers happen to follow and five do not, and keying on it made those
# five invisible: not measured, not pinned, not even counted as unproven, so
# bumping one printed ALL PASS on every machine. The five are darksubs_patcher
# (AI_TRANSLATE_HOOK), darksubs_download_sub_patcher (AI_DOWNLOAD_SUB_ELIF),
# darksubs_embedded_demote_patcher (AI_EMBEDDED_DEMOTE), pov_resume_cancel_
# patcher (AI_POV_RESUME_CANCEL) and af3_home_patcher (POV_AF3_*) -- all wired,
# all wired. The docstring below even named darksubs_patcher as a case this
# file handles. It did not -- this regex threw the file away first.
_MARKER_RE = r'\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_v\d+\b'


def literal_markers(src):
    """Every versioned marker name spelled out in the source."""
    return set(re.findall(_MARKER_RE, src))


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
    version constant ('# ..._v{0}'.format(INJECT_VERSION)), so the CURRENT
    marker appears nowhere in the source text -- only the retired ones do,
    inside OLD_MARKERS. Pinning the literals alone would leave the live marker
    of those three unpinned, which is the one that matters.
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
                found.update(re.findall(_MARKER_RE, v))
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


_SOURCES = None


def _addon_sources():
    """Every .py in the add-on, so liveness can be asked of the call graph."""
    global _SOURCES
    if _SOURCES is None:
        _SOURCES = {}
        root = os.path.dirname(LIB.rstrip(os.sep))
        root = os.path.dirname(root)          # .../service.subtitles.kodipovilai
        for dp, _, fns in os.walk(root):
            if '__pycache__' in dp:
                continue
            for fn in fns:
                if fn.endswith('.py'):
                    p = os.path.join(dp, fn)
                    try:
                        _SOURCES[p] = open(p, encoding='utf-8').read()
                    except OSError:
                        pass
    return _SOURCES


def is_live(stem, name):
    """Does the add-on actually call <stem>.<name>() on a real boot?

    Shape is not liveness, and assuming it was produced a false alarm and an
    inflated count:

      * fentastic_patcher defines ensure_patched AND ensure_unpatched. Only
        ensure_unpatched is called -- 0.2.9's patch caused regressions and
        0.2.10 reverted it for good. Calling both in one pass applies the
        patch and then strips it, so no marker lands, and the run reported
        CLAIMS-PATCHED: "the anchor has moved and the patch is dead". The
        anchor is fine. Nobody calls it.
      * pov_build_content_logger_patcher's call site still exists, but the
        function holding it is commented out of service.py's steps tuple. It
        runs on no device at all, and it was being counted among the
        NEVER-UPGRADES as though it reached fresh installs.

    So: find the call, then check the function CONTAINING the call is itself
    reachable. One level of indirection is all this codebase uses, and going
    deeper would be a dead-code analyser rather than a test.

    A false RETIRED is worse than the over-counting it replaced -- it drops a
    LIVE patcher out of the measured set -- and the first cut produced three
    of them, so both ways it got that wrong are handled and the fallback errs
    toward "live":

      * the wrapper holding the call is usually called from ANOTHER file
        (darksubs_patcher is reached through dark_subs_integration), so
        reachability is asked of the whole add-on, not the one file
      * service.py dispatches the two reauth patchers by NAME, out of a tuple
        of strings, so no `stem.entry(` text exists anywhere -- see
        dispatched_by_name
    """
    own = os.path.abspath(os.path.join(LIB, stem + '.py'))
    call = re.compile(r'\b%s\.%s\s*\(' % (re.escape(stem), re.escape(name)))
    sources = _addon_sources()
    for path, text in sources.items():
        if os.path.abspath(path) == own:
            continue
        for m in call.finditer(text):
            line_start = text.rfind('\n', 0, m.start()) + 1
            if text[line_start:m.start()].lstrip().startswith('#'):
                continue
            wrappers = re.findall(r'(?m)^def (\w+)\(', text[:m.start()])
            if not wrappers:
                return True                     # called at module level
            if _reachable(wrappers[-1], sources):
                return True
    return False


def _reachable(fn_name, sources):
    """Is `fn_name` mentioned anywhere uncommented besides its own def?"""
    for text in sources.values():
        for ln in text.split('\n'):
            s = ln.strip()
            if (fn_name in s and not s.startswith('#')
                    and not s.startswith('def ' + fn_name)):
                return True
    return False


def dispatched_by_name(stem):
    """Is the module named as a bare string, i.e. imported dynamically?

    service.py holds ('pov_mdblist_reauth_patcher', 'pov_trakt_reauth_patcher')
    in a tuple and imports each by name. Matched as a WHOLE quoted string, not
    a substring: log lines like 'pov_build_content_logger_patcher: ' + status
    are not a call site, and treating them as one resurrects the one module
    that really is retired.
    """
    pat = re.compile(r'[\'"]%s[\'"]' % re.escape(stem))
    own = os.path.abspath(os.path.join(LIB, stem + '.py'))
    return any(pat.search(t) for p, t in _addon_sources().items()
               if os.path.abspath(p) != own)


def entry_points(mod, stem):
    """Every no-argument ensure_*/heal_* the add-on really calls.

    NOT just ensure_patched: pov_mdblist_patcher exposes five and service.py
    calls all five on every boot, so measuring the first gave the module a
    verdict derived from one of its six patches while three others reached
    nobody. And not every ensure_* either -- see is_live.
    """
    out, dead = [], []
    for name in sorted(dir(mod)):
        if not (name.startswith('ensure') or name.startswith('heal')):
            continue
        fn = getattr(mod, name, None)
        if not callable(fn):
            continue
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            continue
        if any(p.default is p.empty
               and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
               for p in sig.parameters.values()):
            continue
        (out if is_live(stem, name) else dead).append((name, fn))
    if not out and dead and dispatched_by_name(stem):
        # Imported by name: there is no text saying WHICH entry point is
        # called, so assume all of them. Measuring a dead one costs a wrong
        # label; missing a live one costs the whole point of the file.
        return dead, []
    return out, dead


def patchers():
    """Every module that rewrites a foreign file behind a versioned marker.

    Selected by SHAPE, not by filename. The filter used to be `'patcher' in
    fn`, which is a naming convention -- and pov_torbox_url_fix.py does not
    follow it: it is called from service.py on every boot, rewrites POV's
    torbox_api.py, and gates on '# AI_SUBS_TORBOX_URL_v1' with an exact-match
    early return. It was invisible here, and the family is growing.
    """
    for fn in sorted(os.listdir(LIB)):
        if not fn.endswith('.py') or fn.startswith('_'):
            continue
        stem = fn[:-3]
        src = open(os.path.join(LIB, fn), encoding='utf-8').read()
        if not re.search(r'(?m)^def (ensure|heal)\w*\(', src):
            continue
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
        """Every special:// form lands inside `home`, without exception.

        Enumerating just home/ and profile/ and passing the rest through
        unchanged is not a smaller version of this -- it is a hole. A patcher
        handed back an untranslated 'special://...' writes it as a RELATIVE
        path, so it lands in the current working directory. That is how a run
        of this harness created 'special:/userdata/favourites.xml' inside the
        repo and very nearly committed it.
        """
        if not isinstance(p, str) or not p.startswith('special://'):
            return p
        rest = p[len('special://'):]
        head, _, tail = rest.partition('/')
        # `head` is neutralised by being pasted into a literal directory name,
        # but `tail` is not: special://home/../../x would climb out of the temp
        # home and write into the repo. No patcher builds such a path today;
        # this costs one line and removes the question.
        tail = os.path.normpath('/' + tail).lstrip(os.sep)
        if head == 'home':
            return os.path.join(home, tail)
        if head in ('profile', 'masterprofile', 'userdata'):
            return os.path.join(home, 'userdata', tail)
        return os.path.join(home, '_special_' + head, tail)

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
    """Import the patcher fresh and call EVERY entry point. Never raises.

    Every one, because the service does: a module's verdict has to cover all
    the patches it applies, not whichever one happens to be called
    ensure_patched.
    """
    _install_stubs(home, extra_path)
    sys.modules.pop('resources.lib.' + stem, None)
    try:
        mod = importlib.import_module('resources.lib.' + stem)
        eps, dead = entry_points(mod, stem)
        if not eps:
            return 'RETIRED' if dead else 'NO_ENTRY'
        out = []
        for name, fn in eps:
            try:
                out.append('%s=%s' % (name, fn()))
            except Exception as e:
                out.append('%s=EXC:%r' % (name, e))
        return out[0].split('=', 1)[1] if len(out) == 1 else ', '.join(out)
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
    for addon_id, path in STOCK.items():
        shutil.copytree(path, os.path.join(home, 'addons', addon_id))
    return home


def bump_source(src, markers, versions=False):
    """The patcher as it would look one version later.

    Marker literals always move. Integer version constants move only when
    asked, because the regex for them is necessarily loose (any
    ^SOMETHING_VERSION = <int>) and would happily bump a constant that has
    nothing to do with a marker. simulate_bump asks only after finding that
    rewriting literals moved nothing, which is exactly the constructed-marker
    case and nothing else.

    What deliberately does NOT move is a hand-written OLD_MARKERS list --
    nobody remembers to extend it, and that omission IS the failure mode
    under test.
    """
    out = src
    for m in sorted(markers, key=len, reverse=True):
        n = int(re.search(r'_v(\d+)$', m).group(1))
        out = re.sub(re.escape(m) + r'(?![0-9])',
                     re.sub(r'_v\d+$', '_v%d' % (n + 1), m), out)
    if versions:
        out = re.sub(r'(?m)^([A-Z_]*VERSION) = (\d+)\s*$',
                     lambda g: '%s = %d' % (g.group(1), int(g.group(2)) + 1),
                     out)
    return out


def _code_duplicated(before, after, markers):
    """Did a line of real CODE get duplicated, or only a marker comment?

    A patcher whose marker sits apart from the code it injects can re-stamp
    the comment on a bump while the injected code stays correct and singular
    -- pov_movie_networks_patcher tests the rewritten query text itself, finds
    it already right, and touches nothing else. Calling that the same thing as
    pov_services_patcher appending a fourth copy of every service row is a
    verdict that reads far worse than the truth.

    A marker line is identified by CONTAINING A MARKER, not by looking like a
    Python comment. `#` alone would miss an XML host's <!-- ..._v1 --> and
    misread a harmless re-stamp there as duplicated behaviour; and there is no
    length floor, because `break` duplicating is not less real than a long
    line duplicating.
    """
    from collections import Counter
    fam = {re.sub(r'_v\d+$', '', m) for m in markers}

    def code_lines(blob):
        out = []
        for ln in blob.decode('utf-8', 'replace').split('\n'):
            s = ln.strip()
            if not s or s.startswith('#') or any(f in s for f in fam):
                continue
            out.append(s)
        return Counter(out)
    b, a = code_lines(before), code_lines(after)
    return any(a[k] > b.get(k, 0) for k in a)


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
    base = None
    if override is not None:
        # An overridden source must be the one that gets IMPORTED too, or
        # `landed` and the UNBUMPABLE check below are computed from the
        # pristine file on disk while the run uses the override. Harmless for
        # today's one caller, which edits no marker text -- and a silent trap
        # for the first override that touches a constructed marker.
        base = tempfile.mkdtemp(prefix='upgbase-')
        with open(os.path.join(base, stem + '.py'), 'w', encoding='utf-8') as f:
            f.write(text)
    try:
        s1 = _run(stem, home, extra_path=base)
        if s1 == 'RETIRED':
            # Defined, marker-gated, and called by nothing. Pinned so that
            # re-arming it trips the tripwire and forces a measurement, but
            # kept out of the broken counts: a patcher that reaches no device
            # is not "the fix lands on fresh installs only".
            return 'RETIRED', s1, ''
        snap1 = _snapshot(home)
        blob1 = b''.join(snap1.values())
        landed = sorted(m for m in (literal_markers(text)
                                    | runtime_markers(stem, base))
                        if has(blob1, m))
        if not landed:
            # "Nothing landed" has two very different causes and they were
            # both called UNPROVEN, with diagnostics that blamed the fixture.
            # A patcher that REPORTS 'patched' and leaves no marker on a host
            # that is present has stopped applying -- the anchor moved under
            # it -- and that is the single most useful thing this file can
            # say. It is not a missing stock tree.
            # Read the RESULTS, not the whole status string: _run reports
            # 'ensure_patched=no_fentastic', and a substring test on that
            # matches the function NAME and calls a patcher with no host
            # installed a liar.
            results = [part.split('=', 1)[-1] for part in str(s1).split(', ')]
            if STOCK and any(r.startswith('patched') or r == 'repatched'
                             for r in results):
                return 'CLAIMS-PATCHED', s1, 'reported success, wrote no marker'
            return 'UNPROVEN', s1, ''

        # A FRESH directory per variant, never a rewrite in place. Writing two
        # variants to the same path is how pov_services_patcher came back
        # UNBUMPABLE: the literal-only and version-bumped sources differ by one
        # digit, so same size, and written in the same second, so same mtime --
        # and Python served the first one's cached bytecode for the second.
        tmps = []

        def variant(**kw):
            d = tempfile.mkdtemp(prefix='upgmod-')
            tmps.append(d)
            with open(os.path.join(d, stem + '.py'), 'w',
                      encoding='utf-8') as f:
                f.write(bump_source(text, landed, **kw))
            return d
        try:
            use = variant()
            # The bump has to have actually landed in the module, or the
            # "second run" is just the first run again and every verdict from
            # it is fiction. This is not paranoia: the first version of this
            # harness rewrote marker LITERALS only, so it silently failed to
            # bump the three patchers that build their marker from an integer
            # constant -- and reported a confident verdict for them anyway.
            # EVERY landed marker has to have moved, not merely one of them.
            # An all-or-nothing set comparison lets a module holding one
            # literal and one constructed marker escape escalation: the
            # literal moves, the sets differ, and the constructed one is then
            # "measured" against an unchanged copy of itself.
            def unmoved(d):
                after = runtime_markers(stem, d)
                return [m for m in landed if m in after]
            if unmoved(use):
                # constructed marker: the version lives in an int constant
                use = variant(versions=True)
                if unmoved(use):
                    return ('UNBUMPABLE', s1,
                            'still holding %s after the bump' % unmoved(use))

            s2 = _run(stem, home, extra_path=use)
            snap2 = _snapshot(home)
            blob2 = b''.join(snap2.values())
        finally:
            for d in tmps:
                shutil.rmtree(d, ignore_errors=True)

        # PER MARKER, then the worst one -- not `any()` over the whole set.
        # pov_mdblist_patcher applies five separate patches; two of them never
        # upgrade and the rest do. An any()-based verdict labelled the module
        # DOUBLE-INJECT, which is the kinder of the two, and the two that
        # reach nobody were invisible inside a pin that looked like it covered
        # them. The worst behaviour in a module is the module's behaviour.
        rank = {'UPGRADES': 0, 'DOUBLE': 1, 'NEVER-UPGRADES': 2,
                'LOST-PATCH': 3}
        per = []
        for m in landed:
            n = int(re.search(r'_v(\d+)$', m).group(1))
            nxt = re.sub(r'_v\d+$', '_v%d' % (n + 1), m)
            old, new = has(blob2, m), has(blob2, nxt)
            per.append('UPGRADES' if new and not old else
                       'DOUBLE' if new else
                       'NEVER-UPGRADES' if old else 'LOST-PATCH')
        raw = max(per, key=rank.__getitem__)
        worst = raw
        if raw == 'DOUBLE':
            worst = ('DOUBLE-INJECT' if _code_duplicated(blob1, blob2, landed)
                     else 'DOUBLE-STAMP')
        if len(set(per)) > 1:
            # Name the markers that behave differently from the verdict, so a
            # module carrying five patches does not hide which of them is the
            # one that reaches nobody.
            s2 = '%s [also %s]' % (s2, ' '.join(
                '%s=%s' % (m.rsplit('_v', 1)[0].replace('AI_SUBS_', ''), p)
                for m, p in zip(landed, per) if p != raw))
        return worst, s1, s2
    finally:
        shutil.rmtree(home, ignore_errors=True)
        if base:
            shutil.rmtree(base, ignore_errors=True)


def main():
    """The suite. Guarded so the helpers above can be imported and
    reused: without this, `import test_patcher_upgrade_path` runs every
    patcher twice and then calls sys.exit() in the caller's face."""
    # --------------------------------------------------------------------------
    # --pins: re-measure and print a fresh table
    # --------------------------------------------------------------------------
    if '--pins' in sys.argv:
        for stem, src, marks in patchers():
            verdict, s1, s2 = simulate_bump(stem, src)
            was = PINS.get(stem, ('', ()))[0]
            # Re-measuring on a machine without the host turns a real verdict into
            # UNPROVEN. Pasted over the table that is a silent DOWNGRADE: a patcher
            # known to be broken becomes permanently unchecked, and nothing says
            # so. Shout, rather than emit a line that looks like a measurement.
            if verdict == 'UNPROVEN' and was not in ('', 'UNPROVEN'):
                print('# !! DO NOT PASTE: %s was measured %s. There is no host for'
                      '\n# !! it here, so this is not a re-measurement, it is a'
                      ' downgrade.\n# !! Point its *_STOCK env var at a stock tree'
                      ' and run --pins again.' % (stem, was))
            # s2 is NOT truncated: it carries the "[also ...]" breakdown for a
            # module whose markers disagree, which is the most informative
            # thing this tool prints and was being cut off at 40 characters.
            print("pin('%s', '%s',\n    %s)   # %s -> %s"
                  % (stem, verdict, ', '.join("'%s'" % m for m in marks),
                     str(s1)[:60], s2))
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
    have_pov = bool(STOCK)
    print('=== simulated bump %s ===' % (
        'against ' + ', '.join('%s %s' % (k.rsplit('.', 1)[-1], host_version(v))
                               for k, v in sorted(STOCK.items()))
        if have_pov else '(NO host tree here -- see below)'))
    measured = set()
    unproven = 0
    for stem, src, marks in patchers():
        want = PINS.get(stem, ('?', ()))[0]
        if want == 'UNPROVEN' and not have_pov:
            unproven += 1
            continue
        verdict, s1, s2 = simulate_bump(stem, src)
        if verdict == 'UNPROVEN':
            unproven += 1
            continue
        measured.add(stem)
        check('%s: %s' % (stem, verdict), verdict == want,
              'pinned %s, measured %s (%s -> %s). An upgrade path that CHANGED '
              'without the marker changing means the host add-on moved under the '
              'patcher.' % (want, verdict, s1, s2))

    pinned_verdicts = [PINS.get(s, ('', ()))[0] for s, _, _ in patchers()]
    check('nothing is UNBUMPABLE', 'UNBUMPABLE' not in pinned_verdicts,
          'a patcher whose version this harness cannot move is unmeasured, not '
          'safe -- teach bump_source how to bump it')
    check('nothing is LOST-PATCH', 'LOST-PATCH' not in pinned_verdicts,
          'a bump makes the patch vanish from the host entirely -- the feature '
          'stops existing. Never pin this; fix it')

    # The old version of this asked only "did the dynamic layer run on ANYTHING",
    # which kodi_playlist_timeout_patcher satisfies forever: it writes Kodi's own
    # userdata and so needs no stock add-on at all. On a machine with no host trees
    # it was 1 exercised out of 32 measurable -- and a cheerful ALL PASS.
    #
    # What matters is whether every pin CLAIMING a measured verdict was re-checked.
    claimed = {s for s, (v, _) in PINS.items() if v != 'UNPROVEN'}
    skipped = sorted(claimed - measured)
    print()
    print('re-measured %d of %d pinned verdicts / %d unproven here'
          % (len(measured), len(claimed), unproven))
    if skipped:
        print('NOT RE-MEASURED (%d): %s' % (len(skipped), ', '.join(skipped)))
    # Strict only when every host this table was built against is present --
    # otherwise a fresh clone is red on arrival and gets switched off. Without them
    # the run says loudly that it is partial, and the pin layer above still catches
    # the thing this file exists for.
    FULL_HOSTS = set(STOCK) == set(DECLARED_HOSTS)
    if FULL_HOSTS:
        check('every pinned verdict was re-measured', not skipped,
              'both hosts are present, so a pin that could not be re-measured is '
              'a harness regression, not a missing fixture')
    elif skipped:
        print('PARTIAL RUN -- those %d were NOT verified here, only their markers '
              'were checked for a bump.\n    Set POV_STOCK and UMBRELLA_STOCK to '
              'make this run mean what it says.' % len(skipped))

    # --------------------------------------------------------------------------
    # 3. sabotage -- both layers must be able to fail
    # --------------------------------------------------------------------------
    print()
    print('=== hygiene: the harness wrote nothing outside its temp homes ===')
    REPO = os.path.normpath(os.path.join(HERE, '..'))
    strays = sorted(n for d in (os.getcwd(), REPO, HERE)
                    for n in os.listdir(d) if n.startswith('special:'))
    check('no special:// path escaped into the tree', not strays,
          'found %s -- a patcher was handed an untranslated special:// path and '
          'wrote it relative to the working directory' % ', '.join(strays))

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

    # A marker that is BUILT rather than written out moves only on the second,
    # escalated pass. Both halves matter: the literal pass must NOT touch the
    # version constant (its regex is loose enough to hit an unrelated
    # SOMETHING_VERSION), and the escalation must fire when the literal pass
    # moved nothing. Without the escalation, pov_services_patcher,
    # darksubs_patcher and fentastic_patcher get "measured" by running them
    # against an identical copy of themselves.
    built = ("INJECT_VERSION = 12\n"
             "MARKER = '# AI_SUBS_X_v{0}'.format(INJECT_VERSION)\n")
    check('SABOTAGE: the literal pass leaves version constants alone',
          'INJECT_VERSION = 12' in bump_source(built, []),
          'an unrelated SOMETHING_VERSION constant would be bumped too')
    check('SABOTAGE: the escalated pass moves a constructed marker',
          'INJECT_VERSION = 13' in bump_source(built, [], versions=True))
    check('SABOTAGE: the escalation actually fires in the real path',
          PINS['pov_services_patcher'][0] != 'UNBUMPABLE',
          'the constructed-marker patcher fell back to unmeasured')

    # A marker that is not spelled AI_SUBS_* must still be found. Keying on
    # that prefix made five wired patchers invisible -- never measured, never
    # pinned, not even counted -- so bumping one printed ALL PASS everywhere.
    check('SABOTAGE: a non-AI_SUBS marker is still discovered',
          'AI_TRANSLATE_HOOK_v4' in PINS['darksubs_patcher'][1]
          and 'POV_AF3_TOUCH_CLEANUP_v1' in PINS['af3_home_patcher'][1],
          'marker discovery is keyed on a house-convention prefix again')

    # A module is selected by SHAPE, not by having "patcher" in its filename.
    # pov_torbox_url_fix.py is called from service.py on every boot, rewrites
    # POV's torbox_api.py behind an exact-match marker gate, and measures
    # NEVER-UPGRADES -- and the filename filter hid it completely.
    check('SABOTAGE: a rewriter without "patcher" in its name is covered',
          'pov_torbox_url_fix' in PINS,
          'the file filter is back to matching on the filename')

    # Every entry point, not just ensure_patched. pov_mdblist_patcher applies
    # six patches through five entry points; three of them reach nobody, and
    # calling only the first gave the module a kinder verdict that hid them.
    check('SABOTAGE: every ensure_*/heal_* entry point is called',
          PINS['pov_mdblist_patcher'][0] == 'NEVER-UPGRADES',
          'the module is back to being judged on ensure_patched alone')

    # The status string now reads "ensure_patched=no_fentastic", so a naive
    # substring test for "patched" matches the function NAME and calls a
    # patcher with no host installed a liar.
    check('SABOTAGE: CLAIMS-PATCHED reads the result, not the function name',
          PINS['fentastic_patcher'][0] == 'UNPROVEN',
          'an entry-point name is being mistaken for a result')

    # Liveness comes from the call graph, not from a function's name.
    # fentastic_patcher defines ensure_patched (dead -- 0.2.10 reverted that
    # patch for good) and ensure_unpatched (live). Calling both applies the
    # patch and immediately strips it, so nothing lands and the run reported
    # CLAIMS-PATCHED at a perfectly healthy anchor.
    check('SABOTAGE: a retired entry point is not called',
          not is_live('fentastic_patcher', 'ensure_patched')
          and is_live('fentastic_patcher', 'ensure_unpatched'),
          'liveness is back to trusting the function name')

    # ...and the two ways that first went wrong, both of which produced a
    # FALSE retirement, which drops a live patcher out of the measured set.
    check('SABOTAGE: a wrapper called from another file counts as live',
          is_live('darksubs_patcher', 'ensure_patched'),
          'reachability is being asked of one file again -- darksubs_patcher '
          'is reached through dark_subs_integration')
    check('SABOTAGE: dispatch by module name counts as live',
          dispatched_by_name('pov_mdblist_reauth_patcher')
          and not dispatched_by_name('pov_build_content_logger_patcher'),
          'either the reauth pair went dead, or a log line containing the '
          'module name is being read as a call site')

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
    # "ALL PASS" on a run that re-measured 1 verdict out of 33 is the exact
    # lie this file exists to stop telling. Say which it was.
    print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else
          'ALL PASS' if not skipped else
          'ALL PASS -- PARTIAL: %d of %d verdicts unverified here (pin layer '
          'only)' % (len(skipped), len(claimed)))
    sys.exit(1 if FAIL else 0)


if __name__ == '__main__':
    main()
