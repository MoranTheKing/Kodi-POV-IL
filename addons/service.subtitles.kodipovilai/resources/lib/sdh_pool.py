# Phase 3b: share content-detected SDH releases via the community pool worker,
# so a subtitle ONE user content-detected as SDH (srt.is_sdh_content) can be
# preferred + labelled at ANOTHER user's ranking time -- before it's ever
# downloaded there. The local sdh_registry (Phase 3a) only knows what THIS user
# has downloaded; this widens it to the whole community.
#
# It rides the EXISTING pool transport/auth: pool.sign_headers() signs
# method+path+anon (NOT the body), so a new /sdh route authenticates exactly
# like /contribute -- and pool.py itself is left completely UNCHANGED (its
# protected community key is never read here, only its public helpers are).
#
# Purely a best-effort HINT: push is share-gated, pull is use-gated, everything
# fails open, and it is never authoritative -- the provider is_hi flag, a
# whole-token release marker, and the LOCAL registry all still decide first in
# _is_sdh_ext. is_shared_sdh() reads a LOCAL cache only (never the network), so
# it is safe to call on the ranking path; the cache is warmed out-of-band by
# refresh_shared_sdh() from the background service.

import json
import time

try:
    import urllib.request as _urlreq
except Exception:
    _urlreq = None

try:
    from resources.lib import pool
except Exception:
    pool = None

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None


_CACHE = ('special://profile/addon_data/service.subtitles.kodipovilai/'
          'sdh_shared.json')
_TTL = 86400.0            # refetch the shared set at most once/day
_POST_TIMEOUT = 8
_MAX_KEYS = 5000


def _translate(p):
    return xbmcvfs.translatePath(p) if xbmcvfs else p


def _now():
    try:
        return time.time()
    except Exception:
        return 0


def contribute_sdh(release):
    """Share a content-detected SDH release with the pool (share-gated,
    fire-and-forget, never raises)."""
    if pool is None or _urlreq is None:
        return
    try:
        if not pool.share_enabled():
            return
        rel = pool.worker_norm_release(release)
        if not rel or len(rel) > 200:
            return
        req = _urlreq.Request(
            pool.POOL_URL + '/sdh',
            data=json.dumps({'rel': rel}).encode('utf-8'),
            headers=pool._post_headers('/sdh'), method='POST')
        _urlreq.urlopen(req, timeout=_POST_TIMEOUT).read()
    except Exception:
        pass


def _load():
    if xbmcvfs is None:
        return {}
    try:
        p = _translate(_CACHE)
        if not xbmcvfs.exists(p):
            return {}
        with xbmcvfs.File(p) as f:
            raw = f.read()
        d = json.loads(raw) if raw else {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(obj):
    if xbmcvfs is None:
        return False
    try:
        tmp = _translate(_CACHE + '.tmp')
        f = xbmcvfs.File(tmp, 'w')
        try:
            ok = f.write(json.dumps(obj, ensure_ascii=False))
        finally:
            f.close()
        if not ok:
            return False
        dst = _translate(_CACHE)
        if xbmcvfs.rename(tmp, dst):
            return True
        xbmcvfs.delete(dst)
        return bool(xbmcvfs.rename(tmp, dst))
    except Exception:
        return False


def refresh_shared_sdh(force=False):
    """Fetch the shared SDH set into the LOCAL cache, at most once per _TTL.
    Call from a NON-ranking context (the background service) so the ranking path
    never blocks on the network. use-gated (only a user who pulls from the pool
    warms it). Returns True if the cache was refreshed. Never raises."""
    if pool is None:
        return False
    try:
        if not pool.use_enabled():
            return False
        cur = _load()
        if not force and (_now() - float(cur.get('at') or 0)) < _TTL:
            return False
        raw = pool._get('/sdh', {})
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode('utf-8', 'replace')
        data = json.loads(raw)
        keys = data.get('keys') if isinstance(data, dict) else None
        if not isinstance(keys, list):
            return False
        keys = [str(k) for k in keys if k][:_MAX_KEYS]
        return _save({'keys': keys, 'at': _now()})
    except Exception:
        return False


# tiny in-process memo so a burst of _is_sdh_ext calls in ONE ranking pass reads
# the cache file once, not per candidate.
_MEM = {'keys': None, 'at': 0}


def is_shared_sdh(key):
    """True iff `key`'s normalized release is in the cached shared SDH set. Reads
    the LOCAL cache ONLY -- never touches the network -- so it is safe on the
    ranking path. Empty/absent cache (e.g. pool-use off, or not yet warmed) ->
    False. Never raises."""
    if pool is None:
        return False
    try:
        k = pool.worker_norm_release(key)
        if not k:
            return False
        if _MEM['keys'] is None or (_now() - _MEM['at']) > 5:
            _MEM['keys'] = set(_load().get('keys') or [])
            _MEM['at'] = _now()
        return k in _MEM['keys']
    except Exception:
        return False
