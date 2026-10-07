"""Repair hooks after Kodi updates a host during an existing session.

Idle polling only stats addon.xml. It does no network work and never replaces
an addon, restarts Kodi, or edits a playing video's code.
"""
import os
import hashlib
import json
import time

def repair_changed(addons, previous, current, window, monitor):
    import xbmc
    from resources.libs.patch_engine import PatchEngine
    old = dict((row[0], row[1:]) for row in previous)
    stats = PatchEngine().run() if current[0][1] is not None else {}
    healthy = not any(stats.get(key, 0) for key in
                      ('failed', 'missing', 'anchor_missing', 'malformed', 'legacy_host_deferred'))
    umbrella_changed = current[1][1] is not None and old.get(current[1][0]) != current[1][1:]
    if umbrella_changed:
        import uuid
        ack = 'kodipovil.host_repair.' + uuid.uuid4().hex
        script = os.path.join(addons, 'service.subtitles.kodipovilai', 'repair_hosts.py')
        if not os.path.isfile(script):
            healthy = False
        else:
            try:
                xbmc.executebuiltin('RunScript({}, {})'.format(script, ack))
                for _ in range(20):
                    result = window.getProperty(ack)
                    if result:
                        healthy = healthy and json.loads(result).get('ok') is True
                        break
                    if monitor.waitForAbort(1):
                        return False
                else:
                    healthy = False
            except Exception:
                healthy = False
            finally:
                window.clearProperty(ack)
    if any(row[0] in ('skin.fentastic', 'script.fentastic.helper') and
           old.get(row[0]) != row[1:] for row in current):
        from resources.libs import fentastic_widgets
        fentastic_widgets.repair()
    xbmc.log('[POV IL] Host-update patch repair: {} acknowledged={}'.format(stats, healthy), xbmc.LOGINFO)
    return healthy

def signature(addons):
    result = []
    for addon in ('plugin.video.pov', 'plugin.video.umbrella',
                  'skin.fentastic', 'script.fentastic.helper'):
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
    pending = None
    retry_at = 0
    attempts = 0
    try:
        while not monitor.waitForAbort(10):
            current = signature(addons)
            if current == previous:
                pending = None
                attempts = 0
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
        elif window.getProperty(prop) == token:
            window.clearProperty(prop)
