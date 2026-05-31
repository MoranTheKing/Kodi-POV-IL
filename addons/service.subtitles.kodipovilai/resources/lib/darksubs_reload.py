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


def request_reload():
    """Disable+enable DarkSubs so its reuselanguageinvoker interpreter
    re-imports the patched source. Debounced to once per process. Safe
    no-op if Kodi APIs are unavailable. Returns True if a cycle ran."""
    global _cycled
    if _cycled:
        return False
    if xbmc is None:
        return False
    _cycled = True
    try:
        off = _set_enabled(False)
        # brief settle so the interpreter is actually torn down
        try:
            xbmc.sleep(800)
        except Exception:
            pass
        on = _set_enabled(True)
        if off and on:
            _log('cycled DarkSubs (disable/enable) so it re-imports the '
                 'patched source', level='INFO')
            return True
        _log('DarkSubs enable/disable returned off={0} on={1}'.format(
            off, on), level='WARNING')
        # Make sure we leave it ENABLED even if the disable half failed.
        if not on:
            _set_enabled(True)
        return False
    except Exception as e:
        _log('reload failed: {0}'.format(e), level='WARNING')
        try:
            _set_enabled(True)
        except Exception:
            pass
        return False
