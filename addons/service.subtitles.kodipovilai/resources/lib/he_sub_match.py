# Hebrew-subtitle match score for POV's source-results window.
#
# Shows, under each source (before you pick it), how well an available Hebrew
# subtitle's release name matches that source's release -- i.e. how likely a
# ready Hebrew sub will sync to it. Computed against the community pool (AI +
# manual uploads). Cosmetic/advisory only.
#
# Self-contained on purpose: POV imports this by path from its own interpreter
# (like source_capture), so NO relative/package imports -- we do the pool
# /lookup over plain urllib here instead of importing pool.py. Every entry
# point is fully guarded; any failure yields an empty prefix so POV's source
# list is never affected.

import os
import re
import time
import json
import base64

try:
    import urllib.request as _req
    import urllib.parse as _parse
except Exception:
    _req = None
    _parse = None

POOL_URL = 'https://povil-subs-pool.moran200333.workers.dev'
_UA = 'KodiPOVIL-AISubs/he-match'
_ADDON_ID = 'service.subtitles.kodipovilai'

_CACHE = {}            # media_key -> (ts, [pool+wizdom release names])
_TTL = 300.0           # seconds; POV's interpreter persists so this survives
_TIMEOUT = 2.5

# Engine (Ktuvit/...) availability is filled by a background RunScript into a
# shared cache file; we read it cheaply on every call so the badge fills in on
# the next source-window open without ever blocking POV.
_ENGINE_CACHE_FILE = (
    'special://profile/addon_data/service.subtitles.kodipovilai/'
    'he_avail_cache.json')
_ENGINE_TTL = 7 * 24 * 3600.0   # 7 days; Ktuvit availability changes slowly
_FIRED = {}            # media_key -> last warm-fire ts (throttle re-fires)
_FIRE_RETRY = 120.0    # re-fire a warm at most once every 2 min per title


def _enabled():
    try:
        import xbmcaddon
        v = (xbmcaddon.Addon(_ADDON_ID).getSetting('show_subtitle_match')
             or '').strip().lower()
        return v != 'false'   # default ON when unset
    except Exception:
        return True


def _media_params(meta):
    """Pull {tmdb,imdb,type,season,episode} out of POV's meta dict, defensively
    (only imdb_id/media_type/season/episode are guaranteed present)."""
    if not meta:
        return None
    g = meta.get
    imdb = str(g('imdb_id') or g('imdb') or '').strip()
    tmdb = str(g('tmdb_id') or g('tmdb') or '').strip()
    if not (imdb or tmdb):
        return None
    season = str(g('season') or g('custom_season') or '0').strip() or '0'
    episode = str(g('episode') or g('custom_episode') or '0').strip() or '0'
    mt = str(g('media_type') or '').strip().lower()
    is_ep = mt in ('episode', 'tvshow', 'tv', 'season') or (
        season not in ('', '0') and episode not in ('', '0'))
    return {
        'tmdb': tmdb, 'imdb': imdb,
        'type': 'episode' if is_ep else 'movie',
        'season': season if is_ep else '0',
        'episode': episode if is_ep else '0',
        'lang': 'he',
    }


def _media_key(p):
    return '{0}:{1}:{2}:{3}:{4}'.format(
        p['tmdb'] or p['imdb'], p['type'], p['season'], p['episode'], p['lang'])


WIZDOM_API_URL = 'https://wizdom.xyz/api/search?action=by_id'


def _pool_release_names(p):
    """Hebrew release names from the community pool."""
    try:
        q = _parse.urlencode({k: v for k, v in p.items() if v})
        req = _req.Request(POOL_URL + '/lookup?' + q,
                           headers={'user-agent': _UA})
        raw = _req.urlopen(req, timeout=_TIMEOUT).read().decode('utf-8')
        data = json.loads(raw)
        out = []
        if data.get('ok'):
            for v in (data.get('variants') or []):
                rel = (v.get('release') or '').strip()
                if rel:
                    out.append(rel)
        return out
    except Exception:
        return []


def _wizdom_release_names(p):
    """Hebrew release names from Wizdom's open API (no key, covers most
    content) -- so the source-screen % works even for titles that aren't in
    the community pool yet. Fully guarded."""
    try:
        imdb = (p.get('imdb') or '').strip()
        if not imdb.startswith('tt'):
            return []
        params = {'imdb': imdb}
        season = (p.get('season') or '').strip()
        episode = (p.get('episode') or '').strip()
        if p.get('type') == 'tv' or (season not in ('', '0')
                                     and episode not in ('', '0')):
            try:
                params['season'] = str(int(season or 0)).zfill(2)
                params['episode'] = str(int(episode or 0)).zfill(2)
            except Exception:
                pass
        req = _req.Request(
            WIZDOM_API_URL + '&' + _parse.urlencode(params),
            headers={'user-agent': _UA})
        raw = _req.urlopen(req, timeout=_TIMEOUT).read().decode('utf-8')
        data = json.loads(raw)
        out = []
        for item in (data or []):
            v = (item.get('versioname') or '').strip()
            if v:
                out.append(v)
        return out
    except Exception:
        return []


