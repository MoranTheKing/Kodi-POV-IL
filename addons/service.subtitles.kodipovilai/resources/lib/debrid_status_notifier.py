# -*- coding: utf-8 -*-
"""Build-only premium debrid subscription status toasts.

The thresholds are read from POV's existing "Premium Expires
Notification (days)" settings:

  rd.expires / tb.expires / pm.expires / ad.expires

`0` keeps the build's previous behaviour: show the status on every Kodi
startup. Any positive value shows only when the subscription has that
many days or fewer remaining (for example 3 = only in the last 3 days).
"""

import os
import sys

try:
    import xbmc
    import xbmcaddon
    import xbmcgui
    import xbmcvfs
except ImportError:
    xbmc = None
    xbmcaddon = None
    xbmcgui = None
    xbmcvfs = None

from resources.lib import kodi_utils


WINDOW_PROP = 'kodipovilai.debrid_status_shown'

SERVICES = (
    {
        'name': 'Real-Debrid',
        'title': 'Real-Debrid',
        'prefix': 'rd',
        'enabled': 'rd.enabled',
        'connected': ('rd.username', 'rd.token', 'rd.refresh'),
        'expires': 'rd.expires',
        'module': 'real_debrid_api',
        'class': 'RealDebridAPI',
        'icon': 'realdebrid.png',
    },
    {
        'name': 'TorBox',
        'title': 'TorBox',
        'prefix': 'tb',
        'enabled': 'tb.enabled',
        'connected': ('tb.account_id', 'tb.token'),
        'expires': 'tb.expires',
        'module': 'torbox_api',
        'class': 'TorBoxAPI',
        'icon': 'torbox.png',
    },
    {
        'name': 'Premiumize',
        'title': 'Premiumize',
        # Its refusals are {"status":"error","message":"..."} at HTTP 200 --
        # no error object, no code. See _refusal.
        'codeless': True,
        'prefix': 'pm',
        'enabled': 'pm.enabled',
        'connected': ('pm.account_id', 'pm.token'),
        'expires': 'pm.expires',
        'module': 'premiumize_api',
        'class': 'PremiumizeAPI',
        'icon': 'premiumize.png',
    },
    {
        'name': 'AllDebrid',
        'title': 'AllDebrid',
        'prefix': 'ad',
        'enabled': 'ad.enabled',
        'connected': ('ad.account_id', 'ad.token'),
        'expires': 'ad.expires',
        'module': 'alldebrid_api',
        'class': 'AllDebridAPI',
        'icon': 'alldebrid.png',
    },
)


def _pov_addon():
    if xbmcaddon is None:
        return None
    try:
        return xbmcaddon.Addon('plugin.video.pov')
    except Exception:
        return None


def _setting(addon, key, default=''):
    try:
        value = addon.getSetting(key)
        return value if value is not None else default
    except Exception:
        return default


def _pov_lib_path():
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/plugin.video.pov/resources/lib')
    except Exception:
        return ''


def _media_icon(filename):
    if xbmcvfs is None:
        return None
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/plugin.video.pov/resources/'
            'skins/Default/media/' + filename)
    except Exception:
        return None


def _days_remaining(service):
    lib_path = _pov_lib_path()
    if not lib_path or not os.path.isdir(lib_path):
        return None

    inserted = False
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)
        inserted = True
    try:
        module = __import__(
            'debrids.' + service['module'], fromlist=[service['class']])
        cls = getattr(module, service['class'])
        return cls().days_remaining()
    except Exception as exc:
        kodi_utils.log('{0} status lookup failed: {1}'.format(
            service['name'], exc), level='WARNING')
        return None
    finally:
        if inserted:
            try:
                sys.path.remove(lib_path)
            except ValueError:
                pass


# WHY A REFUSED ACCOUNT USED TO SHOW NOTHING AT ALL.
#
# A field report: every AllDebrid source failed to resolve. The log showed no
# reason, and three separate layers were why. POV's alldebrid_api._request
# logs only when the HTTP STATUS is bad -- and AllDebrid answers 200 with the
# error inside the body, the way its API has always worked. POV's
# days_remaining() wraps the lot in a bare `except: days = None`. And this
# file then read None as 'no number, so say nothing'. Three swallows in a row,
# and the one field that holds the answer never reached anyone.
#
# Verified against the live API, without the reporter's log or credentials:
#
#     GET v4/magnet/upload  ->  200  {"status":"error",
#                                     "error":{"code":"AUTH_...",
#                                              "message":"..."}}
#
# and v4/magnet/instant answers 404, so the endpoints are alive and it is not
# an API generation problem: AllDebrid is refusing THIS account, and naming
# which refusal in a field nobody read.
#
# NARROW ON PURPOSE. This speaks only for an unambiguous error envelope with
# one of the codes below -- reasons about the ACCOUNT, which a user can act
# on. A timeout, a dropped connection or an unrecognised shape says nothing,
# because a toast that cries wolf on a flaky night is worse than silence.
_REFUSAL_TEXT = {
    'AUTH_MISSING_APIKEY': 'החשבון לא מחובר',
    'AUTH_BAD_APIKEY': 'המפתח אינו תקף -- צריך לחבר מחדש',
    'AUTH_BLOCKED': 'הגישה חסומה',
    'AUTH_USER_BANNED': 'החשבון מושעה',
    'MUST_BE_PREMIUM': 'החשבון אינו פרימיום',
}


