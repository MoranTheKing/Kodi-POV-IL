# OpenSubtitles client. Anonymous tier only (200 requests/day per
# IP, no auth header). We just need: query by IMDB id + language,
# get a list of subtitles, download one.
#
# OpenSubtitles' v1 REST API requires an Api-Key header even for
# anonymous use. We use the publicly published one from their
# documentation (intended for low-volume integrations). If we ever
# hit rate limits, we'll switch to letting users plug their own
# free OS account in.

import json
import urllib.parse

try:
    import requests
except ImportError:
    requests = None

API_BASE = 'https://api.opensubtitles.com/api/v1'

# Public "demo" / docs Api-Key. OS encourages low-volume callers
# to use this without per-user signup. If they revoke it, the
# addon will degrade gracefully and the user can plug their own.
PUBLIC_API_KEY = 'jjBg5VlSAEhk0xkb6lEoiTPwUO0VvP3z'

USER_AGENT = 'KodiPovIlAI/0.1'

DEFAULT_TIMEOUT = 15


def _headers():
    return {
        'Api-Key': PUBLIC_API_KEY,
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

    params = {}
    if imdb_id:
        # OS expects the numeric part only.
        s = str(imdb_id).lower().lstrip('t')
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
        r = requests.get(url, headers=_headers(), timeout=DEFAULT_TIMEOUT)
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

    try:
        r = requests.post(
            API_BASE + '/download',
            headers={**_headers(), 'Content-Type': 'application/json'},
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
