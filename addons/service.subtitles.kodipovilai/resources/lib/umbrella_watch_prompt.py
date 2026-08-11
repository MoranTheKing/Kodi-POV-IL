# Ask, once, when Umbrella has a service connected but is not reading from it.
#
# The safety net under umbrella_watch_source's claim. That claim is taken once
# per setting and only while the setting still reads the shipped Local, which
# is right -- but it leaves one state with no way out: our claim recorded, and
# the setting back at Local anyway. Something reset it, and after that Umbrella
# has the lists and none of the watched state, forever, with nothing in the
# build able to tell whether the user chose Local or something took it.
#
# Three attempts were made to answer that question by inference, from a
# reconnect signal, and every one of them fired without a human doing anything
# and silently reverted somebody's choice. The measured signal in
# pov_services_patcher covers the case where the user does go and reconnect.
# This covers the rest, and it does it by ASKING rather than deciding -- which
# is the honest response to a question that cannot be answered from the state.
#
# Once per device. Answered no, or dismissed, and it never comes back: a
# question asked twice is a question that overrules the answer.

import threading

try:
    import xbmc
except Exception:
    xbmc = None

try:
    import xbmcgui
except Exception:
    xbmcgui = None

try:
    import xbmcaddon
except Exception:
    xbmcaddon = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None

try:
    from resources.lib import addon_settings_safe
except Exception:
    addon_settings_safe = None

try:
    from resources.lib import umbrella_watch_source as ws
except Exception:
    ws = None


UMBRELLA_ADDON_ID = 'plugin.video.umbrella'
UMBRELLA_GUARD_PROPERTY = 'umbrella.updateSettings'
MARKER_SETTING = '_umb_watch_prompt_v1'

# One asker at a time. `_asked()` only turns true once the answer is written,
# and the answer is not written until the dialog has been dismissed -- so a
# keeper tick landing while the dialog stands would pass the same test and open
# a second one. On a box nobody is sitting in front of, that is a fresh dialog
# every minute, against this file's own promise that it asks once.
_IN_FLIGHT = threading.Lock()

TITLE = 'Kodi POV IL'
BODY = ('אמברלה מחוברת אבל לא מציגה סימוני צפייה והתקדמות.\n'
        'להפעיל אותם מהשירות שחיברת?')
YES = 'הפעל'
NO = 'לא, השאר מקומי'


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('umbrella_watch_prompt: ' + msg, level=level)
    except Exception:
        pass


def _asked():
    try:
        return bool((kodi_utils.get_setting(MARKER_SETTING, '') or '').strip())
    except Exception:
        return True          # cannot tell -> do not pester


def _remember(answer):
    try:
        kodi_utils.set_setting(MARKER_SETTING, answer)
    except Exception:
        pass


def _reader(addon_id):
    if xbmcaddon is None:
        return lambda _k: None
    try:
        addon = xbmcaddon.Addon(addon_id)
    except Exception:
        return lambda _k: None

    def _get(key):
        try:
            return (addon.getSetting(key) or '').strip()
        except Exception:
            return None
    return _get


def _restorable(umbrella):
    """[(key, source)] that could be put back RIGHT NOW, or [].

    A service with no token has nothing to read from, so a setting on Local is
    not a fault worth a dialog. And restoring the marker's value BLIND was a
    blocker: connect Trakt through POV, connect MDBList inside Umbrella itself
    -- a route this build never touches, so POV's token stays empty and the
    mirror never runs for it -- then revoke Trakt in Umbrella, which DOES
    reset these two settings where MDBList's revoke does not. The marker still
    said Trakt, so a user answering yes had their indicators pointed at a
    revoked account while the live one sat unused. So the recorded service is
    used only while it still holds a token, and otherwise the live one,
    preferring MDBList exactly as the mirrors do. pairs() never needs this: it
    only ever writes its own live source. Only this module restores a
    historical value, so only this module has to check it.

    Called TWICE on purpose -- once to decide whether to ask, and again after
    the dialog, because the dialog has no timeout and the answer can arrive
    long after the question."""
    if ws is None:
        return []
    live = set()
    if umbrella('mdblist.token'):
        live.add(ws.MDBLIST)
    if umbrella('trakt.user.token'):
        live.add(ws.TRAKT)
    if not live:
        return []
    fallback = ws.MDBLIST if ws.MDBLIST in live else ws.TRAKT
    done = ws._done()
    wanted = []
    for key in ws.KEYS:
        prev = done.get(key)
        if not prev or prev == ws.NOTHING:
            continue                     # never ours -> never our business
        if umbrella(key) != ws.SHIPPED_LOCAL:
            continue
        wanted.append((key, prev if prev in live else fallback))
    return wanted


