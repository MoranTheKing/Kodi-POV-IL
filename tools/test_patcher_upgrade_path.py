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
both -- 15 patchers are NEVER-UPGRADES and 6 DOUBLE-INJECT, out of the 40
that can be measured here.

That reads worse than it is, and the reason is worth knowing before anyone
panics at the table below. **Both hosts update themselves on the user's
device**, POV through repository.kodifitzwell and Umbrella through its own
repo. A host update REPLACES the files our markers live in, so the marker
vanishes and the patcher re-applies cleanly at whatever version it is now.
Measured marker by marker: 19 of the 21 write inside the host add-on.

So for those 19, a bump that "never upgrades" is a DELAY, not a permanent
loss: the fix lands on the host's next release. The window is real -- the
changelog promises behaviour the device does not have until then -- but it
closes by itself.

**That safety net is a DEFAULT, not a guarantee, and it is worth saying so.**
It holds only while Kodi's add-on auto-update is on. The build ships it on
(general.addonupdates = 0), but our own wizard offers "never check for
updates" as a supported choice, and anyone who takes it loses the net for all
19 at once, silently. Treat self-healing as what usually happens, never as a
reason to ship a bump that cannot upgrade.

**TWO have no net at all, and they are the ones to fix first.**
`kodi_playlist_timeout_patcher` writes `userdata/advancedsettings.xml`, Kodi's
own profile data, and `pov_mdblist_patcher` writes `_lists_sort_recent_v1`
into OUR OWN addon settings. No add-on update ever touches either. Bump one of
those markers and the change reaches nobody who already ran it, permanently.

(That was "one" until the Kodi stub grew a real settings store: before it, the
second one could not be observed landing at all. The count is a measurement,
and it moved when the instrument improved.)

They are the two AMONG THE 21 BROKEN. They are not the only patchers in the
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

The other 42 are UNPROVEN, for two different reasons, and neither is a pass:
no stock copy of the host on this machine (the skins, the wizard,
service.subtitles.All_Subs), or nothing here can CALL the code -- service.py's
boot migrations and the three lib modules with no ensure_*/heal_* are pinned
but not runnable. On a machine with no host trees at all nearly everything
lands here, so the run says PARTIAL rather than pretending. Every host this
tree patches now has a key and an env var, so "unmeasured here" is a missing
directory rather than a host with nowhere to point at it.

--pins also prints `[never landed: ...]` for a pinned marker the run never saw
written. Most are retired predecessors, which is expected on a pristine host --
but AI_SUBS_MDBL_REDACT_v1 is a phantom: declared in pov_mdblist_patcher and
never written by the code it nominally gates, which really uses an unversioned
sentinel. Those used to vanish from the verdict silently.

RETIRED is its own verdict for a marker-gated module nothing calls, and those
are kept OUT of the broken counts: a patcher reaching no device at all is not
"the fix lands on fresh installs only", and counting it inflates the risk this
table describes. Two are retired today.

WHAT COUNTS AS A PATCHER HERE IS DELIBERATELY NOT A NAMING RULE.

Marker discovery assumes nothing about how a marker is SPELLED, because four
separate assumptions each hid live, shipping patchers:

  * not the AI_SUBS_ prefix -- five patchers do not use it
  * not SHOUTING_CASE -- wizard_self_healer's is '.ai_subs_wizard_healed_v4'
  * not "_vN at the end" -- af3_discover_pov_patcher ships
    'AI_SUBS_POV_DISCOVER_v6_unified', and the trailing word meant the module
    was pinned on its DEAD v1/v2/v3 predecessors, so a bump of the live marker
    tripped nothing. That module also carries the enumerated-OLD_MARKERS shape
    this file warns about, so the regex was hiding the very bug it hunts.
  * not "_vN" at all -- darksubs_opensubtitles_patcher's whole marker is
    'OPENSUBTITLES_SEARCH_FALLBACK_VERSION = 4'

  * not even "in the host's file" -- a whole second convention keeps a
    versioned flag in OUR OWN addon's Kodi settings to record that a one-time
    change already ran. Those all start with an underscore, which \b can never
    anchor before, so they were invisible. That convention has NO safety net
    at all: our own settings are cleared by nothing, ever, so a bump that
    cannot upgrade never recovers -- unlike a marker in a host add-on, which
    the host's next release wipes. There are 29 of them in the table, the
    biggest cluster in service.py rather than in any patcher.

  * not even "name and version in one string" -- the shape already PROVEN in
    production splits them: CACHE_RTL_FIX_VERSION = '7' beside
    set_setting('_rtl_fix_done', CACHE_RTL_FIX_VERSION). Neither literal
    carries both halves and the joined text exists nowhere, so no
    single-string search could see it. That gate has been bumped 4->5 and
    5->6 in shipped releases, each time for exactly the reason this file
    exists, and its own comment says the constant "must be bumped whenever a
    new repair is added here, or every existing install skips the backfill
    forever". The CALL SITE is read instead: a two-argument set_setting whose
    key and value both resolve to module-level constants becomes "key=value".
    Only keys starting with _ count -- set_setting('chunk_lines', '50') is a
    default, not a version gate, and tripping the pin when someone retunes a
    default is the kind of noise that gets a test switched off.

  * not "in one of our modules" -- a PAYLOAD file ships the version as CODE.
    darksubs_opensubtitles_patcher gates on the text
    'OPENSUBTITLES_SEARCH_FALLBACK_VERSION = 4' while the file it copies
    carries that same line as a real assignment, in resources/patches/, a
    SIBLING of resources/lib. Two hand-synced copies with nothing linking
    them: bump the one that ships and the gate keeps matching the old text on
    every device that already has it, forever. The whole add-on is walked now,
    and a payload's source is read as raw text.
  * not "written anywhere at all" -- af3_home_patcher's
    PATCH_VERSION = '2026-06-01-pov-home-v21' is a gate in its own right,
    written into marker FILES whose entire content is the version. A
    module-level NAME_VERSION with digits in it counts on sight.

What IS assumed: a marker is TEXT, so the search is scoped to STRING LITERALS.
That is what makes the loose shape safe -- an ordinary api_v2 identifier lives
in code, not in a string. And the Kodi stub carries a real settings store
backed by a file under the temp home, so a settings marker is observable in
the snapshot exactly like any other write.

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

  * modules gating on an UNVERSIONED marker -- 23 of them carry an
    ensure_*/heal_* entry point and produce no discoverable marker at all,
    among them pov_repeat_timer_patcher (which fixes a real auth-thread bug),
    idanplus_channels_patcher and favourites_xml_patcher. There is no version
    to bump, so the tripwire has nothing to hold; the risk on their second
    revision is the same, with no convention nudging anyone toward it. This
    said "six" for four rounds, which was wrong by nearly 4x and understated
    the exposure.
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
import ast
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
ADDON = os.path.normpath(os.path.join(LIB, '..', '..'))

# Stock host add-ons, if this machine has them. The dynamic layer needs a real
# host to patch; the pin layer below does not and always runs.
#
# EVERY host this tree patches gets an entry, not just the two that happen to
# be cached here. When it was a hardcoded pair, seven other hosts could not be
# measured on any machine under any environment -- there was no key to point at
# them, so supplying one meant editing this file. Among the unreachable was
# skin.arctic.fuse.3, host to af3_discover_pov_patcher, which the notes below
# call the highest-risk shape in the tree.
#
# A host with no tree here leaves its patchers UNPROVEN: an admission that they
# were not measured, never a pass.
_SCRATCH = ('/tmp/claude-0/-home-user-Kodi-POV-IL/'
            '70968383-5f01-52a3-afe7-ced1aba28071/scratchpad/')
