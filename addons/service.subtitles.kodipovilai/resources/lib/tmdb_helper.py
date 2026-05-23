# Read TMDB credentials from script.module.tmdbhelper, which POV
# users already have configured via "חיבור שירותים". Fetch cast
# data + try to determine each actor's gender so the translation
# prompt can pick correct Hebrew gender forms.
#
# If tmdbhelper isn't installed or no key is set, return empty
# metadata -- the translation still works, just less accurately.

try:
    import requests
except ImportError:
    requests = None

try:
    import xbmcaddon
except ImportError:
    xbmcaddon = None

TMDB_HELPER_ID = 'script.module.tmdbhelper'

# Setting key candidates inside tmdbhelper. Different forks store
# the key under different names; we try each in order.
KEY_SETTING_CANDIDATES = ('api_key', 'tmdb_apikey', 'tmdb_api_key')

API_BASE = 'https://api.themoviedb.org/3'


def _get_tmdb_key():
    """Pull a TMDB v3 API key from script.module.tmdbhelper's
    settings. Returns '' if helper is missing or unconfigured."""
    if not xbmcaddon:
        return ''
    try:
        helper = xbmcaddon.Addon(TMDB_HELPER_ID)
    except Exception:
        return ''
    for k in KEY_SETTING_CANDIDATES:
        try:
            v = helper.getSetting(k)
            if v and v.strip():
                return v.strip()
        except Exception:
            continue
    return ''


def _get(url, params, timeout=15):
    if not requests:
        return None
    try:
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code != 200:
            return None
        return r.json()
    except (requests.RequestException, ValueError):
        return None


# TMDB returns gender as: 0=unspecified, 1=female, 2=male, 3=non-binary.
GENDER_MAP = {0: 'unknown', 1: 'female', 2: 'male', 3: 'non-binary'}


def fetch_cast(imdb_id=None, tmdb_id=None, media_type=None,
               season=None, episode=None, max_actors=12):
    """Look up a film or episode and return its main cast.

    Returns a list of dicts:
        [{'name': 'Charlie Day', 'character': 'Mabel',
          'gender': 'female', 'order': 0}, ...]

    Best-effort: missing pieces (no IMDB id, no TMDB key, etc.)
    return whatever we could resolve. Empty list on full failure.
    """
    key = _get_tmdb_key()
    if not key:
        return []

    # 1. Resolve to a TMDB id + media_type if we only have IMDB.
    if not tmdb_id and imdb_id:
        find = _get(API_BASE + '/find/' + imdb_id,
                    {'api_key': key, 'external_source': 'imdb_id'})
        if find:
            if find.get('movie_results'):
                tmdb_id = find['movie_results'][0].get('id')
                media_type = 'movie'
            elif find.get('tv_results'):
                tmdb_id = find['tv_results'][0].get('id')
                media_type = 'tv'

    if not tmdb_id or not media_type:
        return []

    # 2. Episode-level call if we have season/episode, else
    #    movie/tv top-level credits.
    if media_type == 'tv' and season and episode:
        url = '{0}/tv/{1}/season/{2}/episode/{3}/credits'.format(
            API_BASE, tmdb_id, season, episode)
    elif media_type == 'tv':
        url = '{0}/tv/{1}/aggregate_credits'.format(API_BASE, tmdb_id)
    else:
        url = '{0}/movie/{1}/credits'.format(API_BASE, tmdb_id)

    credits_data = _get(url, {'api_key': key, 'language': 'en-US'})
    if not credits_data:
        return []

    cast = credits_data.get('cast', []) or []
    out = []
    for c in cast[:max_actors]:
        # aggregate_credits puts character names under 'roles'
        character = c.get('character') or ''
        if not character and c.get('roles'):
            character = c['roles'][0].get('character', '')
        out.append({
            'name': c.get('name', ''),
            'character': character,
            'gender': GENDER_MAP.get(c.get('gender', 0), 'unknown'),
            'order': c.get('order', 999),
        })
    out.sort(key=lambda x: x.get('order', 999))
    return out


def title_and_year(imdb_id=None, tmdb_id=None, media_type=None):
    """Convenience: official title + release year from TMDB. Useful
    for the translation prompt header."""
    key = _get_tmdb_key()
    if not key or (not tmdb_id and not imdb_id):
        return ('', '')

    if not tmdb_id:
        find = _get(API_BASE + '/find/' + imdb_id,
                    {'api_key': key, 'external_source': 'imdb_id'})
        if not find:
            return ('', '')
        if find.get('movie_results'):
            d = find['movie_results'][0]
            return (d.get('title', ''), (d.get('release_date') or '')[:4])
        if find.get('tv_results'):
            d = find['tv_results'][0]
            return (d.get('name', ''), (d.get('first_air_date') or '')[:4])
        return ('', '')

    if media_type == 'tv':
        d = _get('{0}/tv/{1}'.format(API_BASE, tmdb_id), {'api_key': key})
        if not d:
            return ('', '')
        return (d.get('name', ''), (d.get('first_air_date') or '')[:4])
    d = _get('{0}/movie/{1}'.format(API_BASE, tmdb_id), {'api_key': key})
    if not d:
        return ('', '')
    return (d.get('title', ''), (d.get('release_date') or '')[:4])