def _engine_cache_path():
    try:
        import xbmcvfs
        return xbmcvfs.translatePath(_ENGINE_CACHE_FILE)
    except Exception:
        return ''


def _engine_cached_names(key):
    """Hebrew release names the MoranSubs engine (Ktuvit) found for this media,
    or None when it has not been warmed yet / is stale -- the caller then fires
    a background warm. Pure file read; never networks."""
    try:
        path = _engine_cache_path()
        if not path or not os.path.isfile(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f) or {}
        ent = data.get(key)
        if not ent:
            return None
        if (time.time() - float(ent.get('ts', 0))) > _ENGINE_TTL:
            return None
        return [n for n in (ent.get('names') or []) if n]
    except Exception:
        return None


def _meta_str(meta, keys):
    for k in keys:
        v = meta.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ''


def _fire_engine_warm(key, p, meta):
    """Fire-and-forget RunScript so MoranSubs runs Ktuvit for this title in its
    own context and writes the result to the shared cache. Throttled per title
    so reopening the source window doesn't spam it. Non-blocking."""
    try:
        import xbmc
        now = time.time()
        if (now - _FIRED.get(key, 0)) < _FIRE_RETRY:
            return
        _FIRED[key] = now
        payload = {
            'mk': key,
            'imdb': p.get('imdb', ''),
            'tmdb': p.get('tmdb', ''),
            'type': p.get('type', 'movie'),
            'season': p.get('season', '0'),
            'episode': p.get('episode', '0'),
            'title': _meta_str(meta, ('title', 'originaltitle',
                                      'OriginalTitle', 'label', 'name')),
            'tvshow': _meta_str(meta, ('tvshowtitle', 'showtitle',
                                       'TVShowTitle')),
            'year': str((meta.get('year') if meta else '') or ''),
        }
        blob = base64.b64encode(
            json.dumps(payload).encode('utf-8')).decode('ascii')
        xbmc.executebuiltin(
            'RunScript(service.subtitles.kodipovilai,'
            'action=he_avail,data={0})'.format(blob))
    except Exception:
        pass


def release_names(meta):
    """Return the release names of Hebrew subtitles available for this media,
    from the community pool + Wizdom (synchronous) AND the MoranSubs engine /
    Ktuvit (background-warmed, read from a shared cache). Cached per media. []
    when disabled / unknown / on error -- so the caller shows no prefix."""
    try:
        if not _enabled() or _req is None:
            return []
        p = _media_params(meta)
        if not p:
            return []
        key = _media_key(p)
        now = time.time()
        # Pool + Wizdom: networked, so cache in-memory for 5 min.
        hit = _CACHE.get(key)
        if hit and (now - hit[0]) < _TTL:
            pw = hit[1]
        else:
            pw = []
            seen0 = set()
            for src in (_pool_release_names, _wizdom_release_names):
                for rel in src(p):
                    low = rel.lower()
                    if low not in seen0:
                        seen0.add(low)
                        pw.append(rel)
            _CACHE[key] = (now, pw)
        # Engine (Ktuvit): cheap disk read every call; warm in the background
        # when missing so the badge fills in on the next open (never blocks).
        eng = _engine_cached_names(key)
        if eng is None:
            # Not warmed yet: fire the background Ktuvit lookup and return NOW.
            # We must NOT block here -- this runs inside POV's source-results
            # build, so waiting froze the source list for several seconds. The
            # badge fills in the next time the list renders (cheap cache read).
            _fire_engine_warm(key, p, meta)
            eng = []
        names = list(pw)
        seen = set(n.lower() for n in names)
        for rel in eng:
            low = (rel or '').lower()
            if low and low not in seen:
                seen.add(low)
                names.append(rel)
        return names
    except Exception:
        return []


def _tokens(s):
    return set(t for t in re.split(r'[^a-z0-9]+', (s or '').lower()) if len(t) >= 2)


def _score(src_release, sub_release):
    """How much of the SUBTITLE's release is covered by the SOURCE's release
    (0-100). Using the subtitle as denominator means a sub whose release tags
    are all present in the source scores high -> likely a good sync."""
    a = _tokens(src_release)
    b = _tokens(sub_release)
    if not a or not b:
        return 0
    return int(round(100.0 * len(a & b) / len(b)))


def best_score(src_release, names):
    try:
        if not names or not src_release:
            return 0
        return max((_score(src_release, n) for n in names), default=0)
    except Exception:
        return 0


def label_prefix(src_release, names):
    """A small coloured 'HEB <NN>% | ' prefix for the START of the source's
    info line, or '' when there's no usable match. Colour: green high / amber
    mid / red low. Deliberately LTR-only (no Hebrew letters): a Hebrew word
    inline in the mostly-English info line triggers bidi reordering (it jumps
    to the end) and then gets clipped when the line is full. An LTR badge stays
    at the start and always shows, since the line truncates from the end."""
    try:
        best = best_score(src_release, names)
        if best <= 0:
            return ''
        if best >= 66:
            color = 'FF49C46A'
        elif best >= 33:
            color = 'FFE0B23C'
        else:
            color = 'FFD0594F'
        return '[COLOR {0}][B]HEB {1}%[/B][/COLOR] | '.format(color, best)
    except Exception:
        return ''