HOSTS = {
    'plugin.video.pov': ('POV_STOCK', _SCRATCH + 'pov6813/plugin.video.pov'),
    'plugin.video.umbrella': ('UMBRELLA_STOCK',
                              _SCRATCH + 'umb6782/plugin.video.umbrella'),
    'skin.arctic.fuse.3': ('AF3_STOCK', ''),
    'skin.arctic.zephyr.2': ('AZ2_STOCK', ''),
    'skin.fentastic': ('FENTASTIC_STOCK', ''),
    'skin.estuary': ('ESTUARY_STOCK', ''),
    'skin.povil.nox': ('NOX_STOCK', ''),
    'service.subtitles.All_Subs': ('ALLSUBS_STOCK', ''),
    'plugin.program.kodipovilwizard': ('WIZARD_STOCK', ''),
    # 4.0.2 is what devices self-update to; GetYouTube is byte-identical
    # to the 3.9.1 the build ships, so either measures the same verdict.
    'plugin.video.idanplus': ('IDANPLUS_STOCK',
                              _SCRATCH + 'idanplus402/plugin.video.idanplus'),
    'service.subtitles.all_subs_plus': ('ALLSUBS_PLUS_STOCK', ''),
}
DECLARED_HOSTS = set(HOSTS)
STOCK = {}
for _id, (_env, _default) in HOSTS.items():
    _p = os.environ.get(_env) or _default
    if _p and os.path.isdir(_p):
        STOCK[_id] = _p


def host_version(path):
    """Whatever the host add-on calls itself, for the banner.

    Both hosts auto-update on the user's device -- POV through
    repository.kodifitzwell, Umbrella through its own repo -- so a verdict is
    only worth what the tree it was measured against is worth. Printing the
    version is how a fixture that has quietly gone stale becomes visible.

    ANCHOR ON `<addon`, NEVER ON A BARE version=. The obvious search finds the
    `<?xml version="1.0"?>` prologue first and reports the host as 1.0 --
    HANDOFF.md records that exact mistake being made in build_full_build.py,
    and this function had it too. It went unnoticed because POV's and
    Umbrella's addon.xml have no prologue; idanplus's does, and reported 1.0
    for a 4.0.2 tree the moment it was added.
    """
    try:
        head = open(os.path.join(path, 'addon.xml'),
                    encoding='utf-8-sig').read(600)
        m = re.search(r'<addon[^>]*?version="([0-9.]+)"', head, re.S)
        return m.group(1) if m else '?'
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
pin('build_icons_patcher', 'UPGRADES',
    '_tiles_refresh_gen=2')
pin('idanplus_youtube_id_patcher', 'UPGRADES',
    'AI_SUBS_IDAN_YT_ID_v1')
pin('hebrew_build_ui_patcher', 'UPGRADES',
    '_PREFS_SEED_VERSION=v1', '_subtitle_outline_migration_v1',
    '_ui_prefs_seeded=v1')
pin('pov_addon_window_patcher', 'UPGRADES',
    'AI_SUBS_POV_ADDON_WINDOW_v1', 'AI_SUBS_POV_IMPORT_WINDOW_v1')
pin('pov_aiostreams_patcher', 'UPGRADES',
    'AI_SUBS_POV_AIOSTREAMS_v2')
pin('pov_debrid_error_log_patcher', 'UPGRADES',
    'AI_SUBS_POV_DEBRID_ERRLOG_v1')
pin('pov_directory_timing_patcher', 'UPGRADES',
    'AI_SUBS_POV_DIRTIMING_v3')
pin('pov_debrid_timeout_patcher', 'UPGRADES',
    'AI_SUBS_POV_DEBRID_TIMEOUT_v1')
pin('addon_autoupdate_repair', 'UPGRADES',
    '_MODE_SEED_VERSION=v1', '_addon_update_mode_seeded=v1')
pin('pov_debrid_unbound_guard_patcher', 'UPGRADES',
    'AI_SUBS_POV_DEBRID_UNBOUND_v1')
# NEVER-UPGRADES on purpose, and STILL harmless now that a v2 exists -- but
# the reason has changed, so the old one ("there is no v2 to migrate to") is
# gone rather than left standing next to a v2.
#
# WHY A v1 DEVICE IS NOT STRANDED. The marker lives inside POV's own
# sources.py. A device reaches the shape v2 is for by POV AUTO-UPDATING, and
# that replaces sources.py wholesale -- so the v1 marker leaves with the file
# and v2 applies to a clean copy. The only device that keeps v1 is one still on
# POV <= 6.08.15, where the v1 edit is the CORRECT one for the shape it has.
# Nobody is left carrying a patch that does not fit their POV.
#
# Re-measured for 6.09.01, not assumed:
#   6.09.01 run 1  -> legacy=created, scan=patched,   rank=patched
#   6.09.01 run 2  -> legacy=exists,  scan=unchanged, rank=unchanged
#   6.08.15 already carrying v1 -> scan=unchanged (left alone, not upgraded)
#
# Each edit still refuses to touch a file carrying an older marker of its own
# rather than guessing at a block it no longer describes. The rank guard
# reported `unmatched` there until it grew the same older-marker check the scan
# edit already had; the outcome was the same either way, but "unmatched" reads
# as a POV refactor and would send the next maintainer after a change POV never
# made.
pin('pov_internal_scraper_shim', 'NEVER-UPGRADES',
    'AI_SUBS_POV_INTERNAL_DIRS_v2', 'AI_SUBS_POV_RANK_MISS_v1')
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
pin('umbrella_mdblist_sync_patcher', 'UPGRADES',
    'AI_SUBS_UMB_MDBL_SINCE_v2', '_umb_mdbl_cursor_reset=2')
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
# UNPROVEN because the simulation's stock POV is 6.08.12, which does not carry
# the 6.08.14 line this repairs -- so the harness has no host and reports
# `unmatched` rather than a verdict. The behaviour IS proven, in
# tools/test_pov_alldebrid_status.py, which executes POV's own torrent_info
# before and after the patch against a single-object, a list and an empty-list
# response. Pinned anyway so a version bump stops here and asks.
pin('pov_alldebrid_status_fix', 'UNPROVEN',
    'AI_SUBS_POV_AD_STATUS_v1')
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
    'AI_SUBS_MDBL_WATCHLIST_ONLY_v2', 'AI_SUBS_SORT_RECENT_DEFAULT_v1',
    '_lists_sort_recent_v1')
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
pin('umbrella_language_patcher', 'DOUBLE-STAMP',
    '_umbrella_api_language_v1', '_umbrella_lang_filters_v1')
pin('umbrella_setup_patcher', 'DOUBLE-STAMP',
    'AI_SUBS_UMBRELLA_SOURCE_NAME_v1', '_umbrella_coco_providers_v1',
    '_umbrella_coco_providers_v2', '_umbrella_coco_wired_v1',
    '_umbrella_defaults_v1')
pin('update_nag_patcher', 'DOUBLE-STAMP',
    '_update_nag_quiet_v1')

