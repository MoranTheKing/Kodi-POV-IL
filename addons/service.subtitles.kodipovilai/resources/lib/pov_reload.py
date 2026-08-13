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


# HOW WE KNOW POV IS UNUSABLE: WE ASK IT. No shared state, no cross-process
# record -- five validation rounds of a Window(10000) count-and-deadlines
# scheme each found a new way it was wrong, and the question it existed to
# answer needs no coordination at all.
#
# WHAT REPLACED IT FIRST, AND WHY THAT WAS ALSO WRONG. The probe cannot tell
# "POV is mid-cycle" from "POV is not installed", so the first attempt kept a
# sticky "I have seen POV work in this process" flag and treated a failure as a
# cycle only after that. It reads sensibly and it is broken twice over: the
# FIRST call in any process is always told "not cycling", because the flag
# still holds its default -- and the wizard's plugin entry point declares
# reuselanguageinvoker=false, so Kodi hands it a brand-new interpreter on every
# single invocation. The AF3 tools-row guard built on that flag could therefore
# never fire, on any platform, ever, while looking correct on the page.
#
# So there is no flag. is_cycling() is exactly "POV cannot be constructed right
# now", which is true on the first call in a cold process and true in the
# wizard's throwaway interpreter. Absence is handled where it belongs -- in the
# waiting, not the asking -- by _gave_up below.
_gave_up = False
_timeouts = 0


def _is_resolvable():
    """Can plugin.video.pov actually be CONSTRUCTED right now?

    Not the same question as "is it enabled". Addons.GetAddonDetails reports
    enabled=true as soon as the flag is set, while this call -- the one POV's
    own kodi_utils makes on its first line, and the one that raises "Unknown
    addon id" in the field logs -- keeps failing for a moment afterwards.
    """
    try:
        import xbmcaddon
        xbmcaddon.Addon(POV_ADDON_ID)
        return True
    except Exception:
        return False


def is_cycling():
    """True while POV cannot be constructed.

    With no Kodi at all there is nothing to guard, and answering "cycling"
    would make every guard in the build block on a machine where none of this
    applies. Absence of Kodi is not a POV cycle.
    """
    if xbmc is None:
        return False
    return _armed or _cycling or not _is_resolvable()


def wait_until_settled(timeout=8):
    """Block until POV can be constructed again. True when it is safe.

    THE TIMEOUT IS SHORT, AND GIVING UP IS REMEMBERED. A user who turns POV off
    deliberately -- or who never had it -- leaves it unconstructible for good,
    and an unbounded reading of "not constructible means wait" made every
    guarded reload in the build stall for the full timeout, every time, for the
    rest of the session. Measured at the previous 30s default: 62 add-on
    constructions and a real 30-second stall per call site, for a condition
    that was never going to clear.

    So the wait is bounded at a few times the ~2.7s window actually observed,
    and once it has run out we ask Kodi whether POV is switched off. If it is,
    this is not a cycle and never was: stop waiting for it, for the rest of
    this process. If Kodi says it is enabled and it still cannot be built, that
    is strange enough to keep being careful about, so no latch is set.
    """
    global _gave_up, _timeouts
    if _gave_up or xbmc is None:
        return True
    if not is_cycling():
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
    _timeouts += 1
    if _is_enabled() is not True:
        # Kodi says POV is switched off, or cannot find it at all. Either way
        # this is not a cycle and never was, so stop paying for it. NOT INSTALLED
        # counts here too: dropping the old sticky flag fixed a cold process
        # being blind, but it also meant a user who simply does not have POV
        # started paying a wait at every guarded site. One bounded wait per
        # process is the price of the cold-start fix; more than that is not.
        _gave_up = True
        _log('POV is not switched on; not waiting for it again this session',
             level='WARNING')
        return True
    if _timeouts >= 3:
        # Enabled, yet still unconstructible after three full waits. Whatever
        # this is, it is not a window that is about to pass, and paying the
        # timeout at every guarded site for the rest of the session helps
        # nobody. Three strikes bounds the total cost at a few seconds per
        # process while still being patient with a genuinely slow cycle.
        _gave_up = True
        _log('POV reports enabled but will not construct after {0} waits; '
             'proceeding without it'.format(_timeouts), level='WARNING')
        return True
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
