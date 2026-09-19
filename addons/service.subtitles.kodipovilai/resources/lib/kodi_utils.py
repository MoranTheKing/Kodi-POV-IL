# Thin shims over Kodi's xbmc* APIs. Keeps the rest of the addon
# testable in isolation -- everything that touches Kodi goes through
# here.

import os
import sys
import threading
import hashlib
import json
import time
import urllib.parse

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
_ADDON = None

# notify() fires each GUI toast on a short-lived daemon thread so a wedged GUI
# can never stall the caller (see notify()). This bounds how many such threads
# may be parked at once: under a *sustained* GUI wedge (and with
# reuselanguageinvoker keeping this module warm across invocations) toast
# threads that block inside Kodi's notification() don't get reaped until the
# wedge clears, so without a cap they could accumulate over a session. Past the
# cap we simply drop the toast -- notifications are decorative and nothing
# depends on one landing.
_NOTIFY_MAX_PENDING = 8
_notify_lock = threading.Lock()
_notify_pending = [0]
_EMBEDDED_MODE_VALUES = (
    'auto', 'align_only', 'direct', 'local_only', 'off')
_embedded_mode_lock = threading.Lock()


def addon():
    # Cache the Addon() instance. Constructing xbmcaddon.Addon() re-parses and
    # re-validates the addon's ENTIRE settings.xml against Kodi's settings
    # schema every single time (visible in the Kodi log as a burst of
    # "error reading <control>/<dependency> tag" warnings) -- with 100+
    # settings and a few schema quirks, that's real, repeated work. This
    # module has 100+ call sites (get_setting/set_setting/get_bool/...), and
    # a periodic background loop calls into one of them roughly once a
    # minute for the life of the Kodi session, so a fresh Addon() per call
    # meant a full settings.xml reparse every single time, indefinitely.
    # The Addon() handle itself doesn't go stale -- getSetting/setSetting
    # always read/write the live store -- so one cached instance is safe to
    # reuse for the life of the process, across threads.
    global _ADDON
    if _ADDON is None:
        _ADDON = xbmcaddon.Addon(ADDON_ID)
    return _ADDON


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
        # 1. "Languages to download subtitles for" (subtitles.languages).
        #    Hebrew HERE is the strongest positive signal there is -- it is
        #    exactly the list Kodi's subtitle search uses -- so it wins even
        #    when the PLAYBACK preference (locale.subtitlelanguage) names
        #    another language. Field case: a standalone user on a foreign
        #    build had locale.subtitlelanguage=English, and the old
        #    precedence silently disabled the entire addon ("offers no AI
        #    entries") even though Hebrew was in their download list.
        dl = _read_kodi_setting_value('subtitles.languages')
        if isinstance(dl, str):
            dl = [p for p in dl.replace(';', ',').split(',') if p.strip()]
        dl_has_hebrew = (isinstance(dl, (list, tuple)) and dl
                         and any(_is_hebrew_lang(x) for x in dl))
        if dl_has_hebrew:
            return True

        # 2. "Preferred subtitle language" (locale.subtitlelanguage) -- a
        #    single value naming a concrete language.
        pref = (_read_kodi_setting_value('locale.subtitlelanguage') or '')
        pref_norm = str(pref).strip().lower()
        if pref_norm and pref_norm not in _SUBTITLE_LANG_SPECIAL:
            return _is_hebrew_lang(pref_norm)

        # 3. Download list readable, non-empty and Hebrew-less (and no
        #    concrete playback preference) -> the user asked for other
        #    languages only.
        if isinstance(dl, (list, tuple)) and dl:
            return False

        # 4. Nothing conclusive -> keep the AI-Hebrew default.
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


def embedded_translation_mode():
    """Return and maintain the canonical embedded-subtitle strategy.

    Version 0.2.441 replaces two hidden booleans with one explained mode list.
    On the first run, preserve the exact legacy on/off + HTTP boundary:
    disabled -> ``off``; enabled but HTTP-disabled -> ``local_only``; otherwise
    ``auto``.  Once migrated, the new selector is canonical and its closest
    legacy representation is mirrored back for downgrade compatibility.
    """
    with _embedded_mode_lock:
        marker = get_setting('_embedded_mode_v1', '') == '1'
        raw = (get_setting('embedded_translation_mode', '') or '').strip().lower()

        if not marker:
            # A non-default mode can only have been explicitly selected in the
            # new UI before the service migration ran, so honour it.
            if raw in _EMBEDDED_MODE_VALUES and raw != 'auto':
                mode = raw
            elif not get_bool('embedded_translate', True):
                mode = 'off'
            elif not get_bool('embedded_http_extract', True):
                mode = 'local_only'
            else:
                mode = 'auto'
        else:
            if raw in _EMBEDDED_MODE_VALUES:
                mode = raw
            elif not get_bool('embedded_translate', True):
                mode = 'off'
            elif not get_bool('embedded_http_extract', True):
                mode = 'local_only'
            else:
                mode = 'auto'

        enabled = mode != 'off'
        allow_http = mode not in ('off', 'local_only')
        writes_ok = True
        if raw != mode:
            writes_ok = set_setting('embedded_translation_mode', mode) and writes_ok
        if get_bool('embedded_translate', True) != enabled:
            writes_ok = set_setting(
                'embedded_translate', 'true' if enabled else 'false') and writes_ok
        if get_bool('embedded_http_extract', True) != allow_http:
            writes_ok = set_setting(
                'embedded_http_extract',
                'true' if allow_http else 'false') and writes_ok
        if not marker and writes_ok:
            set_setting('_embedded_mode_v1', '1')
        return mode


