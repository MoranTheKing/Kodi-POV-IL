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
# Wyzie's API is Cloudflare-fronted and sometimes returns 522
# (origin unreachable) or just hangs on the SSL handshake. Keeping
# the per-request timeout tight so a single bad call doesn't lock
# up subtitle search for a long time -- a per-call retry handles
# the occasional transient.
DEFAULT_TIMEOUT = 8
# Number of retries on connection-level failure (timeout, DNS,
# refused). NOT applied to HTTP error responses -- those mean we
# reached Wyzie and got a real answer (e.g. 401, 429), retrying
# wouldn't help.
RETRY_ON_TIMEOUT = 1
RETRY_DELAY = 2.0

# Wyzie wraps OpenSubtitles, and OpenSubtitles is inconsistent about
# whether Hebrew is 'he' (ISO 639-1, modern), 'heb' (ISO 639-2/B,
# OpenSubtitles legacy), or even 'iw' (deprecated ISO 639-1, still
# served by some scrapers). When we ask for Hebrew we try all three
# variants and union the results -- some titles only show up under
# the legacy code. For other languages this is a no-op since the
# 2-letter form is universal.
_LANG_ALIASES = {
    'he':  ('he', 'heb', 'iw'),
}


class _SearchResult(list):
    """List subclass that carries last-call diagnostics. Callers that
    need to know WHY a search returned empty can read .last_http_status
    and .last_error -- regular list code keeps working unchanged."""
    last_http_status = None
    last_error = None


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
    except requests.Timeout:
        return {'ok': False,
                'message': 'Wyzie לא הגיב תוך {0} שניות. השירות שלהם '
                           'מקרטע מדי פעם (Cloudflare 522 / origin '
                           'unreachable). נסה שוב בעוד דקה-שתיים. '
                           'אם זה נמשך - הבעיה אצלם, לא אצלך.'
                           .format(DEFAULT_TIMEOUT)}
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

    import time as _time
    out = _SearchResult()
    last_http_status = None  # surface to caller for diagnostics
    last_error = None
    # If the very first request times out, Wyzie is probably offline
    # right now. Bail out of the whole search rather than chewing
    # through 30+ seconds across multiple language aliases. The
    # caller's empty-result diagnostic will explain.
    service_offline = False
    for lang in languages:
        if service_offline:
            break
        # Try each language alias (e.g. 'he', 'heb', 'iw' for Hebrew).
        # As soon as one returns results, take them and don't retry
        # under another alias for this language slot.
        aliases = _LANG_ALIASES.get(lang, (lang,))
        for code in aliases:
            if service_offline:
                break
            params = {'id': ident, 'language': code, 'key': key}
            if season:
                params['season'] = str(season)
            if episode:
                params['episode'] = str(episode)
            url = API_BASE + '/search?' + urllib.parse.urlencode(params)
            r = None
            attempts = 0
            while attempts <= RETRY_ON_TIMEOUT:
                try:
                    r = requests.get(
                        url,
                        headers={'User-Agent': USER_AGENT,
                                 'Accept': 'application/json'},
                        timeout=DEFAULT_TIMEOUT,
                    )
                    break
                except requests.RequestException as e:
                    last_error = str(e)[:120]
                    kodi_utils.log(
                        'wyzie search {0}/{1} attempt {2}: '
                        'request failed: {3}'.format(
                            lang, code, attempts + 1, last_error),
                        level='WARNING')
                    attempts += 1
                    if attempts <= RETRY_ON_TIMEOUT:
                        _time.sleep(RETRY_DELAY)
            if r is None:
                # All retries exhausted on a connection-level error.
                # If this was the first lang/alias and nothing has
                # come back at all so far, assume Wyzie is offline
                # right now and stop chewing the user's time on
                # subsequent language slots.
                if not out and last_http_status is None:
                    service_offline = True
                continue
            last_http_status = r.status_code
            if r.status_code != 200:
                kodi_utils.log(
                    'wyzie search {0}/{1}: HTTP {2}'.format(
                        lang, code, r.status_code),
                    level='WARNING')
                # On 5xx, try another alias -- might be a per-code
                # backend issue rather than a service-wide outage.
                continue
            try:
                body = r.json()
            except ValueError as e:
                last_error = 'invalid JSON'
                kodi_utils.log(
                    'wyzie search {0}/{1}: invalid JSON'.format(
                        lang, code), level='WARNING')
                continue
            items_before = len(out)
            for item in _extract_list(body):
                norm = _normalise_result(item)
                if norm:
                    if not norm['language']:
                        norm['language'] = lang  # stamp the canonical code
                    else:
                        # Re-stamp any legacy code back to the canonical
                        # 2-letter form so downstream code (which keys
                        # by 'he') still finds Hebrew hits even if the
                        # response came back as 'heb' or 'iw'.
                        norm['language'] = lang
                    out.append(norm)
            if len(out) > items_before:
                # Got hits under this alias; no need to try further aliases.
                kodi_utils.log(
                    'wyzie {0}: {1} hits via code "{2}"'.format(
                        lang, len(out) - items_before, code),
                    level='DEBUG')
                break
        else:
            # all aliases exhausted, no hits
            kodi_utils.log(
                'wyzie {0}: 0 hits across aliases {1} (last HTTP {2})'
                .format(lang, list(aliases), last_http_status),
                level='INFO')

    out.last_http_status = last_http_status
    out.last_error = last_error
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
