# One-time tune of plugin.video.pov's scraper settings for the build.
#
# The build owner WANTS pre-release (CAM/SCR/TELE) and 3D results included by
# default, so this restores both to ON. It also turns the default-ON
# "piratebay" provider back on (the build's userdata left it off, which reduced
# source counts). v1 of this patcher briefly turned pre-release/3D off; v2
# restores them, and because the marker version changed it re-applies on any
# device that got v1.
#
# NOTE: this does NOT affect the "1080p-named source shown as SD" report. POV
# derives 4K/1080p/720p by regex on the release name
# (source_utils.get_release_quality) -- the same code on a clean POV and here --
# so these settings do not change how a source is labelled, only which sources
# appear. That display report is tracked separately.
#
# We deliberately DO NOT touch filter.foreign.single.audio (the build keeps it
# off on purpose so Hebrew / foreign-audio releases are not dropped).
#
# Applied once per marker version, only where the value still differs -- so a
# user who later changes any of these keeps their choice. If POV is not
# installed yet we skip WITHOUT marking done, so it retries.

try:
    import xbmcaddon
except Exception:
    xbmcaddon = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
TUNE_FLAG = '_pov_scraper_tune'
TUNE_VERSION = 'v3'

# id -> desired value ('true'/'false' as POV stores bools).
DESIRED = (
    ('include_prerelease_results', 'true'),
    ('include_3d_results', 'true'),
    ('provider.piratebay', 'true'),
)

# id -> the LOWEST value we are willing to leave in place. Unlike DESIRED these
# are only ever raised, never lowered: a user who wants to wait longer keeps
# their number.
#
# scrapers.timeout.1 is the reason this exists. In POV 6.08.x that one number
# is spent TWICE, on two phases that run one after the other in
# ExternalSources.results():
#
#   1. thread_monitor over the provider threads      -- find torrents
#   2. thread_monitor over the debrid cache-checks   -- ask the debrid which of
#                                                       those it already holds
#
# and after each one POV keeps ONLY the threads that finished:
#
#     threads = [i for i in threads if i.done() and not i.exception()]
#
# For phase 2 that is unforgiving, because final_sources is built exclusively
# inside the loop over the debrid threads that came back. With a single debrid
# configured -- which is the normal setup here -- that is ONE thread, and if it
# does not answer in time the entire result set is dropped and POV reports "no
# results" even though phase 1 found hundreds of torrents.
#
# Those torrents are not lost, though: each provider writes its own results
# into POV's providers cache as soon as it finishes, whether or not anyone was
# still waiting for it. So the NEXT attempt at the same title serves phase 1
# from cache in a fraction of a second, which leaves the whole budget to the
# debrid check, and it succeeds. That is exactly the reported shape -- "first
# time no results, second time it finds sources, seemingly at random".
#
# POV shipped 6.08.01 with this setting's default raised from 10 to 20 and its
# label changed from "Scraper Timeout" to "Scraper/Debrid Timeout (secs)",
# which is upstream saying the same thing: one number now has two jobs. Our
# build's userdata pins it at 10, so our users kept half the budget POV now
# expects. This adopts POV's own new default rather than inventing a number.
MINIMUMS = (
    ('scrapers.timeout.1', 20),
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_scraper_settings_patcher: ' + msg, level=level)
    except Exception:
        pass


def _already_done():
    if kodi_utils is None:
        return False
    try:
        return kodi_utils.get_setting(TUNE_FLAG, '') == TUNE_VERSION
    except Exception:
        return False


def _mark_done():
    if kodi_utils is None:
        return
    try:
        kodi_utils.set_setting(TUNE_FLAG, TUNE_VERSION)
    except Exception:
        pass


def _pov_addon():
    if xbmcaddon is None:
        return None
    try:
        return xbmcaddon.Addon(POV_ADDON_ID)
    except Exception:
        return None


# Per-key memory of the value WE last wrote, so a FUTURE TUNE_VERSION bump can
# tell "still on our value" (safe to re-tune) apart from "the user changed it
# since" (hands off). Without this, every version bump re-forced all DESIRED
# keys and silently overrode a user's deliberate opt-out -- the "every update
# resets my settings" complaint. JSON dict {key: value_we_set} in our own
# addon settings (survives updates).
STATE_FLAG = '_pov_scraper_tune_state'


def _load_state():
    if kodi_utils is None:
        return {}
    try:
        import json
        raw = kodi_utils.get_setting(STATE_FLAG, '') or ''
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(state):
    if kodi_utils is None:
        return
    try:
        import json
        kodi_utils.set_setting(STATE_FLAG, json.dumps(state))
    except Exception:
        pass


def ensure_patched():
    """Returns 'already' | 'no_pov' | 'unchanged' | 'patched'."""
    if _already_done():
        return 'already'
    addon = _pov_addon()
    if addon is None:
        return 'no_pov'  # not installed yet -- retry next startup, do not mark

    state = _load_state()
    changed = []
    for key, want in DESIRED:
        try:
            cur = addon.getSetting(key)
        except Exception:
            cur = None
        if cur is None:
            continue  # key absent in this POV schema -- leave it alone
        cur_norm = (cur or '').strip().lower()
        if cur_norm == want:
            state[key] = want
            continue
        # A recorded prior write that no longer matches the live value means
        # the USER changed this key since we set it -- respect their choice
        # even across a TUNE_VERSION bump.
        if key in state and cur_norm != (state.get(key) or '').strip().lower():
            _log('skipping {0}: user-changed since last tune '
                 '(now {1!r})'.format(key, cur), level='INFO')
            continue
        try:
            addon.setSetting(key, want)
            state[key] = want
            changed.append('{0}={1}'.format(key, want))
        except Exception as e:
            _log('failed to set {0}: {1}'.format(key, e), level='WARNING')

    for key, floor in MINIMUMS:
        try:
            cur = addon.getSetting(key)
        except Exception:
            cur = None
        if cur is None:
            continue  # key absent in this POV schema -- leave it alone
        raw = (cur or '').strip()
        try:
            cur_val = int(float(raw)) if raw else None
        except ValueError:
            _log('leaving {0} alone: {1!r} is not a number'.format(key, cur),
                 level='WARNING')
            continue
        if cur_val is not None and cur_val >= floor:
            # Already at or above the floor -- including a user who raised it
            # further. Record it so a later bump can still tell ours from
            # theirs, and do not touch the value.
            state[key] = str(cur_val)
            continue
        if key in state and raw != (state.get(key) or '').strip():
            _log('skipping {0}: user-changed since last tune '
                 '(now {1!r})'.format(key, cur), level='INFO')
            continue
        try:
            addon.setSetting(key, str(floor))
            state[key] = str(floor)
            changed.append('{0}={1} (was {2!r})'.format(key, floor, raw))
        except Exception as e:
            _log('failed to raise {0}: {1}'.format(key, e), level='WARNING')

    _save_state(state)
    _mark_done()
    if changed:
        _log('tuned ' + ', '.join(changed), level='INFO')
        return 'patched'
    return 'unchanged'
