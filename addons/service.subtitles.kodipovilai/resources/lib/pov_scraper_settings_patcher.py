# One-time tune of plugin.video.pov's scraper settings for the build.
#
# The build owner WANTS pre-release (CAM/SCR/TELE) and 3D results included by
# default, so this restores both to ON. v1 of this patcher briefly turned
# pre-release/3D off; v2 restores them, and because the marker version changed
# it re-applies on any device that got v1.
#
# provider.piratebay: OFF, on the build owner's instruction (2026-08-15). It
# had been turned ON here for source counts; that is reversed. POV's own
# default for it is true, so this has to be written rather than simply dropped
# from the list -- removing the key would leave every existing device on the
# 'true' we ourselves put there, and would let a fresh POV install turn it on
# again from its own default.
#
# A USER WHO TURNS IT BACK ON KEEPS IT ON. That is not a special case added for
# this key, it is what the state map below already guarantees: we remember the
# value WE wrote, and any key whose live value has drifted from that is treated
# as the user's and never touched again -- including across a future version
# bump. Verified against the real flow, not assumed.
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
    import xbmcgui
except Exception:
    xbmcgui = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
TUNE_FLAG = '_pov_scraper_tune'

# The marker carries a fingerprint of what we actually intend to write, not a
# number someone has to remember to bump. Editing DESIRED or MINIMUMS -- adding
# a key, or changing a floor from 20 to 30 -- changes the fingerprint, so the
# tune re-runs on devices that already ran the previous one. The hand-bumped
# version alone did not do that: a floor could be edited while TUNE_VERSION
# stayed put, _already_done() would short-circuit before the loop, and every
# device that had run the old value would keep it forever.
_TUNE_BASE = 'v3'


def _tune_version():
    try:
        import hashlib
        payload = repr((tuple(DESIRED), tuple(MINIMUMS))).encode('utf-8')
        return '%s-%s' % (_TUNE_BASE,
                          hashlib.md5(payload).hexdigest()[:8])
    except Exception:
        return _TUNE_BASE

