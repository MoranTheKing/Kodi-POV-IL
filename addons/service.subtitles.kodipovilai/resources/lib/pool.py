# Community AI-subtitle pool client (Kodi POV IL).
#
# Talks to the Cloudflare Worker that fronts the Telegram channel + KV index.
# Lets the add-on PULL Hebrew translations other users already made and PUSH
# the ones it makes. Everything here is best-effort and gated by two settings
# (pool_use / pool_share, both OFF by default): any failure degrades to "just
# translate locally", and the network calls never block playback.

import json
import os
import threading

from resources.lib import kodi_utils

try:
    import urllib.request as _urlreq
    import urllib.parse as _urlparse
except ImportError:        # pragma: no cover
    _urlreq = None
    _urlparse = None

POOL_URL = 'https://povil-subs-pool.moran200333.workers.dev'
POOL_API_KEY = 'povil_x8FayxrUOAS9Qew1sFWzO6UgAnEAgJAG'

# Cloudflare's browser-integrity check rejects plain urllib requests (HTTP
# 1010); a normal browser UA passes. Harmless for our own Worker.
_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')
_GET_TIMEOUT = 8
_POST_TIMEOUT = 25


def use_enabled():
    """Pull from the pool before translating? (default off)"""
    return kodi_utils.get_bool('pool_use', False)


def share_enabled():
    """Push fresh translations to the pool? (default off)"""
    return kodi_utils.get_bool('pool_share', False)


def _release_from(info):
    rel = (info.get('release') or info.get('filename') or '').strip()
    if rel:
        return rel
    fp = info.get('filepath') or ''
    base = os.path.basename(fp)
    if '.' in base:
        base = base.rsplit('.', 1)[0]
    return base


def _params(info):
    return {
        'tmdb': (info.get('tmdb_id') or '').strip(),
        'imdb': (info.get('imdb_id') or '').strip(),
        'type': 'episode' if info.get('is_episode') else 'movie',
        'season': str(info.get('season') or '0'),
        'episode': str(info.get('episode') or '0'),
        'lang': 'he',
    }


def _has_id(p):
    return bool(p.get('tmdb') or p.get('imdb'))


def _get(path, params):
    q = _urlparse.urlencode({k: v for k, v in params.items() if v})
    req = _urlreq.Request(POOL_URL + path + '?' + q, headers={'user-agent': _UA})
    with _urlreq.urlopen(req, timeout=_GET_TIMEOUT) as r:
        return r.read()


def lookup(info):
    """Return a list of available Hebrew variants for this media, or []."""
    if _urlreq is None:
        return []
    p = _params(info)
    if not _has_id(p):
        return []
    try:
        data = json.loads(_get('/lookup', p).decode('utf-8'))
        return (data.get('variants') or []) if data.get('ok') else []
    except Exception as e:
        kodi_utils.log('pool lookup failed: {0}'.format(e), level='DEBUG')
        return []


def fetch(info, source_hash=None):
    """Return the .srt text for the exact source_hash (or newest if None),
    or None. With a hash, the Worker 404s when that exact variant is absent."""
    if _urlreq is None:
        return None
    p = _params(info)
    if not _has_id(p):
        return None
    if source_hash:
        p['hash'] = source_hash
    try:
        return _get('/sub', p).decode('utf-8')
    except Exception as e:
        kodi_utils.log('pool fetch failed: {0}'.format(e), level='DEBUG')
        return None


def _post(body):
    try:
        req = _urlreq.Request(
            POOL_URL + '/contribute',
            data=json.dumps(body).encode('utf-8'),
            headers={'content-type': 'application/json',
                     'x-api-key': POOL_API_KEY, 'user-agent': _UA},
            method='POST')
        _urlreq.urlopen(req, timeout=_POST_TIMEOUT).read()
    except Exception as e:
        try:
            kodi_utils.log('pool contribute failed: {0}'.format(e), level='DEBUG')
        except Exception:
            pass


def contribute(info, source_hash, source_lang, srt_text):
    """Fire-and-forget: share a fresh Hebrew translation. Runs on a daemon
    thread so it never delays handing the subtitle back to the player."""
    if _urlreq is None or not srt_text:
        return
    p = _params(info)
    if not _has_id(p):
        return
    body = {
        'tmdb_id': p['tmdb'], 'imdb_id': p['imdb'], 'type': p['type'],
        'season': p['season'], 'episode': p['episode'], 'lang': 'he',
        'release': _release_from(info),
        'source_hash': source_hash or '',
        'source_lang': source_lang or 'en',
        'title': (info.get('title') or '').strip(),
        'year': str(info.get('year') or ''),
        'srt': srt_text,
    }
    try:
        threading.Thread(target=_post, args=(body,), daemon=True).start()
    except Exception:
        pass