# --- retired: marker-gated, and called by nothing ---------------------------
# Kept out of the broken counts on purpose: a patcher that reaches no device is
# not "the fix lands on fresh installs only", and counting it inflates the risk
# the table describes. Still PINNED, so re-arming one trips the tripwire and
# forces a measurement first. pov_build_content_logger_patcher's call site
# exists but its wrapper is commented out of service.py's steps tuple (it DOES
# compile()-check before writing -- an earlier version of this comment said it
# did not, which was simply false; the gate went in months ago);
# fentastic_dialog_subtitles_patcher is referenced nowhere at all.
pin('fentastic_dialog_subtitles_patcher', 'RETIRED',
    'AI_SUBS_DIALOG_HEADER_v1')
pin('pov_build_content_logger_patcher', 'RETIRED',
    'AI_SUBS_POV_BUILD_LOGGER_v2')

# --- no host on this machine: pinned so a bump still stops here -------------
# Not a clean bill of health -- an unmeasured patcher. The skins, the wizard,
# and service.subtitles.All_Subs (the darksubs_* family). Put the matching
# stock add-on where the patcher looks for it and re-run with --pins to turn
# one of these into a real verdict.
#
# af3_discover_pov_patcher matters most here: it carries the enumerated
# OLD_MARKERS shape this file warns about, and its live marker
# (AI_SUBS_POV_DISCOVER_v6_unified) was invisible until marker discovery
# stopped assuming the version sits at the end of the token.
pin('af3_dialog_subtitles_patcher', 'UNPROVEN',
    'AI_SUBS_AF3_HEADER_v1')
pin('af3_discover_pov_patcher', 'UNPROVEN',
    'AI_SUBS_POV_DISCOVER_v1', 'AI_SUBS_POV_DISCOVER_v2',
    'AI_SUBS_POV_DISCOVER_v3', 'AI_SUBS_POV_DISCOVER_v5_rollback',
    'AI_SUBS_POV_DISCOVER_v6_unified')
pin('af3_home_patcher', 'UNPROVEN',
    'AF3_CE_VERSION=6.3.2.14', 'JURIALMUNKEY_MIN_VERSION=0.2.35',
    'PATCH_VERSION=2026-06-01-pov-home-v21',
    'POV_AF3_PLOT_AUTOSCROLL_v2', 'POV_AF3_TOUCH_CLEANUP_v1')
pin('af3_search_pov_patcher', 'UNPROVEN',
    'AI_SUBS_POV_SEARCH_v1', 'AI_SUBS_POV_SEARCH_v2',
    'AI_SUBS_POV_SEARCH_v2_rollback', 'AI_SUBS_POV_SEARCH_v3',
    'AI_SUBS_POV_SEARCH_v3_rollback',
    'AI_SUBS_POV_SEARCH_v3_rollback_pov')
pin('all_subs_samefile_patcher', 'UNPROVEN',
    'AI_SUBS_ALL_SUBS_SAMEFILE_v1')
pin('dark_subs_integration', 'UNPROVEN',
    '_darksubs_autoenable_done=1', '_force_ai_autoenable_done=1')
pin('darksubs_download_sub_patcher', 'UNPROVEN',
    'AI_DOWNLOAD_SUB_ELIF_v1', 'AI_DOWNLOAD_SUB_ELIF_v2')
pin('darksubs_embedded_demote_patcher', 'UNPROVEN',
    'AI_EMBEDDED_DEMOTE_v2')
pin('darksubs_embedded_insert_patcher', 'UNPROVEN',
    'AI_SUBS_EMBED_ENG_LAST_v2')
pin('darksubs_filename_fallback_patcher', 'UNPROVEN',
    'AI_SUBS_FILENAME_FALLBACK_v2')
pin('darksubs_hook_diagnostics', 'UNPROVEN',
    'NAG_VERSION=1')
pin('darksubs_opensubtitles_patcher', 'UNPROVEN',
    'OPENSUBTITLES_SEARCH_FALLBACK_VERSION = 4')
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
    'AI_SUBS_FAVOURITES_PREMIUMIZE_RESEED_v1', 'mdblist_reseed_v2')
pin('fentastic_patcher', 'UNPROVEN',
    'AI_SUBS_NOTIFICATION_WRAP_v1')
pin('fentastic_widget_patcher', 'UNPROVEN',
    '_WIDGET_SEED_VERSION=v1', '_fen_widgets_seeded=v1')
pin('kodi_utils', 'UNPROVEN',
    '_embedded_mode_v1')
pin('nox_change_source_patcher', 'UNPROVEN',
    'AI_SUBS_NOX_CHANGE_SOURCE_v1')
pin('nox_osd_collision_patcher', 'UNPROVEN',
    'AI_SUBS_NOX_OSD_FIX_v1')
pin('pov_container_refresh_crash_fix', 'UNPROVEN',
    'AI_SUBS_POV_WIDGET_REFRESH_v1')
pin('pov_favorites_diagnostic', 'UNPROVEN',
    'DIAG_VERSION=4')
pin('pov_genre_folders_reseed_patcher', 'UNPROVEN',
    'RESEED_VERSION=v1', '_pov_genre_folders_reseed=v1')
pin('pov_scraper_settings_patcher', 'UNPROVEN',
    '_TUNE_BASE=v3')
pin('pov_seasons_view_seed', 'UNPROVEN',
    '_pov_seasons_view_v1')
pin('pov_series_networks_reseed_patcher', 'UNPROVEN',
    'RESEED_VERSION=v1', '_pov_series_networks_reseed=v1')
pin('pov_torbox_usage_patcher', 'UNPROVEN',
    'PATCH_VERSION=6', '_pov_torbox_usage_patch_version=6')
pin('resources/lib/subs_engine/sources/opensubtitles', 'UNPROVEN',
    'OPENSUBTITLES_SEARCH_FALLBACK_VERSION = 4')
pin('resources/patches/darksubs/opensubtitles', 'UNPROVEN',
    'OPENSUBTITLES_SEARCH_FALLBACK_VERSION = 4')
pin('service', 'UNPROVEN',
    'CACHE_RTL_FIX_VERSION=7', 'TEMP_PURGE_VERSION=2',
    '_builtin_engine_rollout_v2', '_chunk_lines_50_v1',
    '_fast_first_chunk_default_v2', '_fen_osd_autoclose_v1',
    '_gemini3_tune_v1', '_gemini_model_bump_v2', '_gemini_model_bump_v3',
    '_gender_ref_on_v1',
    '_ktuvit_on_v4', '_nox_poster_rating_default_v2',
    '_pool_default_on_v1', '_pool_share_force_v1',
    '_pov_autoplay_default_v1', '_pov_autoplay_revert_v2',
    '_pov_resume_revert_v1', '_remember_source_default_v1',
    '_remember_source_force_v2', '_rtl_fix_done=7', '_temp_purge_done=2')
pin('skin_dialog_subtitles_patcher', 'UNPROVEN',
    'AI_SUBS_DIALOG_HEADER_v1', 'AI_SUBS_DIALOG_HEADER_v2')
pin('skin_dialog_subtitles_row_patcher', 'UNPROVEN',
    'AI_SUBS_DIALOG_ROW_HEIGHT_v1')
pin('skin_watched_poster_patcher', 'UNPROVEN',
    'AI_SUBS_WATCHED_LIST_v1', 'AI_SUBS_WATCHED_POSTER_v1')