# id -> desired value ('true'/'false' as POV stores bools).
DESIRED = (
    ('include_prerelease_results', 'true'),
    ('include_3d_results', 'true'),
    ('provider.piratebay', 'false'),
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
# expects.
#
# 20 -- POV's own new default, not a number of our own. An earlier draft used
# 30, reasoning from a phase-by-phase split of the reported log. Two things
# argued it back down:
#
#   * the split was not as measured as it looked. It rested on reading Kodi's
#     generic "CPythonInvoker ... waiting on thread" line as the boundary
#     between the provider phase and the debrid phase, and that line only means
#     the script returned while some thread is still alive -- which, given
#     tpe.shutdown(False) deliberately leaves workers running, it would say
#     either way. Nothing in the log marks where phase 2 began.
#
#   * this setting is not only the two thread_monitor budgets. THREE of POV's
#     debrid backends take it as their per-request HTTP timeout for EVERY call
#     they make:
#
#         debrids/torbox_api.py:19      self.timeout = int(get_setting('scrapers.timeout.1') or 10)
#         debrids/premiumize_api.py:17  ...
#         debrids/offcloud_api.py:17    ...
#
#     including unrestrict_link on the FOREGROUND resolve path, where POV walks
#     up to limit_resolve sources in sequence (default 10) while the user
#     watches a dialog. Against a slow-but-alive debrid that is 10 x timeout,
#     so 30 would take the worst case from ~100s to ~300s. Doubling that cost
#     needs better evidence than we have; matching upstream does not.
#
# Raising it at all is close to free when things are healthy -- thread_monitor
# stops the moment the last thread finishes, so a fast scrape is just as fast
# at 20 as at 10. The cost lands only on the genuinely slow or dead case, which
# is the right side to err on: a longer wait explains itself, "no results" on a
# title with hundreds of sources does not.
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
        return kodi_utils.get_setting(TUNE_FLAG, '') == _tune_version()
    except Exception:
        return False


def _mark_done():
    if kodi_utils is None:
        return
    try:
        kodi_utils.set_setting(TUNE_FLAG, _tune_version())
    except Exception:
        pass


def _pov_addon():
    if xbmcaddon is None:
        return None
    try:
        return xbmcaddon.Addon(POV_ADDON_ID)
    except Exception:
        return None


def _write_verified(addon, key, value):
    """setSetting, then read it back. True only if the value really landed.

    Our own kodi_utils.set_setting already works this way, for a reason stated
    there: some Kodi/Android combinations accept a setSetting call, return
    successfully, and never write the value to disk. That applies at least as
    much to a CROSS-addon write as to our own, and the consequence here is
    worse -- a swallowed write that still counted as done would mark the tune
    complete, and _already_done() would then skip the retry on every future
    boot. The setting would sit broken forever with nothing in the log.
    """
    try:
        addon.setSetting(key, value)
    except Exception as e:
        _log('failed to set {0}: {1}'.format(key, e), level='WARNING')
        return False
    try:
        got = addon.getSetting(key)
    except Exception:
        return True   # cannot read back -- assume the write took, do not loop
    if (got or '').strip() == value:
        return True
    _log('write to {0} did not persist (asked {1!r}, read back {2!r})'.format(
        key, value, got), level='WARNING')
    return False


def _invalidate_pov_settings_cache():
    """Drop POV's cached settings snapshot so it re-reads from disk.

    POV does not call getSetting per read. modules.kodi_utils.SettingsManager
    serves every lookup from a JSON blob kept in the 'pov_settings' window
    property, and only rebuilds it when that property changes -- which POV
    itself does at its own service startup and from onSettingsChanged. Neither
    fires for a write made from another add-on, so without this the value is
    correct on disk while POV's running process keeps handing out the old one,
    and the fix appears to do nothing at all.

    pov_aiostreams_patcher already learned this and does the same thing; the
    note in pov_mdblist_patcher records the same discovery from the other
    direction. Clearing the property is the cheap half of that lesson.
    """
    if xbmcgui is None:
        return
    try:
        xbmcgui.Window(10000).clearProperty('pov_settings')
    except Exception:
        pass


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
    changed, failed = [], []
    for key, want in DESIRED:
        try:
            cur = addon.getSetting(key)
        except Exception:
            cur = None
        if cur is None:
            # Only reached when getSetting RAISED. It does not mean "POV has no
            # such key" -- Kodi answers an unknown id with '', not an error, so
            # a key POV has dropped reads as empty and gets written. That is
            # deliberate rather than merely tolerated: an empty read also
            # happens transiently while POV is still coming up, and skipping on
            # it would mark the tune done and never retry, leaving the setting
            # wrong forever. Writing a stray id Kodi then ignores is the
            # cheaper mistake of the two.
            continue
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
        if not _write_verified(addon, key, want):
            failed.append(key)
            continue
        state[key] = want
        changed.append('{0}={1}'.format(key, want))

    for key, floor in MINIMUMS:
        try:
            cur = addon.getSetting(key)
        except Exception:
            cur = None
        if cur is None:
            # Only reached when getSetting RAISED. It does not mean "POV has no
            # such key" -- Kodi answers an unknown id with '', not an error, so
            # a key POV has dropped reads as empty and gets written. That is
            # deliberate rather than merely tolerated: an empty read also
            # happens transiently while POV is still coming up, and skipping on
            # it would mark the tune done and never retry, leaving the setting
            # wrong forever. Writing a stray id Kodi then ignores is the
            # cheaper mistake of the two.
            continue
        raw = (cur or '').strip()
        try:
            cur_val = int(float(raw)) if raw else None
        except (ValueError, OverflowError):
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
        if not _write_verified(addon, key, str(floor)):
            failed.append(key)
            continue
        state[key] = str(floor)
        changed.append('{0}={1} (was {2!r})'.format(key, floor, raw))

    _save_state(state)
    if changed:
        _invalidate_pov_settings_cache()
    if failed:
        # Do NOT mark done: marking would make _already_done() short-circuit
        # every future boot and the value would stay broken forever, silently.
        # Leaving the marker unset costs one cheap retry per startup instead.
        _log('not marking done -- {0} write(s) did not persist: {1}'.format(
            len(failed), ', '.join(failed)), level='WARNING')
        return 'write_failed'
    _mark_done()
    if changed:
        _log('tuned ' + ', '.join(changed), level='INFO')
        return 'patched'
    return 'unchanged'