def maybe_ask():
    """Returns 'asked_yes' | 'asked_no' | 'already_asked' | 'no_mismatch'
    | 'busy' | 'in_flight' | 'unavailable'. Never raises."""
    if ws is None or addon_settings_safe is None or xbmcgui is None:
        return 'unavailable'
    if not _IN_FLIGHT.acquire(False):
        return 'in_flight'
    try:
        return _ask()
    except Exception as e:
        _log('failed: {0}'.format(e), level='WARNING')
        return 'unavailable'
    finally:
        _IN_FLIGHT.release()


def _ask():
    if _asked():
        return 'already_asked'
    # Not over a film. There is no hurry -- the question keeps until the next
    # tick, and a modal dialog across somebody's playback is worse than
    # waiting.
    try:
        if xbmc is not None and xbmc.Player().isPlayingVideo():
            return 'busy'
    except Exception:
        pass

    if not _restorable(_reader(UMBRELLA_ADDON_ID)):
        return 'no_mismatch'

    try:
        yes = xbmcgui.Dialog().yesno(TITLE, BODY, nolabel=NO, yeslabel=YES)
    except Exception:
        return 'unavailable'             # no marker written: ask another day
    if not yes:
        _remember('no')
        _log('offered to restore watched state; user kept Local')
        return 'asked_no'

    # Work it out AGAIN, now. Everything above was decided before a dialog
    # with no timeout, so by the time somebody presses yes the service they
    # are agreeing to may have been revoked -- and writing it then is the very
    # thing the liveness check exists to stop. The answer still counts: they
    # have been asked, and asking again would be asking twice.
    wanted = _restorable(_reader(UMBRELLA_ADDON_ID))
    if not wanted:
        _remember('yes')
        _log('user agreed, but there was nothing left to restore by then')
        return 'asked_yes'

    _changed, _restored, failed = addon_settings_safe.apply(
        UMBRELLA_ADDON_ID, tuple(wanted),
        guard_property=UMBRELLA_GUARD_PROPERTY)
    # The marker is written whatever the write did. The user has answered,
    # and asking again because a write failed would punish them for our
    # problem; the timer re-mirrors anyway.
    _remember('yes')
    # Keep the marker describing what is actually there. Where the stale
    # service was swapped for the live one, the record has to follow or the
    # mirrors' "is this still ours?" test is answered against a value nobody
    # wrote. settle() merges and never demotes, so this is additive.
    try:
        ws.settle(dict((k, v) for k, v in wanted if k not in failed))
    except Exception:
        pass
    if failed:
        _log('user said yes but the write did not stick ({0})'
             .format(', '.join(failed)), level='WARNING')
    else:
        _log('watched state restored from the connected service at the '
             'user\'s request')
    return 'asked_yes'


def maybe_ask_async():
    """Ask on a thread of its own.

    Dialog().yesno() blocks until it is answered, and Kodi gives it no
    timeout. Called inline from the keeper loop it would stop the MDBList and
    Trakt mirrors and the seasons-view seeder for as long as the dialog stood
    -- possibly forever, on a box nobody is sitting at -- which is precisely
    the per-minute guarantee that loop exists to provide. The lock inside
    maybe_ask() is what stops the loop stacking one thread per tick behind an
    unanswered dialog; daemon=True is what stops any of them holding up
    shutdown."""
    try:
        threading.Thread(target=maybe_ask, daemon=True).start()
    except Exception:
        pass
