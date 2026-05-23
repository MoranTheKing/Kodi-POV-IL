# Thin shims over Kodi's xbmc* APIs. Keeps the rest of the addon
# testable in isolation -- everything that touches Kodi goes through
# here.

import os
import sys

try:
    import xbmc
    import xbmcaddon
    import xbmcvfs
    import xbmcgui
    KODI_AVAILABLE = True
except ImportError:
    # Allows unit tests / standalone scripts to import the module
    # without a Kodi runtime.
    KODI_AVAILABLE = False
    xbmc = None
    xbmcaddon = None
    xbmcvfs = None
    xbmcgui = None

ADDON_ID = 'service.subtitles.kodipovilai'


def addon():
    return xbmcaddon.Addon(ADDON_ID)


def get_setting(key, default=''):
    try:
        v = addon().getSetting(key)
        return v if v is not None else default
    except Exception:
        return default


def get_bool(key, default=False):
    v = get_setting(key, '')
    if v == '':
        return default
    return v.lower() == 'true'


def get_int(key, default=0):
    v = get_setting(key, '')
    try:
        return int(v) if v != '' else default
    except (ValueError, TypeError):
        return default


def get_float(key, default=0.0):
    v = get_setting(key, '')
    try:
        return float(v) if v != '' else default
    except (ValueError, TypeError):
        return default


def set_setting(key, value):
    try:
        addon().setSetting(key, str(value))
    except Exception:
        pass


def localised(strid, *args):
    try:
        s = addon().getLocalizedString(strid)
    except Exception:
        s = ''
    if not s:
        return ''
    if args:
        try:
            return s.format(*args)
        except (IndexError, KeyError):
            return s
    return s


def addon_profile_path():
    """Path to the addon's per-user data dir
    (.kodi/userdata/addon_data/<id>/). Created if missing."""
    if not KODI_AVAILABLE:
        return os.path.join(os.path.expanduser('~'), '.kodi-test', ADDON_ID)
    p = xbmcvfs.translatePath('special://profile/addon_data/' + ADDON_ID + '/')
    if not os.path.isdir(p):
        try:
            os.makedirs(p)
        except OSError:
            pass
    return p


def cache_dir():
    p = os.path.join(addon_profile_path(), 'cache')
    if not os.path.isdir(p):
        try:
            os.makedirs(p)
        except OSError:
            pass
    return p


def log(msg, level='INFO'):
    """Log to Kodi's log at the appropriate level. Honours the
    addon's log_level setting -- anything below that is suppressed."""
    cfg_level = get_setting('log_level', 'INFO').upper()
    order = {'DEBUG': 0, 'INFO': 1, 'WARNING': 2, 'ERROR': 3}
    if order.get(level.upper(), 1) < order.get(cfg_level, 1):
        return
    if not KODI_AVAILABLE:
        print('[{0}] {1}'.format(level, msg))
        return
    kodi_level = {
        'DEBUG': xbmc.LOGDEBUG,
        'INFO': xbmc.LOGINFO,
        'WARNING': xbmc.LOGWARNING,
        'ERROR': xbmc.LOGERROR,
    }.get(level.upper(), xbmc.LOGINFO)
    try:
        xbmc.log('[{0}] {1}'.format(ADDON_ID, msg), level=kodi_level)
    except Exception:
        pass


def notify(msg, title=None, icon=None, time_ms=4000):
    if not KODI_AVAILABLE:
        print('NOTIFY:', title, '-', msg)
        return
    try:
        if title is None:
            title = 'Kodi POV IL'
        if icon is None:
            icon = xbmcvfs.translatePath('special://home/addons/' + ADDON_ID + '/icon.png')
        xbmcgui.Dialog().notification(title, msg, icon, time_ms)
    except Exception:
        pass


def current_video_info():
    """Best-effort snapshot of what Kodi is currently playing.
    Returns a dict with imdb_id, tmdb_id, title, year, season,
    episode, language, filepath -- any field may be empty.

    Kodi's behaviour at subtitle-search time differs across
    library / non-library / direct-play scenarios; we read every
    InfoLabel we plausibly need and let callers pick the bits they
    have."""
    info = {
        'imdb_id': '', 'tmdb_id': '', 'title': '', 'year': '',
        'season': '', 'episode': '', 'language': '', 'filepath': '',
        'tvshow': '', 'is_episode': False,
    }
    if not KODI_AVAILABLE:
        return info

    def gi(name):
        try:
            return xbmc.getInfoLabel(name) or ''
        except Exception:
            return ''

    info['imdb_id']  = gi('VideoPlayer.IMDBNumber')
    info['title']    = gi('VideoPlayer.Title') or gi('VideoPlayer.OriginalTitle')
    info['year']     = gi('VideoPlayer.Year')
    info['season']   = gi('VideoPlayer.Season')
    info['episode']  = gi('VideoPlayer.Episode')
    info['tvshow']   = gi('VideoPlayer.TVshowtitle')
    info['filepath'] = gi('Player.Filenameandpath')
    info['is_episode'] = bool(info['tvshow'] and info['episode'])
    return info


def progress_dialog():
    """Return a DialogProgressBG or None if not available."""
    if not KODI_AVAILABLE:
        return None
    try:
        return xbmcgui.DialogProgressBG()
    except Exception:
        return None