def _refusal(service):
    """(code, message) when the service refuses the account, else None.

    Costs one extra request, and only for a service that is connected and
    already failed to report its days -- so nobody who is fine pays for it.
    """
    lib_path = _pov_lib_path()
    if not lib_path or not os.path.isdir(lib_path):
        return None
    inserted = False
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)
        inserted = True
    try:
        module = __import__(
            'debrids.' + service['module'], fromlist=[service['class']])
        info = getattr(module, service['class'])().account_info()
        if not isinstance(info, dict) or info.get('status') != 'error':
            return None
        err = info.get('error') or {}
        if not isinstance(err, dict):
            # PREMIUMIZE PUTS THE REASON SOMEWHERE ELSE, and reading only
            # AllDebrid's shape meant a refused Premiumize account said
            # nothing at all -- on screen or in the log. Its envelope is
            # {"status":"error","message":"..."} at HTTP 200, with no `error`
            # object and no code, so this used to return None here and the
            # user was left with a search that found sources and then showed
            # an empty list.
            err = {}
        code = (err.get('code') or '').strip()
        message = (err.get('message') or info.get('message') or '').strip()
        if code:
            return (code, message)
        # A BARE MESSAGE COUNTS ONLY WHERE THE SERVICE HAS NO CODES, and that
        # is one service. AllDebrid always sends a code, so a coded envelope
        # arriving without one from AllDebrid is a shape nobody recognises and
        # is still nothing -- widening the rule for everyone would put an
        # arbitrary string on screen the first time a provider answered oddly.
        # Premiumize never sends a code at all; the narrow rule alone let it
        # refuse an account in perfect silence.
        if service.get('codeless') and message:
            return ('', message)
        return None
    except Exception:
        return None
    finally:
        if inserted:
            try:
                sys.path.remove(lib_path)
            except ValueError:
                pass


def _refusal_message(service, code, message):
    known = _REFUSAL_TEXT.get(code)
    detail = known or message or code
    return '[B]{0}: [COLOR red]{1}[/COLOR][/B]'.format(service['name'], detail)


def _threshold(addon, service):
    raw = _setting(addon, service['expires'], '0')
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 0
    # 0 = always show. This preserves the status-on-startup behaviour
    # users already saw, while positive values become "warn only when
    # days_remaining <= value".
    return max(0, value)


def _is_connected(addon, service):
    if _setting(addon, service['enabled'], 'true').lower() != 'true':
        return False
    return any(_setting(addon, key) for key in service['connected'])


def _should_show(days, threshold):
    if days is None:
        return False
    return threshold == 0 or days <= threshold


def _message(service, days):
    if days > 0:
        status = '[COLOR limegreen]פרימיום[/COLOR]'
        suffix = ' (נותרו {0} ימים)'.format(days)
    else:
        status = '[COLOR red]לא בתוקף[/COLOR]'
        suffix = ''
    return '[B]סטטוס מנוי {0}: {1}{2}[/B]'.format(
        service['name'], status, suffix)


def maybe_notify():
    if xbmc is None:
        return 'no_kodi'

    try:
        window = xbmcgui.Window(10000)
        if window.getProperty(WINDOW_PROP) == '1':
            return 'already_shown'
    except Exception:
        window = None

    addon = _pov_addon()
    if addon is None:
        return 'no_pov'

    queue = []
    for service in SERVICES:
        if not _is_connected(addon, service):
            continue
        days = _days_remaining(service)
        if days is None:
            # No number is not nothing to say. Ask once why.
            refused = _refusal(service)
            # A KNOWN CODE, or a service that has no codes and said something.
            # The first is the narrow rule this started with; the second exists
            # because Premiumize never sends a code, so the narrow rule alone
            # meant it could refuse an account in perfect silence.
            if refused and (refused[0] in _REFUSAL_TEXT
                            or (not refused[0] and refused[1])):
                queue.append((service, refused))
            continue
        threshold = _threshold(addon, service)
        if _should_show(days, threshold):
            queue.append((service, days))

    if not queue:
        return 'nothing_to_show'

    monitor = xbmc.Monitor()
    if monitor.waitForAbort(1.8):
        return 'aborted'

    shown = 0
    for idx, (service, days) in enumerate(queue):
        if idx and monitor.waitForAbort(4.8):
            return 'aborted'
        text = (_refusal_message(service, days[0], days[1])
                if isinstance(days, tuple) else _message(service, days))
        kodi_utils.notify(
            text,
            title=service['title'],
            icon=_media_icon(service['icon']),
            time_ms=4500)
        shown += 1

    if window is not None:
        try:
            window.setProperty(WINDOW_PROP, '1')
        except Exception:
            pass
    return 'shown:{0}'.format(shown)
