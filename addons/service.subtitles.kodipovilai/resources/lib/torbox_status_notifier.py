# -*- coding: utf-8 -*-
"""Build-only TorBox subscription status toast.

POV already has a generic debrid-expiry service, but the build ships
Real-Debrid with an always-visible startup status while TorBox only has
a manual home tile. This adds the missing TorBox startup toast without
touching POV lists, Trakt/TMDb data, or standalone AI-subtitle installs.
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


WINDOW_PROP = 'kodipovilai.torbox_status_shown'


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


def _days_remaining():
    lib_path = _pov_lib_path()
    if not lib_path or not os.path.isdir(lib_path):
        return None

    inserted = False
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)
        inserted = True
    try:
        from debrids.torbox_api import TorBoxAPI
        return TorBoxAPI().days_remaining()
    except Exception as exc:
        kodi_utils.log('TorBox status lookup failed: {0}'.format(exc),
                       level='WARNING')
        return None
    finally:
        if inserted:
            try:
                sys.path.remove(lib_path)
            except ValueError:
                pass


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

    enabled = _setting(addon, 'tb.enabled', 'false').lower() == 'true'
    connected = bool(_setting(addon, 'tb.account_id') or
                     _setting(addon, 'tb.token'))
    if not enabled or not connected:
        return 'not_connected'

    # If RD is connected too, let POV's existing RD startup toast go first.
    rd_connected = bool(_setting(addon, 'rd.username') or
                        _setting(addon, 'rd.token') or
                        _setting(addon, 'rd.refresh'))
    delay_ms = 5200 if rd_connected else 1800
    monitor = xbmc.Monitor()
    if monitor.waitForAbort(delay_ms / 1000.0):
        return 'aborted'

    days = _days_remaining()
    if days is None:
        return 'no_days'

    if window is not None:
        try:
            window.setProperty(WINDOW_PROP, '1')
        except Exception:
            pass

    if days > 0:
        status = '[COLOR limegreen]פרימיום[/COLOR]'
        suffix = ' (נותרו {0} ימים)'.format(days)
    else:
        status = '[COLOR red]לא בתוקף[/COLOR]'
        suffix = ''
    kodi_utils.notify('[B]סטטוס מנוי TorBox: {0}{1}[/B]'
                      .format(status, suffix),
                      title='Kodi POV IL',
                      time_ms=4500)
    return 'shown'
