# Resolve a TMDB v3 API key for cast / gender lookups. Two
# sources, in priority order:
#
#   1. The user's own key in script.module.tmdbhelper. Anyone who
#      hooked TMDB up through "חיבור שירותים" already has one
#      there; that key takes precedence both today and in the
#      future (if they connect a personal key tomorrow, we
#      switch to it immediately because we re-read every call).
#
#   2. A bundled fallback key, copied from jurialmunkey's
#      script.module.tmdbhelper upstream:
#        https://github.com/jurialmunkey/plugin.video.themoviedb.helper/
#                blob/nexus/resources/tmdbhelper/lib/api/api_keys/tmdb.py
#      That key is published in the open-source addon and is shared
#      by tens of thousands of tmdbhelper installs worldwide, so it
#      is appropriate to bundle as a default. With it, the user no
#      longer needs to do anything for TMDB beyond installing the
#      build -- gender-aware translation works out of the box.
#
# We never write the bundled key into tmdbhelper's settings, so
# user-facing TMDB integration is unchanged: tmdbhelper continues
# to behave exactly as before this addon was installed.

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

# Public TMDB v3 key shipped in jurialmunkey's tmdbhelper. Used
# only as a last-resort fallback when the user has not connected
# their own. See module docstring for source + rationale.
BUNDLED_TMDB_KEY = 'a07324c669cac4d96789197134ce272b'

API_BASE = 'https://api.themoviedb.org/3'


def _get_user_tmdb_key():
    """The user's personal TMDB v3 key from tmdbhelper, or '' if
    none configured. Never returns the bundled fallback."""
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


def _get_tmdb_key():
    """Resolve a usable TMDB v3 key. User key wins; bundled
    fallback ensures the addon works out of the box for everyone
    else. Called on every lookup, so a key the user adds tomorrow
    becomes effective immediately without restart."""
    user = _get_user_tmdb_key()
    if user:
        return user
    return BUNDLED_TMDB_KEY


def using_bundled_key():
    """True iff we'd fall back to the shipped key right now.
    Used by the settings UI to render an accurate status line."""
    return not _get_user_tmdb_key()


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
               season=None, episode=None, max_actors=25):
    """Look up a film or episode and return its main cast.

    Returns a list of dicts:
        [{'name': 'Charlie Day', 'character': 'Mabel',
          'gender': 'female', 'order': 0}, ...]

    Best-effort: missing pieces (no IMDB id, no TMDB key, etc.)
    return whatever we could resolve. Empty list on full failure.

    max_actors default raised from 12 -> 25 (Oct 2026): top-12 was
    missing scene-relevant minor characters (waiters, partners,
    one-scene parents) whose gender then defaulted in the model's
    inference and tripped up Hebrew verb / adjective agreement.
    25 covers virtually every named role without bloating the
    prompt (extra ~13 short lines, < 1 KB).
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
