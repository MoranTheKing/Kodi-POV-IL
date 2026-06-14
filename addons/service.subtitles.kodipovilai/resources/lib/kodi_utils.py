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


def _read_kodi_setting_value(setting):
    """Read a Kodi *system* setting via JSON-RPC (Settings.GetSettingValue).
    Returns the raw value (str/list/...) or None on any failure."""
    if not KODI_AVAILABLE or xbmc is None:
        return None
    try:
        import json
        payload = {
            'jsonrpc': '2.0', 'id': 1,
            'method': 'Settings.GetSettingValue',
            'params': {'setting': setting},
        }
        resp = json.loads(xbmc.executeJSONRPC(json.dumps(payload)))
        return (resp.get('result') or {}).get('value')
    except Exception:
        return None


# Anything that names Hebrew, whether as an ISO code or a language name.
_HEBREW_LANG_TOKENS = ('he', 'heb', 'iw', 'hebrew', 'עברית')
# Kodi 'preferred subtitle language' tokens that do NOT name a concrete
# language. When the setting holds one of these we can't conclude the user
# prefers a non-Hebrew language, so we defer to the download-languages list.
_SUBTITLE_LANG_SPECIAL = ('', 'none', 'forced_only', 'forcedonly',
                          'default', 'original', 'mediadefault')


def _is_hebrew_lang(value):
    return (value or '').strip().lower() in _HEBREW_LANG_TOKENS


def hebrew_subtitle_wanted():
    """Decide whether the user actually wants Hebrew subtitles, so the AI
    translator knows when to stay out of the way.

    Returns ``False`` ONLY when we can positively determine the user prefers
    a specific NON-Hebrew subtitle language (e.g. they set Kodi's
    "preferred subtitle language" to English). In every ambiguous or
    unreadable case we return ``True`` -- preserving the long-standing
    AI-Hebrew default so we never silently disable translation for the
    Hebrew-default majority, and so a settings-read failure can't break
    anyone. This is purely an *extra* gate: it never enables translation
    that other settings (DarkSubs auto_translate / force_ai_when_auto_translate_off)
    have already turned off."""
    try:
        # 1. "Preferred subtitle language" (locale.subtitlelanguage) -- a
        #    single value. When it names a concrete language it is the
        #    clearest statement of intent, so it wins outright.
        pref = (_read_kodi_setting_value('locale.subtitlelanguage') or '')
        pref_norm = str(pref).strip().lower()
        if pref_norm and pref_norm not in _SUBTITLE_LANG_SPECIAL:
            return _is_hebrew_lang(pref_norm)

        # 2. Otherwise defer to "Languages to download subtitles for"
        #    (subtitles.languages) -- a list (or, on some builds, a CSV).
        dl = _read_kodi_setting_value('subtitles.languages')
        if isinstance(dl, str):
            dl = [p for p in dl.replace(';', ',').split(',') if p.strip()]
        if isinstance(dl, (list, tuple)) and dl:
            return any(_is_hebrew_lang(x) for x in dl)

        # 3. Nothing conclusive -> keep the AI-Hebrew default.
        return True
    except Exception:
        return True


def set_setting(key, value):
    """Set an addon setting. Returns True if the write persisted,
    False otherwise -- some Kodi/Android combinations silently
    swallow setSetting calls (the API returns ok but the value
    never reaches settings.xml on disk). Reading back is the only
    way to know whether the save actually took. Callers that don't
    care just ignore the return value -- backward compatible."""
    str_value = str(value)
    try:
        addon().setSetting(key, str_value)
    except Exception:
        return False
    try:
        return addon().getSetting(key) == str_value
    except Exception:
        return False


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
        # Force RTL paragraph direction. The previous version used
        # U+200F (RLM) as a prefix -- that's just a strong-RTL
        # invisible character that BIASES the BiDi algorithm but
        # doesn't OVERRIDE it. When a message like "AI: 25% תורגם
        # (5/20 chunks)" has more LTR weight than RTL, RLM loses
        # and Kodi renders the toast left-to-right -- which for a
        # Hebrew reader looks "reversed", reading from the end to
        # the beginning.
        #
        # U+202B (RIGHT-TO-LEFT EMBEDDING) + U+202C (POP DIRECTIONAL
        # FORMATTING) is the proper Unicode mechanism to FORCE a
        # paragraph's base direction to RTL while still letting
        # embedded Latin/digit runs read left-to-right within the
        # paragraph. We strip any pre-existing RLM/RLE the message
        # might already carry so we don't double-wrap.
        if msg:
            stripped = msg.lstrip('‏‪‫‬‭‮')
            stripped = stripped.rstrip('‬')
            msg = '‫' + stripped + '‬'
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

    # IMDB id: prefer the explicit UniqueId fetcher because some
    # plugins set that one without setting the legacy IMDBNumber.
    info['imdb_id']  = gi('VideoPlayer.UniqueId(imdb)') or \
                       gi('VideoPlayer.IMDBNumber')
    # TMDB id: POV / FENtastic streaming surfaces this via the
    # UniqueId mechanism even when imdb is empty. Wyzie accepts
    # either, so this is our main fallback for streams.
    info['tmdb_id']  = gi('VideoPlayer.UniqueId(tmdb)')
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
