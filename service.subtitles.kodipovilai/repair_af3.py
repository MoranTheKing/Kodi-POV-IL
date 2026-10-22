"""Bounded, non-network repair after Kodi updates Arctic Fuse 3 in this session.

Kodi replaces the whole skin folder on an update. The build's Hebrew font
(Font.xml + NotoSans), the Hebrew strings and the POV search, Discover and
subtitle-dialog edits go with it, and Kodi reloads the skin with the
developer's font: Hebrew shows as boxes for the rest of the session and on
the login screen of the next start (field report, 22 Oct 2026, AF3 3.4.4 ->
3.4.6). The Wizard's host watch runs this as soon as the update settles.

Run in its own interpreter, so it may wait without holding anything up:
  * for this service's start-up pass, which runs the same patchers -- two
    interpreters writing the skinvariables node files at once can tear them;
  * for playback to end -- the rebuild ends in ReloadSkin;
  * for POV to settle when af3_home_patcher defers its rebuild, and then
    rebuilds once itself: the home marker lives in addon_data and survives
    the update, so a second ensure_patched() would only say already_patched
    and the restored font would stay unloaded until the next start.
"""
import json
import sys
import time

import xbmc
import xbmcgui

from resources.lib import kodi_utils

# Statuses that will not change by running again: done, nothing to patch, or
# an anchor AF3 moved (a later MoranSubs fixes that, a retry cannot).
GOOD = {'patched', 'patched_rebuilt', 'already_patched', 'upgrade_requested',
        'no_af3', 'no_file', 'unmatched', 'deferred_done'}
LOCK = 'kodipovil.af3_repair.running'
REPAIRS_DONE_PROPERTY = 'kodipovil_startup_repairs_done'


def _wait(monitor, window, condition, seconds, step=2, settle=0):
    """True once condition() has held for `settle` seconds; False on timeout;
    None when Kodi closes. Monotonic: a box without a real-time clock jumps
    forward on its first time sync. Keeps this run's lock fresh meanwhile."""
    end = time.monotonic() + seconds
    held = None
    while True:
        now = time.monotonic()
        if condition():
            held = now if held is None else held
            if now - held >= settle:
                return True
        else:
            held = None
        if now >= end:
            return False
        window.setProperty(LOCK, str(now))
        if monitor.waitForAbort(step):
            return None


def repair(monitor, window):
    results = {}
    # Start-up pass first (bounded: a MoranSubs without the build pass never
    # publishes it, and the repair is still wanted).
    if _wait(monitor, window, lambda: bool(window.getProperty(REPAIRS_DONE_PROPERTY)), 180) is None:
        return None
    player = xbmc.Player()
    # Quiet for 30 s, not one instant: POV's autoplay leaves a gap between
    # episodes, and a skin reload there closes its next-episode dialogs.
    if _wait(monitor, window, lambda: not player.isPlaying(), 6 * 3600, step=5, settle=30) is not True:
        return None
    try:
        from resources.lib import af3_dialog_subtitles_patcher
        results['af3_dialog_subtitles_patcher'] = af3_dialog_subtitles_patcher.ensure_patched()
    except Exception:
        results['af3_dialog_subtitles_patcher'] = 'failed'
    try:
        from resources.lib import af3_home_patcher
        status = af3_home_patcher.ensure_patched()
        if status.startswith('rebuild_deferred'):
            from resources.lib import pov_reload
            settled = pov_reload.wait_until_settled(timeout=120)
            if (settled and af3_home_patcher._is_af3_active() and not player.isPlaying()
                    and af3_home_patcher._rebuild_af3_shortcuts()):
                status = 'deferred_done'
        results['af3_home_patcher'] = status
    except Exception:
        results['af3_home_patcher'] = 'failed'
    kodi_utils.log('Arctic Fuse 3 update repair: {}'.format(results))
    return results


window = xbmcgui.Window(10000)
monitor = xbmc.Monitor()
ack = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith('kodipovil.af3_repair.') else ''
try:
    started = float(window.getProperty(LOCK) or 0)
except ValueError:
    started = 0
# time.monotonic() is shared by every interpreter in the Kodi process; a run
# refreshes the lock while it waits, so 15 min without a refresh is a dead run.
if started and 0 <= time.monotonic() - started < 900:
    # Another run is still waiting or working; it covers this update too.
    results = {'af3_repair': 'already_running'}
else:
    window.setProperty(LOCK, str(time.monotonic()))
    try:
        results = repair(monitor, window)
    finally:
        window.clearProperty(LOCK)
if ack and results is not None:
    window.setProperty(ack, json.dumps({
        'ok': bool(results) and all(value in GOOD or value == 'already_running'
                                    for value in results.values())}))
