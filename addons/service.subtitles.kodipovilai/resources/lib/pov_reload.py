# Force plugin.video.pov to re-import its patched sources.py after we modify it.
#
# Like DarkSubs, POV declares <reuselanguageinvoker>true</> and warms its Python
# interpreter at boot (its "ReuseLanguageInvokerCheck" service), so editing
# sources.py on disk does NOT take effect until the interpreter is torn down --
# our patch only applies a Kodi-restart later. Cycling POV (disable/enable via
# JSON-RPC, deferred until idle) makes the interpreter relaunch and re-import
# the patched source the same session.
#
# Mirrors darksubs_reload, with one extra guard: callers only arm this when the
# user has actually opted into the feature, so the 499 users who leave it off
# never get POV cycled.

import json

try:
    import xbmc
except Exception:
    xbmc = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
_cycled = False
_pending = False
# True from the moment POV is disabled until it can actually be constructed
# again. PUBLISHED ON PURPOSE: while this is set, plugin://plugin.video.pov/
# does not resolve, so anything that would make Kodi re-draw POV's widgets --
# above all ReloadSkin() -- has to wait. A user hit exactly that: the widget
# patcher reloaded the skin 0.6 s into this window, the home screen rebuilt,
# every POV widget raised "Unknown addon id", and POV's own service had to be
# killed for not stopping. The same update applied cleanly on NOX, where that
# patcher never runs -- which is what identified the pairing.
_cycling = False
# Raised the moment a cycle is REQUESTED, not when it begins. The cycle waits
# for the user to be idle first -- up to two minutes -- and a reload that asked
# "is POV cycling?" during that wait was told no, went ahead, and then had the
# disable land on the freshly rebuilt screen a few seconds later. Waiting has
# to cover the whole span from armed to finished, or it is just a smaller
# version of the same race.
_armed = False


# The window is announced on a Window(10000) property as well as in these
# globals, because THE WIZARD CYCLES POV TOO -- from its own add-on, in its own
# process, with raw Addons.SetAddonEnabled. Module globals cannot be seen
# across that boundary, so for the whole of the wizard's disable/enable dance
# every guard in this add-on reported "not cycling" and let a ReloadSkin
# straight through. Demonstrated: POV unresolvable, is_cycling() False,
# wait_until_settled() returning True instantly, and the reload firing through
# a "guarded" site. Window(10000) properties are how this build already passes
# state between add-ons (see REPAIRS_DONE_PROPERTY).
#
# THE VALUE IS AN EXPIRY, NOT A FLAG. A property is only cleared by whoever set
# it, so a process killed mid-cycle -- which is exactly the failure mode all of
# this exists to survive -- would leave it set until Kodi restarts, and block
# every skin reload for the rest of the session. Storing a deadline means the
# worst case is a short delay that heals itself.
_CYCLING_PROPERTY = 'kodipovil_pov_cycling_until'


def _publish_cycling(seconds):
    """Announce (or withdraw) the window for other add-ons."""
    try:
        import time
        import xbmcgui
        value = '' if not seconds else '%d' % int(time.time() + seconds)
        xbmcgui.Window(10000).setProperty(_CYCLING_PROPERTY, value)
    except Exception:
        pass


def _another_addon_is_cycling():
    try:
        import time
        import xbmcgui
        raw = (xbmcgui.Window(10000).getProperty(_CYCLING_PROPERTY) or '').strip()
        return bool(raw) and time.time() < float(raw)
    except Exception:
        return False


def is_cycling():
    """True while POV is, or is about to become, unresolvable -- whether this
    add-on is the one cycling it or the wizard is."""
    return _armed or _cycling or _another_addon_is_cycling()


def wait_until_settled(timeout=30):
    """Block until POV resolves again, or the timeout runs out.

    Returns True if it is safe to touch POV-backed UI. Callers that redraw
    widgets should check this rather than assuming; the cost of waiting is a
    delayed refresh, and the cost of not waiting is a broken home screen.
    """
    if not is_cycling() or xbmc is None:
        return True
    waited = 0.0
    while waited < timeout:
        if not is_cycling():
            return True
        try:
            if xbmc.Monitor().waitForAbort(0.5):
                return False
        except Exception:
            return False
        waited += 0.5
    return not is_cycling()


def note_patched():
    global _pending
    _pending = True


def reload_if_patched():
    if _pending:
        return request_reload()
    return False


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_reload: ' + msg, level=level)
    except Exception:
        pass


def _set_enabled(enabled):
    if xbmc is None:
        return False
    payload = json.dumps({
        'jsonrpc': '2.0', 'id': 1, 'method': 'Addons.SetAddonEnabled',
        'params': {'addonid': POV_ADDON_ID, 'enabled': bool(enabled)},
    })
    try:
        return '"error"' not in (xbmc.executeJSONRPC(payload) or '')
    except Exception:
        return False


def _is_enabled():
    if xbmc is None:
        return None
    payload = json.dumps({
        'jsonrpc': '2.0', 'id': 1, 'method': 'Addons.GetAddonDetails',
        'params': {'addonid': POV_ADDON_ID, 'properties': ['enabled']},
    })
    try:
        data = json.loads(xbmc.executeJSONRPC(payload) or '{}')
        addon = (data.get('result') or {}).get('addon') or {}
        return bool(addon.get('enabled')) if 'enabled' in addon else None
    except Exception:
        return None