pin('subs_engine_bridge', 'UNPROVEN',
    'Cached_subs_v2', '_ENGINE_DEFAULTS_VERSION=4',
    '_engine_defaults_v=4')
pin('umbrella_watch_prompt', 'UNPROVEN',
    '_umb_watch_prompt_v1')
pin('umbrella_watch_source', 'UNPROVEN',
    '_umb_watch_source_v2')
pin('wizard_patcher', 'UNPROVEN',
    'AI_SUBS_LOGINIT_INJECT_v1')
pin('wizard_self_healer', 'UNPROVEN',
    'ai_subs_wizard_healed_v4')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


# --------------------------------------------------------------------------
# reading the tree
# --------------------------------------------------------------------------
# A marker is a versioned token INSIDE A STRING LITERAL. Every clause of that
# sentence was learned by getting it wrong, and each mistake hid live patchers:
#
#   * not "AI_SUBS..." -- a house convention five wired patchers do not follow
#     (darksubs_patcher, darksubs_download_sub_patcher,
#     darksubs_embedded_demote_patcher, pov_resume_cancel_patcher,
#     af3_home_patcher)
#   * not SHOUTING_CASE -- wizard_self_healer's marker is
#     '.ai_subs_wizard_healed_v4', lowercase, and already bumped three times
#   * not "_vN at the END" -- af3_discover_pov_patcher ships
#     'AI_SUBS_POV_DISCOVER_v6_unified' and af3_search_pov_patcher
#     'AI_SUBS_POV_SEARCH_v3_rollback'. The trailing word broke the \b, so BOTH
#     were pinned on their dead v1/v2/v3 predecessors and a bump of the live
#     marker would have tripped nothing. af3_discover_pov_patcher is also the
#     enumerated-OLD_MARKERS shape this file warns about, so that was the real
#     bug hiding behind the regex.
#   * not even "_vN" -- darksubs_opensubtitles_patcher's entire marker is the
#     line 'OPENSUBTITLES_SEARCH_FALLBACK_VERSION = 4'
#
# Scoping to string literals is what makes the looser shape safe: a marker is
# always text written into somebody else's file, while an ordinary api_v2 lives
# in code. Measured over the tree, the widened pattern gains six real markers
# and no false ones.
#
# And a fifth: a marker does NOT have to live in the host's file at all. There
# is a whole second convention here -- a versioned flag in OUR OWN addon's Kodi
# settings, recording that a one-time change already ran -- and every one of
# those starts with an underscore, which \b can never anchor before because _
# is a word character. Thirteen were invisible, among them
# pov_mdblist_patcher's '_lists_sort_recent_v1', which gates one of the five
# entry points service.py calls on every boot. That one has the WORST
# safety net in the tree: the flag lives in our own settings, so neither a
# host update nor anything else ever clears it. Bumping it shipped a real
# MDBList-shaped regression under a printed ALL PASS.
_MARKER_RES = (
    re.compile(r'(?<![A-Za-z0-9_])_*[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)*'
               r'_v\d+(?:_[A-Za-z0-9]+)*\b'),
    re.compile(r'\b[A-Za-z][A-Za-z0-9_]*_VERSION\s*=\s*\d+'),
)


def _in_text(text):
    out = set()
    for rx in _MARKER_RES:
        out |= set(rx.findall(text))
    return out


def literal_markers(src):
    """Every versioned marker spelled out in a string literal in the source."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return _in_text(src)
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out |= _in_text(node.value)
    return out


def pair_markers(src):
    """Markers whose NAME and VERSION are two different constants.

    A seventh shape, and the one already proven in production. The convention
    is a fixed key with no digits plus a bare version value with no name,
    joined only at runtime:

        CACHE_RTL_FIX_VERSION = '7'
        ...
        kodi_utils.set_setting('_rtl_fix_done', CACHE_RTL_FIX_VERSION)

    Neither literal carries both halves, so no single-string search can ever
    see it -- and that one has been bumped 4->5 and 5->6 in shipped releases,
    each time for exactly the reason this file exists. Its own comment says
    so: "the constant must be bumped whenever a new repair is added here, or
    every existing install skips the backfill forever."

    So the call site is read instead of the text: a two-argument
    set_setting/setSetting whose key and value both resolve to module-level
    string constants becomes the marker "key=value". A value with no digit in
    it is not a version ('done', 'true') and is skipped.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    consts[t.id] = node.value.value

    def resolve(a):
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            return a.value
        if isinstance(a, ast.Name):
            return consts.get(a.id)
        # '{0}:{1}'.format(kind, NAG_VERSION) -- the same split shape with one
        # more step. darksubs_hook_diagnostics joins its version this way, and
        # a resolver that only knew Constant and Name skipped the whole call.
        if isinstance(a, ast.Call) and isinstance(a.func, ast.Attribute) \
                and a.func.attr == 'format' \
                and isinstance(a.func.value, ast.Constant) \
                and isinstance(a.func.value.value, str):
            parts = [resolve(x) for x in a.args]
            if all(p is not None for p in parts):
                try:
                    return a.func.value.value.format(*parts)
                except (IndexError, KeyError, ValueError):
                    return None
        return None

    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) != 2:
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else \
            fn.id if isinstance(fn, ast.Name) else ''
        if name not in ('set_setting', 'setSetting'):
            continue
        key, val = resolve(node.args[0]), resolve(node.args[1])
        if key and val is None:
            # The value comes out of a local helper, so no literal for it
            # exists anywhere: pov_scraper_settings_patcher writes
            # set_setting(TUNE_FLAG, _tune_version()), and _tune_version
            # returns '%s-%s' % (_TUNE_BASE, md5(...)). The hand-maintained
            # half is _TUNE_BASE, and its own comment says a stale one means
            # "every device that had run the old value would keep it forever"
            # -- this module has ALREADY shipped that bug once, caught only by
            # a reviewer. So follow one hop: any module-level string constant
            # the helper touches is part of that version.
            fn = node.args[1]
            if isinstance(fn, ast.Call) and isinstance(fn.func, ast.Name):
                for d in ast.walk(tree):
                    if isinstance(d, ast.FunctionDef) and d.name == fn.func.id:
                        for n in ast.walk(d):
                            if isinstance(n, ast.Name) and n.id in consts \
                                    and re.search(r'\d', consts[n.id]):
                                out.add('%s=%s' % (n.id, consts[n.id]))
            continue
        if not key or not val or not re.search(r'\d', val):
            continue
        # The key must be one of OUR one-shot flags. Without this, ordinary
        # settings writes join the table -- set_setting('chunk_lines', '50')
        # is not a version gate, and tripping the pin when someone retunes a
        # default is the kind of noise that gets a test switched off.
        if not key.startswith('_'):
            continue
        # And skip the ones whose key already carries the version: the literal
        # search has them, and pinning '_gemini_model_bump_v2=1' beside
        # '_gemini_model_bump_v2' is the same tripwire written twice.
        if re.search(r'_v\d+$', key):
            continue
        out.add('%s=%s' % (key, val))
    return out


