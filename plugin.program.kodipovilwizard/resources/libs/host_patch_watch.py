"""Repair hooks after Kodi updates a host during an existing session.

Idle polling only stats addon.xml. It does no network work and never replaces
an addon, restarts Kodi, or edits a playing video's code.
"""
import os
import hashlib
import json
import time

AF3_ID = 'skin.arctic.fuse.3'

def af3_font_current(addons):
    """False when Arctic Fuse 3 is installed without the build's Hebrew font.

    Kodi replaces the whole skin folder on an update, Font.xml included, and
    the developer's fonts have no Hebrew: Kodi's own Hebrew (dates, "last
    login", menus) then shows as boxes, on the next login screen too (field
    report, 22 Oct 2026). MoranSubs' af3_home_patcher writes the NotoSans
    fontset."""
    if not os.path.isfile(os.path.join(addons, AF3_ID, 'addon.xml')):
        return True
    try:
        with open(os.path.join(addons, AF3_ID, '1080i', 'Font.xml'), 'rb') as handle:
            return b'NotoSans-Regular.ttf' in handle.read()
    except OSError:
        return False


def repair_af3(addons, window, monitor):
    """Re-apply the build's edits to Arctic Fuse 3 after Kodi updated it.

    The update wipes two sets of them. The Wizard's own -- child-profile home
    gating, the profile bootstrap and the branded login screen -- are written
    again here (install_login_hooks reloads the skin itself when a child
    policy is active). MoranSubs' -- Hebrew font and strings, POV search,
    Discover and the subtitle dialog -- come from its repair_af3.py, which
    waits for MoranSubs' own start-up pass and for playback to end, then
    rebuilds and reloads the skin. Best effort: the next Kodi start applies
    both anyway, so a failure here is logged, never retried in a loop.
    Returns None when Kodi is closing."""
    import xbmc
    try:
        from resources.libs import build_profiles
        build_profiles.install_login_hooks()
    except Exception as exc:
        xbmc.log('[POV IL] Arctic Fuse 3 profile hooks deferred: {!r}'.format(exc), xbmc.LOGWARNING)
    result = run_moransubs_repair(addons, window, monitor, 'repair_af3.py',
                                  'kodipovil.af3_repair.', wait=60, missing=True)
    xbmc.log('[POV IL] Arctic Fuse 3 update repair acknowledged={}'.format(result), xbmc.LOGINFO)
    return None if result is None else True


def repair_changed(addons, previous, current, window, monitor):
    import xbmc
    from resources.libs.patch_engine import PatchEngine
    old = dict((row[0], row[1:]) for row in previous)
    changed = [row[0] for row in current if old.get(row[0]) != row[1:]]
    # The patch engine has nothing for Arctic Fuse; an AF3 update alone does
    # not repeat the start-up pass on slow boxes.
    hooks = current[0][1] is not None and any(name != AF3_ID for name in changed)
    stats = PatchEngine().run() if hooks else {}
    healthy = not any(stats.get(key, 0) for key in
                      ('failed', 'missing', 'anchor_missing', 'malformed', 'legacy_host_deferred'))
    umbrella_changed = current[1][1] is not None and old.get(current[1][0]) != current[1][1:]
    if umbrella_changed:
        repaired = repair_umbrella(addons, window, monitor)
        if repaired is None:
            return False
        healthy = healthy and repaired
    if any(row[0] in ('skin.fentastic', 'script.fentastic.helper') and
           old.get(row[0]) != row[1:] for row in current):
        from resources.libs import fentastic_widgets
        fentastic_widgets.repair()
    if any(row[0] == AF3_ID and row[1] is not None and old.get(row[0]) != row[1:]
           for row in current):
        if repair_af3(addons, window, monitor) is None:
            return False
    xbmc.log('[POV IL] Host-update patch repair: {} acknowledged={}'.format(stats, healthy), xbmc.LOGINFO)
    return healthy

def repair_umbrella(addons, window, monitor):
    """Run MoranSubs' Umbrella patchers (its repair_hosts.py) and wait for
    their answer. True when every one reports a good state, False when not or
    no answer came within 20 s, None when Kodi is closing.

    Also used by the Wizard's version gate right after it installs a verified
    Umbrella: this watch takes its baseline after the start-up update check,
    so it never sees that change, and MoranSubs patched the old tree at start."""
    return run_moransubs_repair(addons, window, monitor, 'repair_hosts.py',
                                'kodipovil.host_repair.')


def run_moransubs_repair(addons, window, monitor, script_name, ack_prefix,
                         wait=20, missing=False):
    """RunScript one of MoranSubs' repair scripts and wait for its answer.
    `missing` is the result when that MoranSubs has no such script."""
    import xbmc
    import uuid
    ack = ack_prefix + uuid.uuid4().hex
    script = os.path.join(addons, 'service.subtitles.kodipovilai', script_name)
    if not os.path.isfile(script):
        return missing
    try:
        xbmc.executebuiltin('RunScript({}, {})'.format(script, ack))
        for _ in range(wait):
            result = window.getProperty(ack)
            if result:
                return json.loads(result).get('ok') is True
            if monitor.waitForAbort(1):
                return None
        return False
    except Exception:
        return False
    finally:
        window.clearProperty(ack)


def prebuild_lists():
    """Build one POV list ahead of its first visit while Kodi is idle (see
    pov_list_snapshot.prebuild_tick). Never fails the watch loop."""
    import sys
    import xbmc
    import xbmcvfs
    try:
        patches = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')
        if patches not in sys.path:
            sys.path.append(patches)
        import pov_list_snapshot
        pov_list_snapshot.prebuild_tick(xbmc)
    except Exception:
        pass


