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


def maybe_ask():
    """Returns 'asked_yes' | 'asked_no' | 'already_asked' | 'no_mismatch'
    | 'unavailable'. Never raises."""
    if ws is None or addon_settings_safe is None or xbmcgui is None:
        return 'unavailable'
    if _asked():
        return 'already_asked'

    umbrella = _reader(UMBRELLA_ADDON_ID)
    # Connected to something? A service with no token has nothing to read
    # from, so the settings being on Local is not a fault worth a dialog.
    if not (umbrella('mdblist.token') or umbrella('trakt.user.token')):
        return 'no_mismatch'

    done = ws._done()
    wanted = []
    for key in ws.KEYS:
        prev = done.get(key)
        if not prev or prev == ws.NOTHING:
            continue                     # never ours -> never our business
        if umbrella(key) == ws.SHIPPED_LOCAL:
            wanted.append((key, prev))
    if not wanted:
        return 'no_mismatch'

    try:
        yes = xbmcgui.Dialog().yesno(TITLE, BODY, nolabel=NO, yeslabel=YES)
    except Exception:
        return 'unavailable'             # no marker written: ask another day
    if not yes:
        _remember('no')
        _log('offered to restore watched state; user kept Local')
        return 'asked_no'

    _changed, _restored, failed = addon_settings_safe.apply(
        UMBRELLA_ADDON_ID, tuple(wanted),
        guard_property=UMBRELLA_GUARD_PROPERTY)
    # The marker is written whatever the write did. The user has answered,
    # and asking again because a write failed would punish them for our
    # problem; the timer re-mirrors anyway.
    _remember('yes')
    if failed:
        _log('user said yes but the write did not stick ({0})'
             .format(', '.join(failed)), level='WARNING')
    else:
        _log('watched state restored from the connected service at the '
             'user\'s request')
    return 'asked_yes'
