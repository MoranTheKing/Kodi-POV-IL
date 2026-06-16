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


def _lookup_params_from_body(body):
    return {
        'tmdb': (body.get('tmdb_id') or '').strip(),
        'imdb': (body.get('imdb_id') or '').strip(),
        'type': body.get('type') or '',
        'season': str(body.get('season') or '0'),
        'episode': str(body.get('episode') or '0'),
        'lang': body.get('lang') or 'he',
    }


def _pool_has_hash(body, source_hash):
    """Cheap pre-check: is this exact source already in the pool? Reads the
    episode's variant list (each carries its source hash) and looks for a
    match. Lets the background uploader skip sending an SRT the server would
    only discard. Best-effort: any error returns False so we just upload."""
    if not source_hash:
        return False
    try:
        data = json.loads(
            _get('/lookup', _lookup_params_from_body(body)).decode('utf-8'))
        variants = (data.get('variants') or []) if data.get('ok') else []
        return any(v.get('hash') == source_hash for v in variants)
    except Exception:
        return False


def _post(body, marker_path=None):
    # Pre-check: if this exact source is already in the pool, skip the upload
    # entirely and just mark locally so we stop retrying. The server dedups by
    # source hash too, so this is purely to avoid sending an SRT that would be
    # discarded (and to suppress retries when another device already shared it).
    try:
        if _pool_has_hash(body, (body.get('source_hash') or '').strip()):
            if marker_path:
                mark_contributed(marker_path)
            return
    except Exception:
        pass
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
        return
    # Reached only on a successful POST: mark the file so we never re-upload
    # it. A failed upload leaves no marker, so it retries on the next watch.
    if marker_path:
        mark_contributed(marker_path)


def contribute(info, source_hash, source_lang, srt_text, marker_path=None):
    """Fire-and-forget: share a fresh Hebrew translation. Runs on a daemon
    thread so it never delays handing the subtitle back to the player. If
    marker_path is given, the thread writes a ".shared" marker there once the
    upload succeeds."""
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
        threading.Thread(target=_post, args=(body, marker_path),
                         daemon=True).start()
    except Exception:
        pass


# --- Duplicate-upload guard -------------------------------------------------
# Two layers protect against ever creating two identical subtitles in the pool:
#   1. SERVER: the Worker keys every variant by source_hash (the content hash
#      of the source SRT) and rejects a POST whose hash already exists for that
#      episode -- so a duplicate is impossible even if the client re-posts.
#   2. CLIENT: a tiny ".shared" sidecar next to each cached translation lets us
#      skip the network call entirely once we've contributed that file. The
#      marker lives in addon_data/cache, which a quick-update does NOT touch,
#      so it survives updates and we don't re-upload on every re-watch.
# The marker is only an optimisation; the server is the real guarantee.

def _marker_path(translated_path):
    return (translated_path + '.shared') if translated_path else None


def was_contributed(translated_path):
    m = _marker_path(translated_path)
    return bool(m and os.path.isfile(m))


def mark_contributed(translated_path):
    m = _marker_path(translated_path)
    if not m:
        return
    try:
        with open(m, 'w', encoding='utf-8') as f:
            f.write('1')
    except OSError:
        pass


def contribute_once(info, source_hash, source_lang, srt_text, marker_path=None):
    """contribute(), but skip the upload if this file was already shared (per
    the local marker). The marker is written by the POST thread ONLY after a
    successful upload, so a transient failure retries on the next watch rather
    than being silently dropped. Once marked, repeated watches / quick-updates
    never re-upload. Even if the marker is lost, the Worker dedups by
    source_hash, so duplicates are impossible."""
    if marker_path and was_contributed(marker_path):
        return
    contribute(info, source_hash, source_lang, srt_text,
               marker_path=marker_path)
