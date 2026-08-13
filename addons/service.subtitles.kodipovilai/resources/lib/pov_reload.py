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
# The one disk-probe thread. Not a cached answer -- a handle, so a probe that
# never returns is never started twice. See _probe_path.
_probe_thread = None
try:
    import threading as _threading
    _probe_lock = _threading.Lock()
except Exception:                       # no threads here at all
    class _NoLock(object):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    _probe_lock = _NoLock()
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


# Written before POV is disabled, removed once it is verified back on. The
# wizard keeps the same kind of record for the add-ons IT cycles
# (pending_enable.txt) and for the same reason: a cycle that dies between the
# disable and the enable leaves POV off, and a disabled add-on cannot switch
# itself back on.
#
# SEPARATE FILE, NOT THE WIZARD'S. Two processes doing read-modify-write on one
# list can drop an entry, and the entry that would get dropped is the one
# saying "POV is off and somebody has to fix it". One writer per file removes
# that whole class of problem; the healer simply reads both.
CYCLE_PENDING_FILE = ('special://profile/addon_data/'
                      'service.subtitles.kodipovilai/pov_cycle_pending.txt')


def _cycle_pending_path():
    import xbmcvfs
    return xbmcvfs.translatePath(CYCLE_PENDING_FILE)


def _mark_cycle_pending(pending):
    """Record -- or clear -- "we have POV switched off right now"."""
    try:
        import os
        path = _cycle_pending_path()
        if pending:
            directory = os.path.dirname(path)
            if directory and not os.path.isdir(directory):
                os.makedirs(directory)
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(POV_ADDON_ID + '\n')
        elif os.path.exists(path):
            os.remove(path)
        return True
    except Exception as e:
        _log('could not {0} the cycle record: {1}'.format(
            'write' if pending else 'clear', e), level='WARNING')
        return False


def _forget_record_if_pov_works():
    """A record only means anything while POV is actually broken.

    Without this it never expires. A cycle that overran its own budget by a
    second left the record behind, POV came back unnoticed, and days later --
    after the user had switched POV off themselves -- the startup heal read
    that ancient record as authority and switched it back on. Which is the
    silent settings change this whole mechanism exists to stop, reached through
    staleness instead of through a guess.

    So: any time we can see POV working, the record is obsolete by definition.
    Drop it there and then, and the only records that survive are the ones
    describing an outage that is still real.
    """
    try:
        import os
        if not os.path.exists(_cycle_pending_path()):
            return
    except Exception:
        return
    if not _is_resolvable():
        return
    # TWICE, WITH A GAP. _run_cycle writes the record and disables POV on the
    # next line, and in between POV is still constructible. A DIFFERENT Kodi
    # interpreter -- the wizard's, which shares none of this module's flags --
    # asking is_cycling() at that instant reads "working" correctly and would
    # delete the record a moment before it becomes the only thing that brings
    # POV back. The gap is microseconds wide, so a second look after a pause
    # lands the far side of the disable and sees the outage.
    try:
        import time
        time.sleep(0.3)
    except Exception:
        return
    if _is_resolvable():
        _mark_cycle_pending(False)


def cycle_left_pov_off():
    """True when a cycle of ours switched POV off and never switched it back.

    Read by the startup heal. It is the whole difference between "our cycle was
    interrupted, put POV back" and "the user switched POV off", which look
    identical from outside and deserve opposite answers.
    """
    try:
        import os
        return os.path.exists(_cycle_pending_path())
    except Exception:
        return False


def clear_cycle_record():
    _mark_cycle_pending(False)