def resign_lists():
    """On Kodi's way out, after this session's last cache and sync writes:
    record the current file times of the most recent saved lists whose
    content did not change, so the first home rows of the next start are
    proven by file times alone. Files and SQLite only -- no GUI call (the
    GUI thread is waiting for this interpreter). Bounded to 1.5 s."""
    import sys
    import xbmcvfs
    try:
        patches = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')
        if patches not in sys.path:
            sys.path.append(patches)
        import pov_list_snapshot
        import xbmc
        pov_list_snapshot.DB_TIMEOUT = 0.3     # Kodi is closing: never wait on a lock
        done = pov_list_snapshot.resign(xbmcvfs.translatePath('special://profile/addon_data/plugin.video.pov/'),
                                        limit=12, budget_s=1.5)
        xbmc.log('[POV IL snapshot] on exit: {} saved list(s) re-checked'.format(done), xbmc.LOGINFO)
    except Exception as error:
        try:
            import xbmc
            xbmc.log('[POV IL snapshot] on exit: re-check skipped ({})'.format(type(error).__name__), xbmc.LOGINFO)
        except Exception:
            pass


def warm_bytecode(addons, monitor):
    """Write .pyc files Kodi never writes itself (see pyc_warm); next pass time."""
    import xbmc
    started = time.monotonic()
    try:
        from resources.libs import pyc_warm
        player = xbmc.Player()
        compiled, current, failed = pyc_warm.warm(
            addons, should_stop=monitor.abortRequested,
            should_pause=player.isPlayingVideo,
            sleep=monitor.waitForAbort)
        xbmc.log('[POV IL] bytecode: {} compiled, {} current, {} skipped in {:.1f}s'.format(
            compiled, current, failed, time.monotonic() - started), xbmc.LOGINFO)
    except Exception as exc:
        xbmc.log('[POV IL] bytecode pass failed: {!r}'.format(exc), xbmc.LOGWARNING)


def signature(addons):
    result = []
    for addon in ('plugin.video.pov', 'plugin.video.umbrella',
                  'skin.fentastic', 'script.fentastic.helper', AF3_ID):
        path = os.path.join(addons, addon, 'addon.xml')
        try:
            info = os.stat(path)
            result.append((addon, info.st_mtime_ns, info.st_size))
        except OSError:
            result.append((addon, None, None))
    return tuple(result)

def run():
    import xbmc
    import xbmcgui
    import xbmcvfs
    profile = os.path.normcase(os.path.realpath(xbmcvfs.translatePath('special://profile/')))
    prop = 'kodipovil.host_patch_watch.v2.' + hashlib.sha256(profile.encode('utf8')).hexdigest()
    window = xbmcgui.Window(10000)
    if window.getProperty(prop):
        return
    import uuid
    token = uuid.uuid4().hex
    window.setProperty(prop, token)
    monitor = xbmc.Monitor()
    addons = xbmcvfs.translatePath('special://home/addons/')
    previous = signature(addons)
    if not af3_font_current(addons):
        # Kodi's start-up repository check updated AF3 alongside the build's
        # own start-up (QA: MoranSubs patched 3.4.4 a second before 3.4.6
        # replaced it). Treat AF3 as changed so the first settled poll repairs.
        previous = tuple((row[0], -1, -1) if row[0] == AF3_ID else row for row in previous)
    pending = None
    retry_at = 0
    attempts = 0
    # Bytecode passes count idle 10 s polls: the first once start-up and the
    # home widgets have settled (~70 s), then about every 6 hours for Kodi's
    # own add-on updates, and soon after a host repair rewrote files.
    idle_polls, warm_after = 0, 6
    try:
        while not monitor.waitForAbort(10):
            current = signature(addons)
            if current == previous:
                pending = None
                attempts = 0
                idle_polls += 1
                if idle_polls >= 3:
                    prebuild_lists()
                if idle_polls >= warm_after and not xbmc.Player().isPlayingVideo():
                    warm_bytecode(addons, monitor)
                    idle_polls, warm_after = 0, 6 * 360
                continue
            if xbmc.Player().isPlayingVideo():
                continue
            # Observe a stable install for two polls before touching it.
            if pending != current:
                pending = current
                attempts = 0
                retry_at = 0
                continue
            if time.monotonic() < retry_at:
                continue
            # A temporarily removed addon or partial write is not a completed update.
            removed = any(row[1] is None and previous[i][1] is not None
                          for i, row in enumerate(current))
            try:
                repaired = not removed and repair_changed(addons, previous, current, window, monitor)
            except Exception:
                repaired = False
            if repaired and signature(addons) == current:
                previous = current
                pending = None
                attempts = 0
                # The host's files just changed: recompile them soon.
                idle_polls, warm_after = 0, min(warm_after, 3)
            else:
                attempts += 1
                # Fast recovery for a file lock, then bounded idle backoff for
                # an unsupported upstream change. Never mark failed work done.
                retry_at = time.monotonic() + (10 if attempts == 1 else 30 if attempts == 2 else 300)
                xbmc.log('[POV IL] Host-update repair pending; attempt {}'.format(attempts), xbmc.LOGWARNING)
    finally:
        if monitor.abortRequested():
            # Kodi's GUI thread waits for this interpreter during unload.
            # Window property getters acquire its GUI lock and can deadlock.
            # Queue cleanup without reading that lock; the key is profile-local.
            xbmc.executebuiltin('ClearProperty({},home)'.format(prop))
            resign_lists()
        elif window.getProperty(prop) == token:
            window.clearProperty(prop)