def all_markers(src):
    """Every marker in a source, by all four rules at once.

    ONE function, because there were two lists and they silently disagreed:
    patchers() discovered with all four detectors while simulate_bump built
    its candidate set from literal+runtime only. So every marker found by the
    round-7 settings-pair rule and the round-8 version-constant rule was
    pinned and then never simulated -- 26 markers across 14 modules, including
    CACHE_RTL_FIX_VERSION, the very example used to justify writing the pair
    rule. Injecting the textbook MDBList regression into one of those gates
    produced a byte-identical verdict to the healthy code.

    The sabotage case for it even said so: "the pair shape is pinned but
    cannot be simulated". It was asserting on a string utility, not on a run.
    """
    return literal_markers(src) | pair_markers(src) | version_constants(src)


def version_constants(src):
    """Module-level NAME_VERSION = '<value with a digit>'.

    A third way to spell a gate, and af3_home_patcher shows why it has to be
    caught on its own: PATCH_VERSION = '2026-06-01-pov-home-v21' is written
    into marker FILES (_LAYOUT_MARKER, _SPOTLIGHT_MARKER) whose whole content
    IS the version, so neither the string search nor the settings-pair search
    can see it. darksubs_hook_diagnostics' NAG_VERSION is the same shape with
    the key built at runtime, which is unresolvable statically.

    This also pins two third-party version requirements (AF3_CE_VERSION,
    JURIALMUNKEY_MIN_VERSION). That is deliberate rather than tolerated: a
    host add-on's version changing is exactly when every verdict here needs
    re-measuring, which these notes say elsewhere in so many words.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()
    out = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not (isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                and re.search(r'\d', node.value.value)):
            continue
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id.endswith('VERSION') \
                    and t.id.isupper():
                out.add('%s=%s' % (t.id, node.value.value))
    return out


def bump_marker(m):
    """The same marker, one version later. None if it carries no version.

    The version is the LAST _vN in the token, not a trailing one: a marker can
    carry a word after its number ('..._v6_unified') and that word belongs to
    the marker.
    """
    hits = list(re.finditer(r'_v(\d+)', m))
    if hits:
        h = hits[-1]
        return '%s_v%d%s' % (m[:h.start()], int(h.group(1)) + 1, m[h.end():])
    h = re.search(r'(=\s*v?)(\d+)\s*$', m)
    if h:
        return m[:h.start(2)] + str(int(h.group(2)) + 1) + m[h.end(2):]
    # Last resort: bump the final run of digits. af3_home_patcher's gate is
    # PATCH_VERSION = '2026-06-01-pov-home-v21' -- a date, a name and a
    # version in one string -- and a rule that only knows "digits right after
    # the =" cannot move it at all.
    h = None
    for h in re.finditer(r'\d+', m):
        pass
    if h:
        return m[:h.start()] + str(int(h.group()) + 1) + m[h.end():]
    return None


def marker_family(m):
    """The marker with its version taken out, for grouping."""
    return re.sub(r'_v\d+', '', re.sub(r'=\s*v?\d+\s*$', '', m))


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
                # .update, NOT `found |= ...`: augmented assignment to a name
                # from an enclosing scope rebinds it as a local, so every call
                # raised UnboundLocalError -- swallowed by the except below,
                # leaving runtime_markers silently returning nothing and
                # pov_services_patcher measuring CLAIMS-PATCHED.
                found.update(_in_text(v))
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

    DISCOVERY IS NOT EXECUTABILITY, and conflating them hid the largest
    population of all. The filter used to require an ensure_*/heal_* def AND a
    file directly inside resources/lib -- so a versioned marker anywhere else
    was not merely unmeasured, it was unknown to exist:

      * service.py itself holds EIGHTEEN versioned settings markers gating
        one-shot migrations run from main() at boot -- including
        _gemini_model_bump_v2, whose own comment states the exact
        "reusing the old id makes it a no-op for the users who need it" risk
        this file exists to catch.
      * kodi_utils (_embedded_mode_v1), umbrella_watch_prompt and
        umbrella_watch_source (_umb_watch_source_v2, already bumped once) sit
        in resources/lib but expose no ensure_*/heal_*.

    So a module is DISCOVERED if it carries a versioned marker at all, and it
    is pinned either way. Only a module with a live entry point can be
    simulated; the rest are honestly UNPROVEN. That still buys the thing that
    matters most -- the pin layer trips on a bump -- for all of them.
    """
    seen = set()
    files = []
    for dp, dns, fns in os.walk(ADDON):
        dns[:] = [d for d in dns if d != '__pycache__']
        files += [os.path.join(dp, f) for f in sorted(fns) if f.endswith('.py')]
    for path in sorted(files):
        path = os.path.normpath(path)
        in_lib = os.path.dirname(path) == LIB
        is_service = os.path.dirname(path) == ADDON
        if in_lib or is_service:
            stem = os.path.basename(path)[:-3]
        else:
            # A PAYLOAD, keyed by its path: basenames repeat across the tree
            # (movies.py, cache.py, srt.py...), and a bare-basename key would
            # let one silently win over another.
            stem = os.path.relpath(path, ADDON)[:-3].replace(os.sep, '/')
        if stem in seen or os.path.basename(path).startswith('__'):
            continue
        seen.add(stem)
        src = open(path, encoding='utf-8').read()
        runnable = in_lib and bool(
            re.search(r'(?m)^def (ensure|heal)\w*\(', src))
        marks = all_markers(src)
        if runnable:
            marks |= runtime_markers(stem)
        if not (in_lib or is_service):
            # In a payload the version is CODE, not a string -- this file IS
            # the text that ships. darksubs_opensubtitles_patcher gates on
            # 'OPENSUBTITLES_SEARCH_FALLBACK_VERSION = 4' while the file it
            # copies carries that same line as a real assignment, in
            # resources/patches/, a SIBLING of resources/lib. Two hand-synced
            # copies with nothing linking them: bump the one that ships and
            # the gate still matches the old text on every device that has it,
            # forever. Scanning payload source as raw text is the only way to
            # see that half. It stays off for our own modules, where the same
            # pattern would just re-find INJECT_VERSION-style constants that
            # runtime_markers already resolves properly.
            marks |= set(_MARKER_RES[1].findall(src))
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

    # A real settings store, written to a file under `home`.
    #
    # Not decoration: a whole class of marker lives in OUR OWN addon settings
    # rather than in the host's file ('_lists_sort_recent_v1' and twelve like
    # it). With get_setting/set_setting unstubbed, those patchers either
    # crashed or wrote somewhere _snapshot cannot see, so their markers could
    # never be observed landing and the class stayed unmeasurable even once it
    # was discoverable. Backing it with a file makes the snapshot pick it up
    # exactly like any other host write.
    store = os.path.join(home, 'userdata', 'addon_data',
                         'service.subtitles.kodipovilai', 'settings.probe')
    os.makedirs(os.path.dirname(store), exist_ok=True)

    def _read():
        try:
            with open(store, encoding='utf-8') as f:
                return dict(ln.rstrip('\n').split('=', 1)
                            for ln in f if '=' in ln)
        except OSError:
            return {}

    def _get(key, default=''):
        return _read().get(key, default)

    def _set(key, value):
        d = _read()
        d[str(key)] = str(value)
        with open(store, 'w', encoding='utf-8') as f:
            for k in sorted(d):
                f.write('%s=%s\n' % (k, d[k]))
    ku.get_setting = _get
    ku.set_setting = _set

    # xbmcaddon, which was EVICTED from sys.modules and never replaced.
    #
    # A patcher that reads another add-on's settings does it through
    # xbmcaddon.Addon('plugin.video.pov'), not through kodi_utils. Without the
    # module, that import raised, the surrounding `except Exception` returned
    # 'no_pov' / 'not_installed', and the entry point never ran -- on every
    # machine, stock host present or not. pov_mdblist_patcher's
    # ensure_lists_sort_recent, the very example these notes call the worst
    # safety net in the tree, has never once been dynamically exercised here.
    settings_dir = os.path.join(home, 'userdata', 'addon_data')

    class _Addon(object):
        def __init__(self, addon_id='service.subtitles.kodipovilai'):
            # A real Kodi Addon() raises for an add-on that is not installed,
            # which is exactly how these patchers detect a missing host --
            # emulate it rather than handing back a store nobody has.
            if not os.path.isdir(os.path.join(home, 'addons', addon_id)) \
                    and addon_id != 'service.subtitles.kodipovilai':
                raise RuntimeError('addon %s is not installed' % addon_id)
            self._id = addon_id
            self._f = os.path.join(settings_dir, addon_id, 'settings.probe')
            os.makedirs(os.path.dirname(self._f), exist_ok=True)

        def _all(self):
            try:
                with open(self._f, encoding='utf-8') as f:
                    return dict(ln.rstrip('\n').split('=', 1)
                                for ln in f if '=' in ln)
            except OSError:
                return {}

        def getSetting(self, key):
            return self._all().get(key, '')

        def setSetting(self, key, value):
            d = self._all()
            d[str(key)] = str(value)
            with open(self._f, 'w', encoding='utf-8') as f:
                for k in sorted(d):
                    f.write('%s=%s\n' % (k, d[k]))

        def getAddonInfo(self, field):
            return {'id': self._id, 'version': '0.0.0',
                    'path': os.path.join(home, 'addons', self._id),
                    'profile': os.path.dirname(self._f)}.get(field, '')

    xa = types.ModuleType('xbmcaddon')
    xa.Addon = _Addon
    sys.modules['xbmcaddon'] = xa
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
        nxt = bump_marker(m)
        if not nxt:
            continue
        out = re.sub(re.escape(m) + r'(?![0-9])',
                     nxt.replace('\\', '\\\\'), out)
        if '=' not in m:
            continue
        # A synthesised "key=value" marker has no verbatim text in the source
        # -- that is the whole premise of pair_markers -- so the replace above
        # is a silent no-op and the "second run" runs the UNCHANGED module.
        # That made every pair-shaped gate read NEVER-UPGRADES regardless of
        # whether it was healthy, and two correct patchers were pinned as
        # broken on the strength of it. Move the constant that HOLDS the
        # version instead.
        val, nval = m.split('=', 1)[1].strip(), nxt.split('=', 1)[1].strip()
        if val and val != nval:
            out = re.sub(r"(?m)^(\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*)"
                         r"(['\"])%s\2" % re.escape(val),
                         lambda g: '%s%s%s%s' % (g.group(1), g.group(2),
                                                 nval, g.group(2)), out)
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
    fam = {marker_family(m) for m in markers}

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
        snap0 = _snapshot(home)
        s1 = _run(stem, home, extra_path=base)
        if s1 == 'RETIRED':
            # Defined, marker-gated, and called by nothing. Pinned so that
            # re-arming it trips the tripwire and forces a measurement, but
            # kept out of the broken counts: a patcher that reaches no device
            # is not "the fix lands on fresh installs only".
            return 'RETIRED', s1, ''
        snap1 = _snapshot(home)
        blob1 = b''.join(snap1.values())
        # bump_marker(m) must be able to move it, or the per-marker loop
        # below would ask has() about None.
        landed = sorted(m for m in (all_markers(text)
                                    | runtime_markers(stem, base))
                        if has(blob1, m) and bump_marker(m))
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
            claims = any(r.startswith('patched') or r == 'repatched'
                         for r in results)
            # ...and nothing on disk moved. Both halves are needed. A module
            # can hold markers for one entry point while the entry point that
            # actually ran patches something markerless -- umbrella_language_
            # patcher rewrites strings.po with no marker at all, and calling
            # that a dead anchor was wrong. A REAL dead anchor writes nothing.
            if STOCK and claims and snap1 == snap0:
                return ('CLAIMS-PATCHED', s1,
                        'reported success and changed nothing')
            return 'UNPROVEN', s1, ''

        # A FRESH directory per variant, never a rewrite in place. Writing two
        # variants to the same path is how pov_services_patcher came back
        # UNBUMPABLE: the literal-only and version-bumped sources differ by one
        # digit, so same size, and written in the same second, so same mtime --
        # and Python served the first one's cached bytecode for the second.
        tmps = []

        made = {}

        def variant(**kw):
            d = tempfile.mkdtemp(prefix='upgmod-')
            tmps.append(d)
            body = bump_source(text, landed, **kw)
            made[d] = body
            with open(os.path.join(d, stem + '.py'), 'w',
                      encoding='utf-8') as f:
                f.write(body)
            # The bumped module still resolves its resources relative to
            # __file__, so it needs its real siblings beside it.
            # build_icons_patcher's _bundled_root() looks for media_assets/
            # next to itself; in a bare temp directory it returned
            # 'no_bundled' at the first guard and never reached the code that
            # writes its marker, which read as NEVER-UPGRADES.
            for entry in os.listdir(LIB):
                if entry in (stem + '.py', '__pycache__'):
                    continue
                try:
                    os.symlink(os.path.join(LIB, entry),
                               os.path.join(d, entry))
                except OSError:
                    pass
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
            def unmoved(d, text_after=None):
                # all_markers on the bumped SOURCE, not just runtime
                # attributes: runtime_markers matches one attribute at a time
                # and so can never represent a pair marker at all -- it could
                # not report one "unmoved", the escalation never fired, and a
                # no-op bump sailed through as a measurement.
                after = runtime_markers(stem, d)
                if text_after is not None:
                    after |= all_markers(text_after)
                return [m for m in landed if m in after]
            if unmoved(use, made.get(use)):
                # constructed marker: the version lives in an int constant
                use = variant(versions=True)
                if unmoved(use, made.get(use)):
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
            old, new = has(blob2, m), has(blob2, bump_marker(m))
            per.append('UPGRADES' if new and not old else
                       'DOUBLE' if new else
                       'NEVER-UPGRADES' if old else 'LOST-PATCH')
        # A pinned marker that NEVER LANDS was silently absent from `per` and
        # so contributed nothing -- no verdict, no warning. That is how
        # AI_SUBS_MDBL_REDACT_v1 sat in the table for free: it is a phantom,
        # declared in pov_mdblist_patcher but never written by the code it
        # nominally gates, which really uses an unversioned sentinel. Say so,
        # rather than letting a module look covered because its OTHER markers
        # were measured.
        ghosts = [m for m in (all_markers(text)
                              | runtime_markers(stem, base))
                  if m not in landed]
        if ghosts:
            s2 = '%s [never landed: %s]' % (s2, ' '.join(sorted(ghosts)))

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
                '%s=%s' % (marker_family(m).replace('AI_SUBS_', ''), p)
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
        # ... and the other direction, which this check did NOT have and which
        # a real change walked straight through: a marker DELETED from the
        # source left its pin behind and nothing said a word. It matters for
        # two reasons. A RENAME is a delete plus an add, and only the add half
        # was visible -- so the table would claim the module has two markers
        # when it has one, and the pinned verdict would describe a marker that
        # no longer exists. And a retired migration usually leaves debris: the
        # hidden setting stays declared in our settings.xml, storing a value
        # nothing reads. Measured when this was added: exactly one pin in the
        # whole table was stale, so this starts clean rather than inheriting a
        # backlog.
        gone = [m for m in pinned if m not in marks]
        check('%s pins no marker that is gone from the source' % stem, not gone,
              'pinned marker(s) %s are no longer in %s. If the migration was '
              'retired, drop it from the pin (and from settings.xml, if it '
              'declared one). If it was RENAMED, that is a bump: devices '
              'carrying the old name are not covered by the new one.'
              % (', '.join(gone), stem))

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

    # The four marker SHAPES that each hid a live patcher until they were
    # measured for. Every one of these is a real marker shipping today.
    for stem, marker, shape in (
            ('wizard_self_healer', 'ai_subs_wizard_healed_v4', 'lowercase'),
            ('af3_discover_pov_patcher', 'AI_SUBS_POV_DISCOVER_v6_unified',
             'a word after the version'),
            ('af3_search_pov_patcher', 'AI_SUBS_POV_SEARCH_v3_rollback',
             'a word after the version'),
            ('darksubs_opensubtitles_patcher',
             'OPENSUBTITLES_SEARCH_FALLBACK_VERSION = 4', 'NAME = int')):
        check('SABOTAGE: a marker with %s is discovered (%s)' % (shape, stem),
              marker in PINS.get(stem, ('', ()))[1],
              'the marker shape assumption is back, and this live patcher is '
              'invisible again')

    # ...and each of those shapes has to survive being bumped, or the
    # simulation quietly measures the patcher against an unchanged copy.
    check('SABOTAGE: every marker shape can be bumped',
          bump_marker('ai_subs_wizard_healed_v4') == 'ai_subs_wizard_healed_v5'
          and bump_marker('AI_SUBS_POV_DISCOVER_v6_unified')
          == 'AI_SUBS_POV_DISCOVER_v7_unified'
          and bump_marker('OPENSUBTITLES_SEARCH_FALLBACK_VERSION = 4')
          == 'OPENSUBTITLES_SEARCH_FALLBACK_VERSION = 5',
          'bump_marker is back to assuming _vN sits at the end')

    # A marker does not have to live in the HOST's file. There is a second
    # convention here -- a versioned flag in our own addon's Kodi settings,
    # recording a one-time change -- and every one of those starts with an
    # underscore, which \b can never anchor before. Thirteen were invisible.
    # The sharp one gates a live entry point of pov_mdblist_patcher and has
    # the worst safety net in the tree: our own settings, which nothing ever
    # clears. Bumping it used to print ALL PASS.
    check('SABOTAGE: an underscore-led settings marker is discovered',
          '_lists_sort_recent_v1' in PINS['pov_mdblist_patcher'][1]
          and '_update_nag_quiet_v1' in PINS['update_nag_patcher'][1],
          'the marker pattern cannot anchor before a leading underscore '
          'again, and the whole settings-flag convention is invisible')

    # ...and those markers have to be OBSERVABLE, which needs a real settings
    # store: unstubbed, the patcher either crashed or wrote where the snapshot
    # cannot see, so the class stayed unmeasurable even once discoverable.
    _h = tempfile.mkdtemp(prefix='upgset-')
    try:
        _install_stubs(_h)
        _ku = sys.modules['resources.lib.kodi_utils']
        _ku.set_setting('_probe_v1', 'done')
        check('SABOTAGE: the settings store round-trips and lands on disk',
              _ku.get_setting('_probe_v1', '') == 'done'
              and any(b'_probe_v1' in v for v in _snapshot(_h).values()),
              'settings markers are written somewhere _snapshot cannot see')
    finally:
        shutil.rmtree(_h, ignore_errors=True)

    # xbmcaddon has to EXIST. It was evicted from sys.modules and never
    # replaced, so every entry point reading another add-on's settings hit
    # ModuleNotFoundError, returned its "host not installed" sentinel, and was
    # never exercised -- including ensure_lists_sort_recent, the example these
    # notes lean on hardest. Three pinned verdicts were wrong because of it.
    _h2 = tempfile.mkdtemp(prefix='upgaddon-')
    try:
        os.makedirs(os.path.join(_h2, 'addons', 'plugin.video.pov'))
        _install_stubs(_h2)
        import xbmcaddon as _xa
        _a = _xa.Addon('plugin.video.pov')
        _a.setSetting('probe', 'yes')
        missing = False
        try:
            _xa.Addon('plugin.video.definitely.not.installed')
        except Exception:
            missing = True
        check('SABOTAGE: xbmcaddon exists, stores, and refuses a missing host',
              _a.getSetting('probe') == 'yes' and missing,
              'a cross-addon settings gate cannot be measured at all')
    finally:
        shutil.rmtree(_h2, ignore_errors=True)

    # A marker whose NAME and VERSION are two separate constants, joined only
    # at the call site. CACHE_RTL_FIX_VERSION has been bumped 4->5 and 5->6 in
    # shipped releases for exactly the reason this file exists, and no
    # single-string search could ever have seen it.
    check('SABOTAGE: a split name/version pair is discovered',
          '_rtl_fix_done=7' in PINS.get('service', ('', ()))[1]
          and '_tiles_refresh_gen=2'
          in PINS.get('build_icons_patcher', ('', ()))[1],
          'the pair shape is invisible again, and the RTL backfill gate with '
          'it')
    check('SABOTAGE: an ordinary settings write is NOT a marker',
          not any(m.startswith(('chunk_lines=', 'temperature='))
                  for m in PINS.get('service', ('', ()))[1]),
          'retuning a default would trip the pin -- noise like that is how a '
          'test gets switched off')
    # A payload's version is CODE, in a file that is a sibling of
    # resources/lib. darksubs_opensubtitles_patcher gates on text that also
    # lives, as a real assignment, in the file it copies -- two hand-synced
    # copies with nothing linking them.
    check('SABOTAGE: a payload file outside resources/lib is scanned',
          'OPENSUBTITLES_SEARCH_FALLBACK_VERSION = 4' in PINS.get(
              'resources/patches/darksubs/opensubtitles', ('', ()))[1],
          'the shipped half of the darksubs opensubtitles patch is invisible '
          'again -- bump it there and the gate keeps matching the old text')

    # A version constant can be a gate on its own, written into a marker FILE
    # whose whole content is the version.
    check('SABOTAGE: a bare version constant is a marker',
          'PATCH_VERSION=2026-06-01-pov-home-v21'
          in PINS.get('af3_home_patcher', ('', ()))[1]
          and bump_marker('PATCH_VERSION=2026-06-01-pov-home-v21')
          == 'PATCH_VERSION=2026-06-01-pov-home-v22',
          'af3_home_patcher writes PATCH_VERSION into _LAYOUT_MARKER and '
          '_SPOTLIGHT_MARKER; neither the string nor the settings-pair search '
          'can see it')

    check('SABOTAGE: a split pair can be bumped',
          bump_marker('_rtl_fix_done=7') == '_rtl_fix_done=8'
          and bump_marker('_fen_widgets_seeded=v1') == '_fen_widgets_seeded=v2',
          'bump_marker cannot move the pair shape')

    # ...and it has to be SIMULATED, not merely pinned. That is a different
    # claim, and for two rounds it was false: patchers() discovered with all
    # four rules while simulate_bump built its candidates from two, so every
    # pair and version-constant marker was pinned and never run. The check
    # above did not notice, because it asserts on a string utility.
    # hebrew_build_ui_patcher's verdict is the end-to-end proof: it can only
    # be NEVER-UPGRADES if its _ui_prefs_seeded=v1 pair marker was actually
    # landed, bumped and re-measured.
    _hb = open(os.path.join(LIB, 'hebrew_build_ui_patcher.py'),
               encoding='utf-8').read()
    check('SABOTAGE: bumping a pair marker really moves the source',
          "_PREFS_SEED_VERSION = 'v2'"
          in bump_source(_hb, ['_ui_prefs_seeded=v1']),
          'a synthesised key=value has no verbatim text to replace, so the '
          'bump is a silent no-op and the second run re-runs the FIRST '
          'module -- which reads NEVER-UPGRADES for every pair-shaped gate, '
          'healthy or not')
    check('SABOTAGE: a healthy pair-marker gate measures UPGRADES',
          PINS['hebrew_build_ui_patcher'][0] == 'UPGRADES',
          '_prefs_already_seeded() compares straight against the live '
          'constant -- the correct pattern. Anything else here means the '
          'pair shape is being judged by its shape rather than its behaviour')

    # A version that only exists inside a local helper. pov_scraper_settings_
    # patcher writes set_setting(TUNE_FLAG, _tune_version()), and its
    # hand-maintained half has already shipped this exact bug once.
    check('SABOTAGE: a version behind a helper call is found',
          '_TUNE_BASE=v3' in PINS.get('pov_scraper_settings_patcher',
                                      ('', ()))[1],
          'the module is invisible again -- not pinned, not even unproven')

    # Discovery must not stop at resources/lib with an entry point. service.py
    # holds sixteen versioned settings markers gating boot migrations, and
    # three lib modules carry markers with no ensure_*/heal_* at all. None of
    # them were even pinned -- so no tripwire, not merely no measurement.
    # A MODULE THIS HARNESS CANNOT SEE AT ALL, which is the failure the whole
    # file exists to prevent and which it was itself blind to.
    #
    # Discovery is by marker SHAPE -- `_MARKER_RES` wants `..._v<digits>`. A
    # patcher whose marker does not fit that shape yields no markers, so
    # `patchers()` never yields it, so it is not pinned, not measured, and not
    # even counted as unproven. It simply is not in the report. That happened:
    # a POV cache patcher written with `MARK = 'KODI_POV_IL wal v1'` -- spaces,
    # no underscore-v -- was invisible here while carrying a real bug this
    # harness is built to catch (a version bump that can never reach a patched
    # device, because the version-stamped marker means an already-patched file
    # never matches the new marker either).
    #
    # So the rule is stated the other way round, on the module rather than on
    # the marker: a runnable patcher that declares a VERSIONED constant must be
    # pinned. It cannot hide by spelling its version in a shape the regex above
    # does not know. Zero modules in the tree violate this today, and the
    # module that did was deleted before release.
    _unseen = []
    for _fn in sorted(os.listdir(LIB)):
        if not _fn.endswith('.py') or _fn.startswith('__'):
            continue
        _stem = _fn[:-3]
        _src = open(os.path.join(LIB, _fn), encoding='utf-8').read()
        if not re.search(r'(?m)^def (ensure|heal)\w*\(', _src):
            continue
        try:
            _tree = ast.parse(_src)
        except Exception:
            continue
        for _node in _tree.body:
            if not isinstance(_node, ast.Assign):
                continue
            for _t in _node.targets:
                _n = getattr(_t, 'id', '')
                _v = _node.value
                if (re.search(r'MARK|MARKER|STAMP|VERSION|SENTINEL', _n, re.I)
                        and isinstance(_v, ast.Constant)
                        and isinstance(_v.value, str)
                        and re.search(r'(?:\bv\d+\b|_v\d+)', _v.value, re.I)
                        and _stem not in PINS):
                    _unseen.append('%s: %s = %r' % (_stem, _n, _v.value))
    check('a runnable patcher with a versioned marker is always pinned',
          not _unseen,
          'invisible to this harness -- not pinned, not unproven, absent: '
          + '; '.join(_unseen))

    check('SABOTAGE: markers outside the patcher shape are still pinned',
          '_gemini_model_bump_v2' in PINS.get('service', ('', ()))[1]
          and '_embedded_mode_v1' in PINS.get('kodi_utils', ('', ()))[1]
          and '_umb_watch_source_v2'
          in PINS.get('umbrella_watch_source', ('', ()))[1],
          'discovery is scoped to runnable patcher modules again')

    # The pin comparison used to run one way only -- pinned markers were never
    # checked for still EXISTING. Deleting a migration therefore passed in
    # silence, and a rename showed only its added half. Prove the reverse check
    # can fail by feeding it a marker nothing in the tree defines. Constructed,
    # not borrowed from the table, so retiring any real migration does not turn
    # this into a false alarm.
    _live = {}
    for _stem, _src, _marks in patchers():
        _live[_stem] = set(_marks)
    _victim = next((s for s in ('service', 'umbrella_mdblist_sync_patcher')
                    if s in _live), None)
    check('SABOTAGE: a pinned marker that vanished from the source is caught',
          _victim is not None
          and [m for m in tuple(PINS[_victim][1]) + ('AI_SUBS_GHOST_v1',)
               if m not in _live[_victim]] == ['AI_SUBS_GHOST_v1'],
          'the reverse comparison does not fire, so a deleted or renamed '
          'marker leaves a pin describing something that no longer exists')

    # Every host this tree patches needs a key, or its patchers cannot be
    # measured on ANY machine -- there is nowhere to point at them. The list
    # was two entries while seven other hosts had live, marker-gated patchers.
    # DERIVED from the tree, not a list of the three hosts I happened to think
    # of when this check was written. That list was itself the round-5 disease
    # -- a hand-maintained enumeration -- and it duly missed
    # plugin.video.idanplus, a live host patched from service.py every boot.
    OURS = 'service.subtitles.kodipovilai'
    used = set()
    for _p, _t in _addon_sources().items():
        for _m in re.finditer(
                r"(?m)^[A-Z][A-Z0-9_]*\s*=\s*'((?:plugin\.(?:video|program)"
                r"|skin|service\.subtitles)\.[A-Za-z0-9._]+)'", _t):
            used.add(_m.group(1))
    used.discard(OURS)
    check('SABOTAGE: every host this tree patches is declared',
          used <= DECLARED_HOSTS,
          'undeclared: %s -- there is nowhere to point a stock tree at them, '
          'so their patchers are permanently unmeasurable rather than merely '
          'unmeasured here' % ', '.join(sorted(used - DECLARED_HOSTS)))

    # runtime_markers reads module attributes, and its collector is a nested
    # function: `found |= ...` there rebinds a local and raises, which the
    # except swallows, so it silently returned nothing and the constructed
    # marker of pov_services_patcher vanished.
    check('SABOTAGE: runtime_markers actually collects',
          'AI_SUBS_MYSERVICES_INJECT_v12'
          in PINS['pov_services_patcher'][1],
          'the constructed marker is missing -- runtime discovery is mute')

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