def _is_resolvable():
    """Can plugin.video.pov actually be CONSTRUCTED right now?

    Not the same question as "is it enabled", and the difference is the whole
    bug. Addons.GetAddonDetails reports enabled=true as soon as the flag is
    flipped, while xbmcaddon.Addon(id) -- the call POV's own kodi_utils makes
    on its very first line -- still raises "Unknown addon id". Declaring the
    cycle finished on the flag therefore released the UI a beat before the
    add-on could be used, which is precisely the beat the failures land in.
    This probes with the same call that fails, so success here means the thing
    callers are about to do will work."""
    try:
        import xbmcaddon
        xbmcaddon.Addon(POV_ADDON_ID)
        return True
    except Exception:
        return False


def request_reload():
    global _cycled, _armed
    if _cycled or xbmc is None:
        return False
    _cycled = True
    _armed = True
    try:
        import threading
        threading.Thread(target=_deferred_cycle, daemon=True).start()
        return True
    except Exception as e:
        _armed = False
        _log('could not start reload thread: {0}'.format(e), level='WARNING')
        return False


def _wait_until_idle(timeout=120):
    try:
        monitor = xbmc.Monitor()
    except Exception:
        return False
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


def _capture_home_focus():
    # Best-effort snapshot of the focused home control + its item position.
    # Disabling/enabling POV rebuilds every POV-backed home widget/tile, which
    # otherwise dumps the user back on the FIRST tile; we restore this afterward.
    try:
        if not xbmc.getCondVisibility('Window.IsVisible(home)'):
            return None
        cid = (xbmc.getInfoLabel('System.CurrentControlId') or '').strip()
        if not cid or cid == '0':
            return None
        # Use CurrentItem (1-based ABSOLUTE index), not Position. Position is the
        # on-screen SLOT, which on Estuary's home fixedlist (focusposition=0) is
        # pinned to "0" regardless of the selected tile -- so restoring by
        # Position always snapped focus back to the first tile. SetFocus expects
        # a 0-based absolute index, so convert CurrentItem (1-based) to 0-based.
        cur = (xbmc.getInfoLabel('Container(%s).CurrentItem' % cid) or '').strip()
        pos = str(int(cur) - 1) if cur.isdigit() and int(cur) > 0 else ''
        return (cid, pos)
    except Exception:
        return None


def _restore_home_focus(saved):
    if not saved or xbmc is None:
        return
    cid, pos = saved
    try:
        monitor = xbmc.Monitor()
        # Wait (bounded) for home + that container to repopulate after the cycle.
        for _ in range(20):
            if monitor.waitForAbort(0.5):
                return
            if not xbmc.getCondVisibility('Window.IsVisible(home)'):
                continue
            n = (xbmc.getInfoLabel('Container(%s).NumItems' % cid) or '').strip()
            if n and n != '0':
                break
        # Restore by ABSOLUTE index so it round-trips on Estuary's home
        # fixedlist (where the on-screen slot is pinned) as well as regular
        # lists/panels on FENtastic/NOX.
        cmd = ('SetFocus(%s,%s,absolute)' % (cid, pos)) if pos else ('SetFocus(%s)' % cid)
        xbmc.executebuiltin(cmd)
        _log('restored home focus -> control %s item %s' % (cid, pos),
             level='INFO')
    except Exception:
        pass


def _deferred_cycle():
    global _cycling, _armed
    try:
        if not _wait_until_idle():
            _log('aborted before cycle', level='WARNING')
            _armed = False
            return
        try:
            if xbmc.getCondVisibility('Player.HasMedia'):
                _log('media playing; skipping POV cycle (applies next launch)',
                     level='INFO')
                _armed = False
                return
        except Exception:
            pass
    except Exception:
        # Every early exit clears the armed flag. Leaving it set on a path that
        # never cycles would block skin reloads forever on a session where POV
        # was never touched at all.
        _armed = False
        raise
    saved_focus = _capture_home_focus()
    try:
        # Raised BEFORE the disable and lowered only once POV can be
        # constructed again, so the flag always covers the whole unresolvable
        # window rather than part of it.
        _cycling = True
        # 60s is a ceiling, not an expectation: the window is normally a couple
        # of seconds and the finally below withdraws it. It only matters if this
        # process dies mid-cycle.
        _publish_cycling(60)
        _set_enabled(False)
        try:
            xbmc.sleep(1500)
        except Exception:
            pass
        _set_enabled(True)
        # Never leave POV disabled: verify it came back, retry a few times.
        # THE TEST IS RESOLVABILITY, NOT THE ENABLED FLAG. The flag flips
        # immediately; the add-on stays unusable for a moment after, and
        # reporting success on the flag is what let the rest of the service
        # carry on into that moment.
        ok = False
        for _ in range(12):
            if _is_resolvable():
                ok = True
                break
            if _is_enabled() is not True:
                _set_enabled(True)
            try:
                xbmc.sleep(500)
            except Exception:
                pass
        _log('cycled POV (re-import patched sources); resolvable={0}'.format(ok),
             level='INFO')
        if not ok:
            _set_enabled(True)
        _restore_home_focus(saved_focus)
    except Exception as e:
        _log('cycle failed: {0}'.format(e), level='WARNING')
        try:
            _set_enabled(True)
        except Exception:
            pass
    finally:
        # Both lowered in a finally: a flag that stays raised because
        # something threw would block every future skin reload for the rest of
        # the session, trading a two-second fault for a permanent one.
        _cycling = False
        _armed = False
        _publish_cycling(0)