def _is_installed(budget=None):
    """Does POV exist on disk at all?

    `budget` is the caller's remaining seconds, if it has one. Without it the
    probe uses its own 3s ceiling, which is fine for a one-off question and
    wrong inside a timed loop: a caller that asked for two seconds got three,
    because the probe's ceiling did not know about the caller's. Overshoot was
    measured at 201% for a 1s request. The bound a caller passes is the bound
    it gets; this is how that stays true when the disk is slow.

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
    # ASKED EVERY TIME, NOT CACHED. A one-directional memo ("once seen on disk,
    # always installed") was tried and removed: it bought only the cost of a
    # stat, and it made the answer wrong for the rest of the session for
    # anyone who removed POV while Kodi was running -- the guard stayed armed
    # against an add-on that no longer existed. The reason the memo looked
    # necessary was a hung probe being paid repeatedly inside the polling loop,
    # and that is fixed where it belongs, by charging the probe's real time
    # against the caller's budget.
    try:
        import xbmcvfs
    except Exception:
        return True
    cap = 3.0 if budget is None else max(0.0, min(3.0, budget))
    for root in ('special://home/addons/', 'special://xbmc/addons/'):
        path = root + POV_ADDON_ID + '/addon.xml'
        # translate-then-exists, the same order the rest of this add-on uses
        # (af3_home_patcher._exists), so one convention covers all of it.
        ok = _probe_path(lambda: xbmcvfs.exists(xbmcvfs.translatePath(path)),
                         timeout=cap)
        if ok is None:
            # No answer -- either it raised or it did not come back. Where
            # _exists reads that as "no file", this reads it as "no idea", and
            # the safe reading of no idea is to keep guarding.
            return True
        if ok:
            return True
    return False


def _probe_path(fn, timeout=3.0):
    """Run a filesystem check that is not allowed to hang. None = no answer.

    `except Exception` covers a call that FAILS. It does nothing for a call
    that never returns, and stat() against a dead NFS or SMB mount is exactly
    that -- a Kodi freeze class in its own right, and reachable here because a
    user can point special://home at a share to run several boxes off one
    config. This function is called from inside wait_until_settled's polling
    loop, whose entire contract is a hard bound on how long the service is
    allowed not to start, so a hang here would quietly void that bound.

    ONE PROBE THREAD, EVER. join() bounds how long the CALLER waits; it cannot
    cancel a thread stuck in a C-level syscall, and nothing in Python can. The
    first version started a fresh one per attempt, so against a mount that
    never answers, a single wait leaked three permanently-blocked threads and
    the count climbed for the rest of the session -- in the module written to
    stop Kodi becoming unstable. If the last probe never came back, the disk is
    still not answering: say so from the thread we already have, and start no
    more. Two callers racing here can each start one before either records it,
    so the true bound is "one per concurrent guard site", not one full stop --
    a handful, once, instead of a count that climbs all session. Not worth a
    lock for a value whose only wrong answer is "probe again in a moment".
    """
    global _probe_thread
    box = {}

    def run():
        try:
            box['v'] = bool(fn())
        except Exception:
            box['v'] = None

    try:
        import threading
        # LOCKED, because "read the handle, then set it" is two steps with
        # thread construction in between. Two callers could both find nothing
        # in flight, both start one, and the faster one's handle land LAST --
        # leaving the slow one running untracked, so the next caller starts
        # yet another against the same dead mount. Measured at about one
        # racing pair in twenty-five, which is not rare on a box where the
        # tile-reload worker and a settings click overlap.
        with _probe_lock:
            if _probe_thread is not None and _probe_thread.is_alive():
                return None
            t = threading.Thread(target=run)
            t.daemon = True  # a stuck stat must not keep Kodi's process alive
            _probe_thread = t
            t.start()
        # Joined OUTSIDE the lock: a probe that never returns must not also
        # block everyone else at the door. They look, see it alive, and get
        # their "no answer" immediately.
        t.join(timeout)
    except Exception:
        return None
    return box.get('v')


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
        # Seen working -> any leftover cycle record is stale. Cleared here
        # because this is the one function every guard calls, so the record
        # cannot outlive the outage it describes by more than a moment.
        _forget_record_if_pov_works()
        return False
    return _is_installed()


def wait_until_settled(timeout=30, alien_timeout=None):
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

    THESE NUMBERS ARE A MAIN-THREAD BUDGET, NOT A PATIENCE SETTING. Three of
    the four call sites are steps in _run_build_startup_repairs(), which the
    service runs INLINE on its main thread in build mode, and they do not share
    a budget -- two of them firing in one pass costs the sum. So this is not
    "how late the reload is", it is how long the subtitle service does not
    start, doubled. Measured with both gated on the same skin: 60.9s at a flat
    30s each.

    Hence a cycle WE know about is waited out generously (timeout: it is a real
    outage, it ends, and reloading afterwards is the whole point), while POV
    that is merely unusable and nobody here started (switched off by hand, a
    broken install, another process mid-cycle) gets alien_timeout -- long
    enough for the wizard's cross-process cycle, which is a second and a half
    of downtime plus the construction lag, and short enough that the case that
    NEVER clears costs 10s a site instead of 30. That last one is not
    hypothetical and not one-off: a user who leaves POV switched off pays it on
    every boot where a guarded site has work to do.

    NEITHER BOUND EVER REPORTS SAFE. Running out of patience is not evidence
    that POV came back, and saying so is how the guard would fail open. Every
    caller treats False as "not now": it logs, leaves its work undone and
    unstamped, and the next service run tries again.
    """
    if xbmc is None:
        return True
    # A CLOCK, NOT A COUNT OF SLEEPS. Adding 0.5 per iteration only measures
    # the waiting; it charges nothing for the WORK in each iteration, and the
    # work here includes a disk probe that is allowed to take seconds when a
    # mount is dead. Counted that way, a 10s budget took a minute of real time
    # to run out -- the bound was being kept in units nobody experiences.
    # Monotonic, so a clock adjustment mid-wait cannot extend or void it.
    import time
    # The alien budget is a CAP on the caller's number, never an override of
    # it. Someone who asks for two seconds means two seconds; letting an
    # unrequested ten win would make the argument advisory, which is how the
    # last dead-default finding happened.
    alien = min(timeout, 10) if alien_timeout is None else alien_timeout
    started = time.monotonic()
    ours_before = None
    while True:
        ours = bool(_armed or _cycling)
        if not ours:
            if _is_resolvable():
                return True
            # Hand the probe what is LEFT of this call's budget, so a slow disk
            # cannot push the answer past the bound the caller asked for.
            left = (timeout if ours else alien) - (time.monotonic() - started)
            if not _is_installed(budget=left):
                # Kodi has no such add-on. Nothing to wait for, now or ever.
                return True
        if ours_before is not None and ours != ours_before:
            # The question changed, so the budget does. A caller that spent
            # nine seconds on somebody else's outage and then finds OUR cycle
            # starting should get the cycle's budget, not one second of it.
            # Only on a CHANGE, though: resetting on the first pass too would
            # throw away whatever that pass already spent, and what it spends
            # is the disk probe -- the single most expensive thing in here.
            started = time.monotonic()
        ours_before = ours
        waited = time.monotonic() - started
        if waited >= (timeout if ours else alien):
            _log('POV unresolvable after {0:.0f}s ({1}); telling the caller to '
                 'defer to its next run'.format(
                     waited, 'our cycle' if ours else 'not ours'),
                 level='WARNING')
            return False
        try:
            if xbmc.Monitor().waitForAbort(0.5):
                return False
        except Exception:
            return False


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
        # RECORDED BEFORE THE DISABLE, exactly like the wizard's _cycle_addon,
        # so that a process killed in the next second and a half leaves
        # evidence that POV is off because of us. Without it the startup heal
        # cannot tell our interrupted cycle from a user who switched POV off,
        # and it used to guess -- always healing, which quietly reversed a
        # setting the user had chosen.
        # NO RECORD, NO DISABLE -- the wizard's _cycle_addon says this in as
        # many words and refuses for the same reason. The record is the ONLY
        # thing that brings POV back if this process dies in the next second
        # and a half; disabling without it risks POV stuck off forever with
        # nothing pointing at why. Skipping costs a stale interpreter until the
        # next restart, which is just the old behaviour.
        if not _mark_cycle_pending(True):
            _log('could not record the cycle; not disabling POV',
                 level='WARNING')
            return
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
        if ok:
            # CLEARED ONLY ON PROOF. The record is what tells the next start to
            # switch POV back on, so it comes off the disk only once POV has
            # actually been constructed -- not when the enable call returned,
            # which it does whether or not the enable took.
            _mark_cycle_pending(False)
        else:
            _set_enabled(True)
            _log('POV did not come back; the cycle record stays so the next '
                 'start switches it on', level='WARNING')
        _restore_home_focus(saved_focus)
    except Exception as e:
        _log('cycle failed: {0}'.format(e), level='WARNING')
        try:
            _set_enabled(True)
            if _is_resolvable():
                _mark_cycle_pending(False)
        except Exception:
            pass
