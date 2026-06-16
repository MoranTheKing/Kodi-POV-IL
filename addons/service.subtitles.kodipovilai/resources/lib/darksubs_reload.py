# Force DarkSubs (service.subtitles.All_Subs) to re-import its patched
# source after we rewrite any of its .py files.
#
# Why this is needed: DarkSubs declares <reuselanguageinvoker>true</...>
# and runs autosub.py as a long-lived <xbmc.service>. So at Kodi boot a
# single Python interpreter imports autosub.py / engine.py / sub_window.py
# into memory and STAYS ALIVE for the whole session. When our patchers
# rewrite those files on disk and delete the .pyc, the already-running
# interpreter does NOT re-import them (sys.modules keeps the old objects),
# so our edits never take effect this session -- and because our service
# and DarkSubs's service both start at boot, even a Kodi restart races and
# usually loses. This is why the embedded-subtitle demote/insert patches
# (and any other DarkSubs source patch) appeared to "not apply".
#
# Fix: after a patch actually changes a DarkSubs file, disable then
# re-enable the DarkSubs addon via JSON-RPC. Disabling tears down its
# persistent interpreter; re-enabling relaunches the xbmc.service, which
# now imports the PATCHED source from disk. We debounce so we cycle at
# most once per startup no matter how many DarkSubs files changed.

import json

try:
    import xbmc
except Exception:
    xbmc = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


DARKSUBS_ADDON_ID = 'service.subtitles.All_Subs'

# Module-level debounce: only cycle once per service.py process.
_cycled = False
# Set by note_patched() when any DarkSubs source patch changed a file
# this run, so reload_if_patched() only cycles when there's something new.
_pending = False


def note_patched():
    """Record that a DarkSubs source file was just patched, so a reload
    is warranted at the end of the startup patch pass."""
    global _pending
    _pending = True


def reload_if_patched():
    """Cycle DarkSubs only if at least one source patch changed a file
    this run. One-shot (request_reload is itself debounced)."""
    if _pending:
        return request_reload()
    return False


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('darksubs_reload: ' + msg, level=level)
    except Exception:
        pass


def _set_enabled(enabled):
    if xbmc is None:
        return False
    payload = json.dumps({
        'jsonrpc': '2.0',
        'id': 1,
        'method': 'Addons.SetAddonEnabled',
        'params': {'addonid': DARKSUBS_ADDON_ID, 'enabled': bool(enabled)},
    })
    try:
        resp = xbmc.executeJSONRPC(payload)
        return '"error"' not in (resp or '')
    except Exception:
        return False


def _is_enabled():
    """Query DarkSubs's current enabled state. Returns True/False, or None if
    it can't be determined (not installed / API error)."""
    if xbmc is None:
        return None
    payload = json.dumps({
        'jsonrpc': '2.0',
        'id': 1,
        'method': 'Addons.GetAddonDetails',
        'params': {'addonid': DARKSUBS_ADDON_ID, 'properties': ['enabled']},
    })
    try:
        data = json.loads(xbmc.executeJSONRPC(payload) or '{}')
        addon = (data.get('result') or {}).get('addon') or {}
        if 'enabled' not in addon:
            return None
        return bool(addon.get('enabled'))
    except Exception:
        return None


def request_reload():
    """Cycle DarkSubs so its reuselanguageinvoker interpreter re-imports
    the patched source. Debounced to once per process. Safe no-op if Kodi
    APIs are unavailable. Returns True if a cycle was scheduled.

    IMPORTANT: the disable/enable now runs on a BACKGROUND thread that
    first waits for Kodi to finish booting and go idle. Doing the cycle
    inline during the AI service's startup pass DEADLOCKED Kodi: it
    disabled All_Subs while All_Subs's own xbmc.service (autosub.py) was
    still starting that same boot, leaving two interpreters fighting (the
    old one "didn't stop in 5 seconds - let's kill it" while a new one
    launched), which wedged the GUI and forced a force-stop on the first
    launch after every install/quick update. Deferring until the Home
    window is up and nothing is playing means All_Subs is idle in its
    waitForAbort loop and stops cleanly, so the cycle is harmless."""
    global _cycled
    if _cycled:
        return False
    if xbmc is None:
        return False
    _cycled = True
    try:
        import threading
        threading.Thread(target=_deferred_cycle, daemon=True).start()
        return True
    except Exception as e:
        _log('could not start deferred reload thread: {0}'.format(e),
             level='WARNING')
        return False


def _wait_until_idle(timeout=120):
    """Block until Kodi has booted (Home visible) and is not playing, or
    until timeout. Abort-aware. Returns True once idle, False on
    abort."""
    try:
        monitor = xbmc.Monitor()
    except Exception:
        return False
    # Let the boot storm settle regardless of window state.
    if monitor.waitForAbort(8):
        return False
    waited = 8
    while waited < timeout:
        try:
            home_up = xbmc.getCondVisibility('Window.IsVisible(home)')
            playing = xbmc.getCondVisibility('Player.HasMedia')
        except Exception:
            home_up, playing = True, False
        if home_up and not playing:
            return True
        if monitor.waitForAbort(2):
            return False
        waited += 2
    return True


def _deferred_cycle():
    """Background worker: wait for idle, then disable+enable DarkSubs."""
    if not _wait_until_idle():
        _log('deferred reload aborted before cycle', level='WARNING')
        return
    # If the user started playback while we waited, skip; the patch simply
    # takes effect next launch. Never tear an addon down mid-playback.
    try:
        if xbmc.getCondVisibility('Player.HasMedia'):
            _log('media playing; skipping DarkSubs cycle (applies next '
                 'launch)', level='INFO')
            return
    except Exception:
        pass
    try:
        off = _set_enabled(False)
        try:
            xbmc.sleep(1500)
        except Exception:
            pass
        _set_enabled(True)
        # CRITICAL: never leave DarkSubs disabled. The re-enable can race the
        # post-update boot, and a disabled DarkSubs means no subtitle service
        # and no AI-translation hook at all. Verify it actually came back on,
        # and retry a few times before giving up.
        on = False
        for _ in range(6):
            state = _is_enabled()
            if state is True:
                on = True
                break
            if state is False or state is None:
                _set_enabled(True)
            try:
                xbmc.sleep(1000)
            except Exception:
                pass
        if off and on:
            _log('cycled DarkSubs (disable/enable) so it re-imports the '
                 'patched source', level='INFO')
        else:
            _log('DarkSubs cycle off={0} on={1} (final state verified={2})'
                 .format(off, on, _is_enabled()), level='WARNING')
            _set_enabled(True)
    except Exception as e:
        _log('reload failed: {0}'.format(e), level='WARNING')
        try:
            _set_enabled(True)
        except Exception:
            pass
