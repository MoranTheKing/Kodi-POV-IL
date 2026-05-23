# Wyzie Subs API client. https://sub.wyzie.io / https://docs.wyzie.io
#
# Wyzie is an OpenSubtitles-backed subtitle search proxy with a more
# generous free quota than OS itself (1,000 requests/day on the free
# key tier as of May 2026, vs OS's 5 downloads/day). Each user signs
# up at store.wyzie.io/redeem and pastes their key into our settings.
#
# This module is OPTIONAL. If no key is configured, callers should
# fall back to the temp-dir scanning path in local_subs.find_in_temp.

import json
import urllib.parse

try:
    import requests
except ImportError:
    requests = None

from . import kodi_utils

API_BASE = 'https://sub.wyzie.io'
USER_AGENT = 'KodiPovIlAI/0.1'
DEFAULT_TIMEOUT = 15


def _api_key():
    return (kodi_utils.get_setting('wyzie_api_key', '') or '').strip()


def has_api_key():
    return bool(_api_key())


# ---- result normalisation ------------------------------------------

def _normalise_result(item):
    """Map a Wyzie result dict into the shape our caller expects:
        {'url': '<download url>',
         'language': 'en',
         'release':  '<release tag>',
         'name':     '<file name>',
         'format':   'srt',
         'hi':       bool,
         'download_count': int}
    Returns None if essential fields are missing."""
    if not isinstance(item, dict):
        return None
    url = (item.get('url') or item.get('download') or
           item.get('downloadUrl') or item.get('link'))
    if not url:
        return None
    lang = (item.get('language') or item.get('lang') or '').lower()
    fmt = (item.get('format') or item.get('extension') or
           'srt').lower().lstrip('.')
    return {
        'url':      url,
        'language': lang,
        'release':  item.get('release') or item.get('title') or
                    item.get('name') or '',
        'name':     item.get('name') or item.get('release') or
                    item.get('title') or '',
        'format':   fmt,
        'hi':       bool(item.get('hi') or item.get('hearing_impaired')),
        'download_count': int(item.get('download_count') or
                              item.get('downloads') or 0),
    }


def _extract_list(body):
    """Wyzie's response shape isn't formally documented; be tolerant
    of `[{...}, ...]`, `{"results": [...]}` or `{"subtitles": [...]}`."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ('results', 'subtitles', 'data', 'items'):
            v = body.get(key)
            if isinstance(v, list):
                return v
    return []


# ---- public API ----------------------------------------------------

def test_key(api_key=None):
    """Lightweight reachability check for the Wyzie API. Used by the
    settings "Test Wyzie connection" button.

    Returns a status dict:
      {'ok': bool, 'message': str}
    The message is short and user-facing (Hebrew). 'ok' is True if
    the key is valid and reachable, False otherwise.

    Strategy: hit /search with a known-good IMDB id (Inception,
    tt1375666) requesting English. If we get an HTTP 200 with a
    list of results, the key works. Anything else, classify and
    explain.
    """
    if not requests:
        return {'ok': False,
                'message': 'requests library unavailable (Python issue)'}
    key = (api_key if api_key is not None else _api_key())
    if not key:
        return {'ok': False, 'message': 'לא הוגדר API key'}

    test_url = (API_BASE + '/search?id=tt1375666&language=en&key='
                + urllib.parse.quote(key))
    try:
        r = requests.get(
            test_url,
            headers={'User-Agent': USER_AGENT,
                     'Accept': 'application/json'},
            timeout=DEFAULT_TIMEOUT,
        )
    except requests.RequestException as e:
        return {'ok': False,
                'message': 'נכשל להתחבר ל-Wyzie: {0}'.format(str(e)[:80])}

    status = r.status_code
    if status == 200:
        try:
            body = r.json()
        except ValueError:
            return {'ok': False,
                    'message': 'תגובה לא תקינה מ-Wyzie (לא JSON)'}
        items = _extract_list(body)
        return {'ok': True,
                'message': 'התחברות תקינה. נמצאו {0} כתוביות לסרט '
                           'הבדיקה (Inception).'.format(len(items))}
    if status == 401 or status == 403:
        return {'ok': False,
                'message': 'API key לא תקין או נדחה ({0}).'.format(status)}
    if status == 429:
        return {'ok': False,
                'message': 'חרגת מהמכסה היומית (1000 בקשות ביום). '
                           'המתן עד מחר או שדרג את החשבון.'}
    if 500 <= status < 600:
        return {'ok': False,
                'message': 'Wyzie במצב תקלה ({0}). נסה שוב מאוחר '
                           'יותר.'.format(status)}
    return {'ok': False,
            'message': 'תגובה בלתי צפויה מ-Wyzie (HTTP {0}).'.format(status)}


def search(imdb_id=None, tmdb_id=None, season=None, episode=None,
           languages=('en',)):
    """Query Wyzie for subtitle candidates.

    Returns a list of normalised dicts (see _normalise_result).
    Empty list on any failure or missing API key.
    """
    if not requests:
        return []
    key = _api_key()
    if not key:
        return []
    if not (imdb_id or tmdb_id):
        return []

    # Wyzie uses a single `id` param that accepts either an IMDB id
    # (with the leading 'tt') or a numeric TMDB id. Prefer the IMDB
    # form -- the docs warn that TMDB ids go through an extra
    # IMDB-lookup step that adds latency.
    if imdb_id:
        s = str(imdb_id).strip().lower()
        if not s.startswith('tt'):
            s = 'tt' + s.lstrip('t')
        ident = s
    else:
        ident = str(tmdb_id)

    out = []
    for lang in languages:
        params = {'id': ident, 'language': lang, 'key': key}
        if season:
            params['season'] = str(season)
        if episode:
            params['episode'] = str(episode)
        url = API_BASE + '/search?' + urllib.parse.urlencode(params)
        try:
            r = requests.get(
                url,
                headers={'User-Agent': USER_AGENT,
                         'Accept': 'application/json'},
                timeout=DEFAULT_TIMEOUT,
            )
            if r.status_code != 200:
                kodi_utils.log(
                    'wyzie search {0}: HTTP {1}'.format(lang, r.status_code),
                    level='WARNING')
                continue
            body = r.json()
        except (requests.RequestException, ValueError) as e:
            kodi_utils.log('wyzie search {0} failed: {1}'.format(lang, e),
                           level='WARNING')
            continue
        for item in _extract_list(body):
            norm = _normalise_result(item)
            if norm:
                # Stamp the language we asked for, in case the
                # response omits it.
                if not norm['language']:
                    norm['language'] = lang
                out.append(norm)
    return out


def download(url):
    """Download an SRT from the URL returned by search(). Returns the
    decoded text, or None on failure."""
    if not requests or not url:
        return None
    try:
        r = requests.get(
            url,
            headers={'User-Agent': USER_AGENT},
            timeout=30,
        )
        if r.status_code != 200:
            return None
        try:
            return r.content.decode('utf-8-sig')
        except UnicodeDecodeError:
            return r.content.decode('utf-8', errors='replace')
    except requests.RequestException:
        return None