def embedded_translation_policy(mode=None):
    """Map one mode to the exact runtime paths it permits."""
    if mode not in _EMBEDDED_MODE_VALUES:
        mode = embedded_translation_mode()
    return {
        'mode': mode,
        'enabled': mode != 'off',
        'try_align': mode in ('auto', 'align_only', 'local_only'),
        'try_extract': mode in ('auto', 'direct', 'local_only'),
        'allow_http': mode not in ('off', 'local_only'),
    }


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


def safe_release_filename(release, fallback=''):
    """Turn a subtitle release name into a safe filename STEM (no extension) for
    a delivered .srt, so Kodi shows the real release instead of a hash. Strips a
    trailing language/extension, replaces filesystem-unsafe characters, collapses
    whitespace, and caps the length. Returns `fallback` when nothing usable
    remains."""
    import re
    s = (release or '').strip()
    # drop a trailing extension and a trailing .he/.heb language tag
    s = re.sub(r'\.(srt|ssa|ass|sub|smi|vtt)$', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\.(he|heb|hebrew)$', '', s, flags=re.IGNORECASE)
    # filesystem-unsafe characters -> nothing/space; keep dots/dashes/brackets
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', ' ', s)
    s = re.sub(r'\s{2,}', ' ', s).strip().strip('.')
    if len(s) > 120:
        s = s[:120].rstrip(' .-_')
    return s or fallback


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
    # User master switch (like DarkSubs): hide all subtitle/translation toasts
    # when turned off. Default ON, so nothing changes unless the user opts out.
    try:
        if (get_setting('subs_notifications', 'true')
                or 'true').strip().lower() == 'false':
            return
    except Exception:
        pass
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
        # Fire the actual GUI toast on a short-lived daemon thread so a wedged
        # GUI/render subsystem can NEVER stall the calling thread. Field case:
        # during heavy debrid embedded-subtitle extraction the video decoder
        # starves and the GUI message pump backs up; a translation-kickoff
        # toast issued from the translate() worker blocked there and froze the
        # whole translation before it could dispatch a single chunk (the user
        # saw "AI is translating" but nothing ever happened). Dialog().
        # notification() is meant to be async, but under that duress it did not
        # return -- so we never issue it on a thread that has real work to do.
        def _show(_title=title, _msg=msg, _icon=icon, _ms=time_ms):
            try:
                xbmcgui.Dialog().notification(_title, _msg, _icon, _ms)
            except Exception:
                pass
            finally:
                with _notify_lock:
                    _notify_pending[0] -= 1
        # Cap the number of toast threads that may be parked at once. Normally a
        # toast returns in milliseconds so the count sits at 0-1; it only climbs
        # when the GUI is wedged and notification() isn't returning -- exactly
        # when we must NOT pile on more blocked threads.
        with _notify_lock:
            if _notify_pending[0] >= _NOTIFY_MAX_PENDING:
                return
            _notify_pending[0] += 1
        try:
            threading.Thread(target=_show, name='pov-notify',
                             daemon=True).start()
        except Exception:
            # Couldn't spawn a thread (thread/memory exhaustion -- itself a sign
            # of a wedged, resource-starved device). Do NOT fall back to an
            # inline notification() call: on the caller's thread that would
            # re-block it, the very stall this whole change exists to prevent.
            # Drop the toast and release the slot we just reserved.
            with _notify_lock:
                _notify_pending[0] -= 1
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
        'tvshow': '', 'is_episode': False, 'tagline': '', 'label': '',
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
    # The release name used for subtitle sync matching. FEN/POV populate
    # the Tagline with the real release (e.g. "Swapped.2026.1080p.NF.WEB-
    # DL.DDP5.1.Atmos.H.264-TURG"); for debrid streams the filepath is a
    # tokenized URL, so the Tagline is what makes the match % meaningful.
    info['tagline'] = gi('VideoPlayer.Tagline') or gi('ListItem.Tagline')
    # The visible label is another good release-name fallback.
    info['label'] = gi('VideoPlayer.Label') or gi('ListItem.Label')
    # ListItem path is often the real release name even when the player's
    # filepath is a tokenized debrid URL -- key for the sync-% matching.
    info['li_filename'] = gi('ListItem.FileNameAndPath') \
        or gi('ListItem.FilenameAndPath')
    # The picked release name POV captures into a home-window property
    # (set by pov_source_name_patcher / subs_filename_publisher, the same
    # one DarkSubs reads). This is the most reliable release name for
    # sync-% matching on debrid streams.
    info['picked_release'] = gi('Window(10000).Property(subs.player_filename)')
    info['is_episode'] = bool(info['tvshow'] and info['episode'])
    return info


_CURRENT_SUB_PROP = 'moransubs.current_sub'
_CURRENT_SUB_ID_PROP = 'moransubs.current_sub_id'
_CURRENT_SUB_STATUS_PROP = 'moransubs.current_subsync_status'
_CURRENT_SUB_TOKEN_PROP = 'moransubs.current_sub_token'
_CURRENT_SUB_FIX_READY_PROP = 'moransubs.current_subsync_fix_ready'
_CURRENT_SUB_DELIVERY_PROP = 'moransubs.current_subsync_delivery'

# Short, skin-safe labels. The value is shown only for the subtitle that is
# actually selected, after the exact playing stream has been matched. It is a
# Window property (RAM for this Kodi session), not an on-disk cache or lookup.
_SUBTITLE_SYNC_LABELS = {
    'checking': 'תזמון בבדיקה',
    'confirmed': 'כבר מסונכרנת',
    'fixed': 'סונכרנה אוטומטית',
    'unverified': 'התזמון טרם אומת',
}


def _home_window():
    try:
        return xbmcgui.Window(10000) if KODI_AVAILABLE else None
    except Exception:
        return None


def _current_stream_hash(stream_url=None):
    """Opaque identity of the exact playing URL; never persist/log its token."""
    try:
        value = stream_url
        if value is None:
            value = xbmc.Player().getPlayingFile()
        # Kodi's ``|Header=...`` suffix can select a different debrid object
        # even when the visible URL is identical.  It is safe to include here:
        # only the digest leaves this function, never the URL or its headers.
        value = (value or '').strip()
        if not value:
            return ''
        return hashlib.sha256(
            value.encode('utf-8', 'replace')).hexdigest()[:24]
    except Exception:
        return ''


def _subtitle_link_hash(link):
    try:
        return hashlib.sha256(
            (link or '').encode('utf-8', 'replace')).hexdigest()[:24]
    except Exception:
        return ''


def subtitle_candidate_identity(link):
    """Return a short, private identity that survives refreshed picker links.

    Provider rows are URL-encoded JSON. Some providers refresh transport
    details between the automatic search and a later manual picker open, even
    though the row still names the exact same subtitle. The old UI compared the
    entire encoded payload, so a subtitle that was already on screen could lose
    its ``current`` marker. Keep only the fields that identify the logical
    subtitle, then hash them; no provider URL, token or local path is exposed
    through the Kodi window property.
    """
    try:
        value = str(link or '')
        payload = None
        for _ in range(3):
            try:
                decoded = json.loads(value)
                if isinstance(decoded, dict):
                    payload = decoded
                    break
            except Exception:
                pass
            unquoted = urllib.parse.unquote(value)
            if unquoted == value:
                break
            value = unquoted
        if not payload:
            return _subtitle_link_hash(link)

        kind = str(payload.get('type') or '')
        stable = {'type': kind}
        if kind == 'pool':
            # The content hash is the community row's immutable identity. Its
            # release/source labels may be enriched by a later lookup.
            content_hash = str(payload.get('hash') or '')
            if not content_hash:
                return _subtitle_link_hash(link)
            stable['hash'] = content_hash
        elif kind in ('engine', 'engine_ai'):
            download_data = payload.get('download_data') or {}
            if not isinstance(download_data, dict):
                download_data = {}
            source = str(payload.get('source') or '').strip().lower()

            # A filename is not a provider row id: OpenSubtitles and other
            # engines can return two different files with the same display
            # name.  Use only explicit, stable provider identifiers.  When a
            # provider exposes none, retain strict full-link semantics rather
            # than risking a false ``current`` marker on another row.
            provider_id = None
            id_fields = (
                'id', 'file_id', 'fileId', 'subtitle_id', 'subtitleId',
                'sub_id', 'subId', 'SubtitleID',
            )
            if source != 'ktuvit':
                for field in id_fields:
                    value = download_data.get(field)
                    if value not in ('', None):
                        provider_id = {field: str(value)}
                        break
            if source == 'ktuvit':
                # Ktuvit_Page_ID identifies the film page, not one subtitle;
                # every sibling row shares it. Only FilmID+SubtitleID from the
                # signed request (or an explicit SubtitleID) is row-unique.
                direct_subtitle_id = download_data.get('SubtitleID')
                if direct_subtitle_id not in ('', None):
                    provider_id = {'SubtitleID': str(direct_subtitle_id)}
                raw_request = download_data.get('subtitle_download_data')
                try:
                    request = (json.loads(raw_request)
                               if isinstance(raw_request, str)
                               else raw_request) or {}
                    request = request.get('request') or request
                    film_id = request.get('FilmID')
                    subtitle_id = request.get('SubtitleID')
                    if film_id not in ('', None) and subtitle_id not in ('', None):
                        provider_id = {
                            'FilmID': str(film_id),
                            'SubtitleID': str(subtitle_id),
                        }
                except Exception:
                    pass
            if provider_id is None:
                return _subtitle_link_hash(link)
            stable.update({
                'embedded': bool(payload.get('embedded')),
                'stream_index': payload.get('stream_index', ''),
                'source': source,
                'language': str(payload.get('language') or
                                payload.get('lang') or '').strip().lower(),
                'provider_id': provider_id,
            })
        elif kind == 'embedded_sync':
            stable.update({
                'stream_index': payload.get('stream_index', ''),
                'language': str(payload.get('language') or
                                payload.get('lang') or 'he').strip().lower(),
            })
        elif kind in ('ai', 'embedded_ai'):
            stable.update({
                'source_lang': str(payload.get('source_lang') or '')
                               .strip().lower(),
                # Paths stay private because the canonical structure is hashed.
                'local_path': str(payload.get('local_path') or ''),
                'stream_index': payload.get('stream_index', ''),
            })
        elif kind == 'passthrough':
            stable['path'] = str(payload.get('path') or '')
        else:
            # Unknown future kinds retain strict semantics. Sorting keys makes
            # harmless JSON field-order changes stable without guessing which
            # new fields may be safe to ignore.
            stable = payload
        canonical = json.dumps(stable, ensure_ascii=False, sort_keys=True,
                               separators=(',', ':'))
        return hashlib.sha256(
            canonical.encode('utf-8', 'replace')).hexdigest()[:24]
    except Exception:
        return _subtitle_link_hash(link)


def _new_subtitle_selection_token(link):
    try:
        seed = '{0}\0{1}\0{2}'.format(
            time.time_ns(), threading.get_ident(), link or '')
        return hashlib.sha256(seed.encode('utf-8', 'replace')).hexdigest()[:24]
    except Exception:
        return hashlib.sha256(
            ('{0}\0{1}'.format(time.time(), link or '')).encode(
                'utf-8', 'replace')).hexdigest()[:24]


def clear_subtitle_sync_status():
    """Clear the tiny current-selection status record (no disk/network I/O)."""
    try:
        win = _home_window()
        if win is not None:
            token = win.getProperty(_CURRENT_SUB_TOKEN_PROP) or ''
            if token:
                win.clearProperty(_CURRENT_SUB_STATUS_PROP + '.' + token)
                win.clearProperty(_CURRENT_SUB_FIX_READY_PROP + '.' + token)
                win.clearProperty(_CURRENT_SUB_DELIVERY_PROP + '.' + token)
            # Remove a record left by the pre-token implementation too.
            win.clearProperty(_CURRENT_SUB_STATUS_PROP)
            win.clearProperty(_CURRENT_SUB_DELIVERY_PROP)
    except Exception:
        pass


def set_current_subtitle(link):
    """Remember which subtitle (by its candidate link) is currently applied,
    so the picker can mark it as '» נוכחית' next time it opens. Stored on the
    home window so it's visible across the service / picker processes."""
    if not KODI_AVAILABLE:
        return
    try:
        win = _home_window()
        if win is None:
            return
        new_link = link or ''
        try:
            old_link = win.getProperty(_CURRENT_SUB_PROP) or ''
        except Exception:
            old_link = get_current_subtitle()
        try:
            old_token = win.getProperty(_CURRENT_SUB_TOKEN_PROP) or ''
        except Exception:
            old_token = ''
        # A verdict belongs to one selected candidate. Re-selecting the same
        # one preserves its result; selecting anything else invalidates it.
        if old_link != new_link:
            clear_subtitle_sync_status()
            # Background and manual-delay records are token-scoped. Retire only
            # the selection being replaced, so a late process cannot erase the
            # newer selection's state.
            if old_token:
                win.clearProperty('subsync.pending.' + old_token)
                win.clearProperty('subsync.delivered.' + old_token)
            win.clearProperty('subsync.pending')
            win.clearProperty('subsync.delivered')
            win.setProperty(
                _CURRENT_SUB_TOKEN_PROP,
                _new_subtitle_selection_token(new_link) if new_link else '')
        elif new_link and not (win.getProperty(_CURRENT_SUB_TOKEN_PROP) or ''):
            # Upgrade a live session from a release that pre-dated tokens.
            win.setProperty(_CURRENT_SUB_TOKEN_PROP,
                            _new_subtitle_selection_token(new_link))
        win.setProperty(_CURRENT_SUB_PROP, new_link)
        win.setProperty(_CURRENT_SUB_ID_PROP,
                        subtitle_candidate_identity(new_link) if new_link else '')
    except Exception:
        pass


def get_current_subtitle():
    """The link of the currently-applied subtitle (see above), or ''."""
    if not KODI_AVAILABLE:
        return ''
    try:
        win = _home_window()
        if win is not None:
            value = win.getProperty(_CURRENT_SUB_PROP) or ''
            if value:
                return value
        return xbmc.getInfoLabel(
            'Window(10000).Property({0})'.format(_CURRENT_SUB_PROP)) or ''
    except Exception:
        return ''


def get_current_subtitle_identity():
    """Opaque logical identity of the applied picker row, or ``''``."""
    if not KODI_AVAILABLE:
        return ''
    try:
        win = _home_window()
        value = (win.getProperty(_CURRENT_SUB_ID_PROP) or '') if win else ''
        if value:
            return value
        # Upgrade a selection made by an older in-memory module after an add-on
        # hot update. A normal new selection always takes the bounded property
        # path above.
        return subtitle_candidate_identity(get_current_subtitle())
    except Exception:
        return ''


def get_subtitle_selection_token():
    if not KODI_AVAILABLE:
        return ''
    try:
        win = _home_window()
        return (win.getProperty(_CURRENT_SUB_TOKEN_PROP) or '') if win else ''
    except Exception:
        return ''


def current_subtitle_selection(expected_link=None):
    """Opaque snapshot a foreground/background timing job can bind to.

    When ``expected_link`` is supplied, return an empty snapshot unless that
    exact picker candidate is still current.  This closes the gap where an old
    RunScript process starts after the user has already picked another row and
    would otherwise snapshot the newer row as if it owned it.
    """
    try:
        link = get_current_subtitle()
        if expected_link is not None and link != (expected_link or ''):
            return {'token': '', 'link_hash': '', 'stream_hash': ''}
        return {
            'token': get_subtitle_selection_token(),
            'link_hash': _subtitle_link_hash(link),
            'stream_hash': _current_stream_hash(),
        }
    except Exception:
        return {'token': '', 'link_hash': '', 'stream_hash': ''}


def subtitle_selection_matches(selection_token='', link_hash='',
                               stream_hash=''):
    """True only while all supplied opaque selection identities are current."""
    try:
        if not (selection_token and link_hash and stream_hash):
            return False
        current_link = get_current_subtitle()
        if not current_link:
            return False
        if selection_token != get_subtitle_selection_token():
            return False
        if link_hash != _subtitle_link_hash(current_link):
            return False
        if stream_hash != _current_stream_hash():
            return False
        return True
    except Exception:
        return False


def set_subtitle_sync_status(state, source='', link=None, stream_url=None,
                             selection_token='', link_hash='',
                             stream_hash=''):
    """Publish timing state for the exact current subtitle and video.

    The record contains only hashes plus a short state/source. It lives in a
    Kodi Window property, so this adds no Cloudflare request, write, user-cache
    file or persistent storage. A stale background job cannot attach its result
    to another pick because both the candidate and stream must match.
    """
    if not KODI_AVAILABLE or state not in _SUBTITLE_SYNC_LABELS:
        return False
    try:
        current = get_current_subtitle()
        selected = current if link is None else (link or '')
        if not current or selected != current:
            return False
        current_token = get_subtitle_selection_token()
        current_link_hash = _subtitle_link_hash(selected)
        current_stream_hash = _current_stream_hash()
        expected_stream_hash = (stream_hash or
                                _current_stream_hash(stream_url))
        if (not current_token or not current_stream_hash
                or not current_link_hash):
            return False
        if selection_token and selection_token != current_token:
            return False
        if link_hash and link_hash != current_link_hash:
            return False
        if expected_stream_hash and expected_stream_hash != current_stream_hash:
            return False
        payload = {
            'v': 1,
            'state': state,
            'source': (source or '')[:24],
            'token': current_token,
            'link': current_link_hash,
            'stream': current_stream_hash,
            'ts': int(time.time()),
        }
        win = _home_window()
        if win is None:
            return False
        raw = json.dumps(payload, separators=(',', ':'))
        prop = _CURRENT_SUB_STATUS_PROP + '.' + current_token
        win.setProperty(prop, raw)
        # Close the compare/write race: if the user changed selection while the
        # property was being written, remove only OUR stale record. Never clear
        # a newer job's status that may already have replaced it.
        if not subtitle_selection_matches(
                current_token, current_link_hash, current_stream_hash):
            if win.getProperty(prop) == raw:
                win.clearProperty(prop)
            return False
        return True
    except Exception:
        return False


def get_subtitle_sync_status(link=None, stream_url=None):
    """Return the current timing record only when pick AND stream still match."""
    if not KODI_AVAILABLE:
        return {}
    try:
        current = get_current_subtitle()
        selected = current if link is None else (link or '')
        if not current or selected != current:
            return {}
        win = _home_window()
        token = get_subtitle_selection_token()
        raw = (win.getProperty(_CURRENT_SUB_STATUS_PROP + '.' + token)
               if win and token else '')
        record = json.loads(raw) if raw else {}
        state = record.get('state')
        if (record.get('v') != 1 or state not in _SUBTITLE_SYNC_LABELS
                or record.get('token') != get_subtitle_selection_token()
                or record.get('link') != _subtitle_link_hash(selected)
                or record.get('stream') != _current_stream_hash(stream_url)):
            return {}
        return dict(record, label=_SUBTITLE_SYNC_LABELS[state])
    except Exception:
        return {}


def subtitle_sync_status_label(state):
    return _SUBTITLE_SYNC_LABELS.get(state, '')


def _selection_values(selection=None):
    expected = selection if selection is not None else current_subtitle_selection()
    expected = expected or {}
    return {
        'token': expected.get('token') or '',
        'link_hash': expected.get('link_hash') or '',
        'stream_hash': expected.get('stream_hash') or '',
    }


def _subtitle_path_hash(path):
    try:
        return hashlib.sha256(
            str(path or '').encode('utf-8', 'replace')).hexdigest()[:24]
    except Exception:
        return ''


def stage_subtitle_delivery(path, selection=None, status='', source=''):
    """Arm an exact, RAM-only acknowledgement for the foreground delivery.

    A deep timing worker may be faster than Kodi's subtitle picker callback. It
    must not replace a subtitle until the foreground path has positively seen
    Kodi register and select the original file. Only hashes are stored; neither
    the local path nor the tokenised media URL is exposed or persisted.
    """
    try:
        expected = _selection_values(selection)
        path_hash = _subtitle_path_hash(path)
        if (not path_hash or not all(expected.values())
                or not subtitle_selection_matches(
                    expected['token'], expected['link_hash'],
                    expected['stream_hash'])):
            return False
        final_status = status if status in _SUBTITLE_SYNC_LABELS else ''
        # "checking" is deliberately published before enqueue so the picker can
        # show live work; it is never a final delivery verdict to commit here.
        if final_status == 'checking':
            final_status = ''
        payload = {
            'v': 1,
            'path': path_hash,
            'link': expected['link_hash'],
            'stream': expected['stream_hash'],
            'applied': 0,
            'status': final_status,
            'source': (source or '')[:24],
            'ts': int(time.time()),
        }
        win = _home_window()
        if win is None:
            return False
        prop = _CURRENT_SUB_DELIVERY_PROP + '.' + expected['token']
        raw = json.dumps(payload, separators=(',', ':'))
        win.setProperty(prop, raw)
        if not subtitle_selection_matches(
                expected['token'], expected['link_hash'],
                expected['stream_hash']):
            if win.getProperty(prop) == raw:
                win.clearProperty(prop)
            return False
        return True
    except Exception:
        return False


def _subtitle_delivery_record(path, selection=None, require_current=True):
    try:
        expected = _selection_values(selection)
        path_hash = _subtitle_path_hash(path)
        if not path_hash or not all(expected.values()):
            return {}, expected, '', None
        if (require_current and not subtitle_selection_matches(
                expected['token'], expected['link_hash'],
                expected['stream_hash'])):
            return {}, expected, '', None
        win = _home_window()
        prop = _CURRENT_SUB_DELIVERY_PROP + '.' + expected['token']
        raw = win.getProperty(prop) if win else ''
        record = json.loads(raw) if raw else {}
        if (record.get('v') != 1 or record.get('path') != path_hash
                or record.get('link') != expected['link_hash']
                or record.get('stream') != expected['stream_hash']):
            return {}, expected, raw, win
        return record, expected, raw, win
    except Exception:
        return {}, _selection_values(selection), '', None


def subtitle_delivery_staged(path, selection=None):
    record, _expected, _raw, _win = _subtitle_delivery_record(
        path, selection=selection)
    return bool(record)


def mark_subtitle_delivery_applied(path, selection=None):
    """Acknowledge only the exact file Kodi visibly registered and selected."""
    try:
        record, expected, raw, win = _subtitle_delivery_record(
            path, selection=selection)
        if not record or win is None:
            return False
        record['applied'] = 1
        record['ts'] = int(time.time())
        prop = _CURRENT_SUB_DELIVERY_PROP + '.' + expected['token']
        updated = json.dumps(record, separators=(',', ':'))
        # Do not overwrite a newer stage that replaced the one we observed.
        if win.getProperty(prop) != raw:
            return False
        win.setProperty(prop, updated)
        if not subtitle_selection_matches(
                expected['token'], expected['link_hash'],
                expected['stream_hash']):
            if win.getProperty(prop) == updated:
                win.clearProperty(prop)
            return False
        if win.getProperty(prop) != updated:
            return False
        if record.get('status'):
            if not set_subtitle_sync_status(
                    record['status'], source=record.get('source') or 'local',
                    selection_token=expected['token'],
                    link_hash=expected['link_hash'],
                    stream_hash=expected['stream_hash']):
                return False
        return bool(subtitle_selection_matches(
            expected['token'], expected['link_hash'],
            expected['stream_hash']))
    except Exception:
        return False


def subtitle_delivery_is_applied(path, selection=None):
    record, _expected, _raw, _win = _subtitle_delivery_record(
        path, selection=selection)
    return bool(record and record.get('applied') == 1)


def clear_subtitle_delivery(path=None, selection=None):
    """Remove only the matching token/path acknowledgement, never a newer one."""
    try:
        expected = _selection_values(selection)
        if not expected.get('token'):
            return False
        win = _home_window()
        if win is None:
            return False
        prop = _CURRENT_SUB_DELIVERY_PROP + '.' + expected['token']
        raw = win.getProperty(prop) or ''
        record = json.loads(raw) if raw else {}
        if not record:
            return False
        if path is not None and record.get('path') != _subtitle_path_hash(path):
            return False
        if (expected.get('link_hash')
                and record.get('link') != expected['link_hash']):
            return False
        if (expected.get('stream_hash')
                and record.get('stream') != expected['stream_hash']):
            return False
        if win.getProperty(prop) != raw:
            return False
        win.clearProperty(prop)
        return True
    except Exception:
        return False


def abandon_subtitle_selection(selection=None):
    """Clear a failed pick only if it is still the exact current selection."""
    try:
        expected = _selection_values(selection)
        if (not all(expected.values())
                or not subtitle_selection_matches(
                    expected['token'], expected['link_hash'],
                    expected['stream_hash'])):
            return False
        # set_current_subtitle performs token-scoped cleanup for status, staged
        # fixes, delivery acks and delay-learning records.
        set_current_subtitle('')
        return not get_current_subtitle()
    except Exception:
        return False


def stage_subtitle_sync_fix(path, selection=None, source='local', notice=''):
    """Remember a corrected copy until its caller proves Kodi received it."""
    try:
        expected = _selection_values(selection)
        if (not path or not all(expected.values())
                or not subtitle_selection_matches(
                    expected['token'], expected['link_hash'],
                    expected['stream_hash'])):
            return False
        payload = {
            'v': 1,
            'path': hashlib.sha256(
                str(path).encode('utf-8', 'replace')).hexdigest()[:24],
            'source': (source or '')[:24],
            'notice': (notice or '')[:96],
            'ts': int(time.time()),
        }
        win = _home_window()
        if win is None:
            return False
        prop = _CURRENT_SUB_FIX_READY_PROP + '.' + expected['token']
        raw = json.dumps(payload, separators=(',', ':'))
        win.setProperty(prop, raw)
        if not subtitle_selection_matches(
                expected['token'], expected['link_hash'],
                expected['stream_hash']):
            if win.getProperty(prop) == raw:
                win.clearProperty(prop)
            return False
        return True
    except Exception:
        return False


def subtitle_sync_fix_staged(path, selection=None):
    """Whether ``path`` is the correction staged for this exact selection."""
    try:
        expected = _selection_values(selection)
        if (not path or not all(expected.values())
                or not subtitle_selection_matches(
                    expected['token'], expected['link_hash'],
                    expected['stream_hash'])):
            return False
        win = _home_window()
        raw = (win.getProperty(
            _CURRENT_SUB_FIX_READY_PROP + '.' + expected['token'])
               if win else '')
        record = json.loads(raw) if raw else {}
        path_hash = hashlib.sha256(
            str(path).encode('utf-8', 'replace')).hexdigest()[:24]
        return bool(record.get('v') == 1 and record.get('path') == path_hash)
    except Exception:
        return False


def subtitle_sync_registration_baseline(path, selection=None, player=None):
    """Capture the stream count when a correction or delivery ack is staged.

    ``None`` means no proof is needed. ``-1`` means Kodi exposes no observation
    channel, so callers still deliver fail-open but must not publish FIXED.
    """
    if not (subtitle_sync_fix_staged(path, selection=selection)
            or subtitle_delivery_staged(path, selection=selection)):
        return None
    try:
        p = player or xbmc.Player()
        return len(p.getAvailableSubtitleStreams() or [])
    except Exception:
        return -1


def confirm_subtitle_sync_registration(path, selection=None, before=None,
                                       player=None, timeout_ms=1000,
                                       select_new=True):
    """Confirm FIXED only after Kodi visibly registers a new subtitle stream."""
    if before is None or before < 0:
        return False
    expected = _selection_values(selection)
    if not all(expected.values()):
        return False
    try:
        p = player or xbmc.Player()
        steps = max(1, min(40, int(max(0, timeout_ms) / 50)))
        for _ in range(steps):
            xbmc.sleep(50)
            if not subtitle_selection_matches(
                    expected['token'], expected['link_hash'],
                    expected['stream_hash']):
                return False
            try:
                streams = p.getAvailableSubtitleStreams() or []
            except Exception:
                return False
            if len(streams) > before:
                if select_new:
                    try:
                        p.setSubtitleStream(len(streams) - 1)
                    except Exception:
                        # Growth proves registration, but Kodi may keep an older
                        # Hebrew stream active. Without a successful pin we
                        # cannot truthfully claim the repaired copy is applied.
                        return False
                if not subtitle_selection_matches(
                        expected['token'], expected['link_hash'],
                        expected['stream_hash']):
                    return False
                acknowledged = mark_subtitle_delivery_applied(
                    path, selection=expected)
                confirmed = confirm_subtitle_sync_fix(
                    path, selection=expected)
                return bool(acknowledged or confirmed)
        return False
    except Exception:
        return False


def apply_subtitle_file(path, selection=None, fix_path=None, timeout_ms=1000,
                        abandon_on_failure=True):
    """Hand one file to Kodi without letting stale work affect a newer pick.

    The file is applied fail-open. When it represents a staged timing repair,
    FIXED is published only after the new stream appears in Kodi's stream list.
    ``fix_path`` names the staged source when ``path`` is a display-name copy.
    """
    expected = _selection_values(selection)
    if not path or not all(expected.values()):
        return False
    try:
        if not subtitle_selection_matches(
                expected['token'], expected['link_hash'],
                expected['stream_hash']):
            return False
        p = xbmc.Player()
        try:
            if not p.isPlayingVideo():
                return False
        except Exception:
            return False
        staged_path = fix_path or path
        before = subtitle_sync_registration_baseline(
            staged_path, selection=expected, player=p)
        if not subtitle_selection_matches(
                expected['token'], expected['link_hash'],
                expected['stream_hash']):
            return False
        # Freeze the real embedded-stream baseline before Kodi appends this
        # external file. This is intentionally lazy to avoid a module cycle.
        try:
            from resources.lib import subs_engine_bridge
            subs_engine_bridge.seal_playback_streams(current_video_info())
        except Exception:
            pass
        p.setSubtitles(path)
        p.showSubtitles(True)
        if not subtitle_selection_matches(
                expected['token'], expected['link_hash'],
                expected['stream_hash']):
            return False
        if before is not None:
            confirmed = confirm_subtitle_sync_registration(
                staged_path, selection=expected, before=before,
                player=p, timeout_ms=timeout_ms)
            if not confirmed:
                if abandon_on_failure:
                    abandon_subtitle_selection(expected)
                return False
        return bool(subtitle_selection_matches(
            expected['token'], expected['link_hash'],
            expected['stream_hash']))
    except Exception:
        if abandon_on_failure:
            abandon_subtitle_selection(expected)
        return False


def confirm_subtitle_sync_fix(path, selection=None):
    """Publish FIXED after a caller has positively proven Kodi registration."""
    try:
        expected = _selection_values(selection)
        if (not path or not all(expected.values())
                or not subtitle_selection_matches(
                    expected['token'], expected['link_hash'],
                    expected['stream_hash'])):
            return False
        win = _home_window()
        prop = _CURRENT_SUB_FIX_READY_PROP + '.' + expected['token']
        raw = win.getProperty(prop) if win else ''
        record = json.loads(raw) if raw else {}
        path_hash = hashlib.sha256(
            str(path).encode('utf-8', 'replace')).hexdigest()[:24]
        if record.get('v') != 1 or record.get('path') != path_hash:
            return False
        published = set_subtitle_sync_status(
            'fixed', source=record.get('source') or 'local',
            selection_token=expected['token'],
            link_hash=expected['link_hash'],
            stream_hash=expected['stream_hash'])
        if published:
            if win.getProperty(prop) == raw:
                win.clearProperty(prop)
            # The status write itself is token-scoped, but a toast is global.
            # Re-check after the write so A cannot announce over B if the user
            # changed subtitles in that tiny interval.
            still_current = subtitle_selection_matches(
                expected['token'], expected['link_hash'],
                expected['stream_hash'])
            if still_current and record.get('notice'):
                notify(record['notice'], time_ms=5000)
            return bool(still_current)
        return False
    except Exception:
        return False


def progress_dialog():
    """Return a DialogProgressBG or None if not available."""
    if not KODI_AVAILABLE:
        return None
    try:
        return xbmcgui.DialogProgressBG()
    except Exception:
        return None
