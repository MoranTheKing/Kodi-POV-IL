# OpenSubtitles v1 REST API client. The /api/v1 endpoint requires an
# `Api-Key` header for every request (there is no anonymous endpoint
# in v1). Each user brings their own key -- they sign up free at
# https://www.opensubtitles.com/en/consumers, take ~30 seconds, and
# get a key that's good for ~200 requests/day per IP.
#
# The first version of this file shipped with a made-up "demo" key
# (`jjBg...`) baked in. That key was never valid -- OS responded 403
# "You cannot consume this service" to every request, so the addon's
# subtitle search dialog never showed anything. Fixed by reading the
# key from the addon's settings; if it's empty we just return no
# results instead of pretending to query and getting silently
# rejected.

import json
import urllib.parse

try:
    import requests
except ImportError:
    requests = None

from . import kodi_utils

API_BASE = 'https://api.opensubtitles.com/api/v1'

USER_AGENT = 'KodiPovIlAI/0.1'

DEFAULT_TIMEOUT = 15


def _api_key():
    """User-configured key from the addon's settings. Empty string
    if not set -- callers should treat that as "skip OS"."""
    return (kodi_utils.get_setting('os_api_key', '') or '').strip()


def has_api_key():
    return bool(_api_key())


def _headers():
    key = _api_key()
    if not key:
        return None
    return {
        'Api-Key': key,
        'User-Agent': USER_AGENT,
        'Accept': 'application/json',
    }


def search(imdb_id=None, tmdb_id=None, query=None, year=None,
           season=None, episode=None, languages=('en',)):
    """Query OpenSubtitles for available subtitle files.

    Returns a list of dicts:
        {
          'file_id': int,
          'language': 'en',
          'filename': '...',
          'release': '...',
          'fps': float or None,
          'hi': bool,        # hearing-impaired flag
          'hd': bool,
          'download_count': int,
        }
    Sorted by download_count descending so the most popular match
    is first. Empty list on any failure.
    """
    if not requests:
        return []
    headers = _headers()
    if not headers:
        return []  # no API key configured

    # Guard against query-by-nothing -- with no identifier and no
    # query string, OS returns ALL Hebrew subtitles in their
    # database sorted by popularity. The first revision of this
    # file did that whenever Kodi failed to surface an IMDB id,
    # polluting the search dialog with completely unrelated movies.
    if not imdb_id and not tmdb_id and not query:
        return []

    params = {}
    if imdb_id:
        # OS expects the numeric part only.
        s = str(imdb_id).lower().lstrip('t')
        if s:
            params['imdb_id'] = s
    if tmdb_id:
        params['tmdb_id'] = str(tmdb_id)
    if query and not (imdb_id or tmdb_id):
        params['query'] = query
        if year:
            params['year'] = str(year)
    if season:
        params['season_number'] = str(season)
    if episode:
        params['episode_number'] = str(episode)
    if languages:
        params['languages'] = ','.join(languages)
    params['order_by'] = 'download_count'

    url = API_BASE + '/subtitles?' + urllib.parse.urlencode(params)
    try:
        r = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            return []
        body = r.json()
    except (requests.RequestException, ValueError):
        return []

    out = []
    for item in body.get('data', []):
        attrs = item.get('attributes') or {}
        files = attrs.get('files') or []
        if not files:
            continue
        f = files[0]
        out.append({
            'file_id': f.get('file_id'),
            'language': (attrs.get('language') or '').lower(),
            'filename': f.get('file_name') or attrs.get('release', ''),
            'release': attrs.get('release', ''),
            'fps': attrs.get('fps'),
            'hi': bool(attrs.get('hearing_impaired')),
            'hd': bool(attrs.get('hd')),
            'download_count': attrs.get('download_count', 0),
        })
    return out


def download(file_id):
    """Trade a file_id for the actual SRT text.

    OS's flow is two-step: POST /download to get a temporary URL,
    then GET that URL.
    """
    if not requests or not file_id:
        return None
    auth = _headers()
    if not auth:
        return None  # no API key configured

    try:
        r = requests.post(
            API_BASE + '/download',
            headers={**auth, 'Content-Type': 'application/json'},
            data=json.dumps({'file_id': int(file_id)}),
            timeout=DEFAULT_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        info = r.json()
    except (requests.RequestException, ValueError):
        return None

    link = info.get('link')
    if not link:
        return None

    try:
        r = requests.get(link, timeout=30)
        if r.status_code != 200:
            return None
        # OS returns either a plain .srt or sometimes utf-8-with-BOM.
        try:
            return r.content.decode('utf-8-sig')
        except UnicodeDecodeError:
            # Fall back to permissive decoding -- better to show
            # a mangled subtitle than nothing.
            return r.content.decode('utf-8', errors='replace')
    except requests.RequestException:
        return None
