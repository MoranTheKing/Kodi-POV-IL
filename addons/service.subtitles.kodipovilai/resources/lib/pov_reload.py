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
# So there is no flag, and there is no memory. is_cycling() is two questions
# asked fresh every time -- can POV be constructed, and is POV on disk -- and
# both are answered the same way on the first call in a cold process as on the
# thousandth, which is what makes it work in the wizard's throwaway interpreter
# as well as in the long-lived service. The disk is what separates "mid-cycle"
# from "not installed"; see _is_installed for why that question is not put to
# JSON-RPC.



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


def _is_installed():
    """Does POV exist on disk at all?

    This is how "mid-cycle" is told apart from "not installed", and it is
    deliberately NOT a JSON-RPC question. Addons.GetAddonDetails answers the
    same way -- no usable answer -- for an id Kodi has never heard of and for a
    call that failed because Kodi was busy, and Kodi is at its busiest during
    exactly the moment being guarded. Reading absence out of that reply makes
    the guard report SAFE in the middle of a real cycle: measured, a single
    transient RPC failure turned a genuine 5-second outage into an instant
    "go ahead", which is the original fault verbatim.

    Disabling an add-on does not delete its folder, so addon.xml is present
    throughout a cycle and missing only when POV genuinely is not installed.
    Anything that stops us reading the disk answers "installed", so an
    unanswerable question keeps the guard on rather than turning it off.
    """
    try:
        import xbmcvfs
    except Exception:
        return True
    for root in ('special://home/addons/', 'special://xbmc/addons/'):
        path = root + POV_ADDON_ID + '/addon.xml'
        try:
            # translate-then-exists, the same order the rest of this add-on
            # uses (af3_home_patcher._exists), so one convention covers all of
            # it. Note the except returns INSTALLED where _exists returns
            # missing: there, a failed check means "no file"; here it means
            # "no answer", and the safe reading of no answer is to keep
            # guarding.
            if xbmcvfs.exists(xbmcvfs.translatePath(path)):
                return True
        except Exception:
            return True
    return False


def is_cycling():
    """True while POV is installed but cannot be constructed.

    With no Kodi at all there is nothing to guard, and answering "cycling"
    would make every guard in the build block on a machine where none of this
    applies. Absence of Kodi is not a POV cycle, and neither is absence of POV.
    """
    if xbmc is None:
        return False
    if _armed or _cycling:
        return True
    if _is_resolvable():
        return False
    return _is_installed()


def wait_until_settled(timeout=30):
    """Block until POV can be constructed again. True when it is safe to go on.

    NO LATCH. An earlier version remembered "I gave up on POV" for the life of
    the process, to avoid paying a wait for someone who does not have POV. It
    was a single fuse in front of every guarded reload in the build, and
    ordinary things tripped it: one JSON-RPC hiccup while Kodi was busy, or a
    user taking half a minute over a settings toggle. Once tripped it never
    reset, so a later, genuine cycle went completely unguarded -- reproduced,
    with a real ReloadSkin firing against unresolvable POV and the AF3 rebuild
    marked done so it never retried. A guard that silently turns itself off for
    the rest of a session, while logging that it made a deliberate safe choice,
    is worse than no guard at all.

    What replaces it costs nothing and forgets nothing: POV that is not on disk
    is not cycling, so the user who does not have it never waits, on this call
    or any later one, without a flag being kept anywhere.

    THIRTY SECONDS, AND NOT MORE, BECAUSE OF WHERE THIS IS CALLED FROM. Three
    of the four call sites are steps in _run_build_startup_repairs(), which the
    service runs INLINE on its main thread in build mode -- so this number is
    not just a delayed reload, it is the subtitle service not starting. The
    armed span alone can legitimately last two minutes (the cycle waits for the
    user to stop navigating before it disables anything), and waiting that out
    would be correct and unusable. Thirty covers the ordinary sequence -- the
    cycle's own 8s settle plus its ~9s of downtime -- and gives up on the rest.

    THE TIMEOUT NEVER REPORTS SAFE. Running out of patience is not evidence
    that POV came back, and saying so is how the guard would fail open. Every
    caller treats False as "not now": it logs, leaves its work undone and
    unstamped, and the next service run tries again.
    """
    if xbmc is None:
        return True
    waited = 0.0
    while True:
        if not (_armed or _cycling):
            if _is_resolvable():
                return True
            if not _is_installed():
                # Kodi has no such add-on. Nothing to wait for, now or ever.
                return True
        if waited >= timeout:
            _log('POV still unresolvable after {0:.0f}s; telling the caller to '
                 'defer to its next run'.format(waited), level='WARNING')
            return False
        try:
            if xbmc.Monitor().waitForAbort(0.5):
                return False
        except Exception:
            return False
        waited += 0.5


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
    # ONE try/finally around the whole body, not one per stage. The flags are
    # cleared on every exit -- returns, exceptions, and the gaps BETWEEN the
    # stages alike. An earlier shape cleared _armed in each branch that could
    # return, which is correct for the branches it lists and silently wrong for
    # anything raised outside them: the flag stays raised, is_cycling() answers
    # "yes" forever, and every guarded skin reload in the session is deferred
    # for a cycle that already ended. Bounded waits kept that from being fatal;
    # it still meant no reload ever ran again.
    global _cycling, _armed
    try:
        _run_cycle()
    finally:
        _cycling = False
        _armed = False


def _run_cycle():
    global _cycling
    if not _wait_until_idle():
        _log('aborted before cycle', level='WARNING')
        return
    try:
        if xbmc.getCondVisibility('Player.HasMedia'):
            _log('media playing; skipping POV cycle (applies next launch)',
                 level='INFO')
            return
    except Exception:
        pass
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
