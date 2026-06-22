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

_TIMEOUT = 2.5

# Engine (OpenSubtitles) availability is filled by a background RunScript into a
# shared cache file; we read it cheaply on every call so the badge fills in on
# the next source-window open without ever blocking POV.
_ENGINE_CACHE_FILE = (
    'special://profile/addon_data/service.subtitles.kodipovilai/'
    'he_avail_cache.json')
_ENGINE_TTL = 7 * 24 * 3600.0   # 7 days; OpenSubtitles availability changes slowly
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


def _pool_lookup(p):
    """One /lookup call -> (hebrew release names, embedded-Hebrew release names).
    'embedded' is the set of releases the community has flagged as carrying a
    built-in (muxed) Hebrew track -- keyed by release name so it matches across
    debrid providers. Networked: only called from the background warm, never
    from the POV source window."""
    try:
        q = _parse.urlencode({k: v for k, v in p.items() if v})
        req = _req.Request(POOL_URL + '/lookup?' + q,
                           headers={'user-agent': _UA})
        raw = _req.urlopen(req, timeout=_TIMEOUT).read().decode('utf-8')
        data = json.loads(raw)
        names, embedded = [], []
        if data.get('ok'):
            for v in (data.get('variants') or []):
                rel = (v.get('release') or '').strip()
                if rel:
                    names.append(rel)
            for rel in (data.get('embedded') or []):
                rel = (rel or '').strip()
                if rel:
                    embedded.append(rel)
        return names, embedded
    except Exception:
        return [], []




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


def _cache_entry(key):
    """The shared he_avail cache entry for this media, or None when missing /
    stale. The background warm writes {ts, names, embedded}; this is a pure file
    read that NEVER networks (it runs inside POV's source-window build)."""
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
        return ent
    except Exception:
        return None


def _cached_names(key):
    """All available Hebrew release names from the warm cache (pool + Wizdom +
    OpenSubtitles + Ktuvit-fallback), or None when not warmed / stale."""
    ent = _cache_entry(key)
    if ent is None:
        return None
    return [n for n in (ent.get('names') or []) if n]


def _cached_embedded(key):
    """Release names flagged as carrying a built-in Hebrew track (from the warm
    cache). [] when none / not warmed."""
    ent = _cache_entry(key)
    if ent is None:
        return []
    return [n for n in (ent.get('embedded') or []) if n]


def _meta_str(meta, keys):
    for k in keys:
        v = meta.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ''


def _fire_engine_warm(key, p, meta):
    """Fire-and-forget RunScript so MoranSubs runs OpenSubtitles for this title in its
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


def availability(p):
    """NETWORKED -- runs ONLY in the background warm (MoranSubs's own process),
    never in POV's source window. Returns (hebrew release names, embedded-Hebrew
    release names) from the community pool + Wizdom. The warm adds OpenSubtitles
    / Ktuvit on top and writes the merged result to the shared cache."""
    names, embedded = [], []
    seen = set()
    try:
        pool_names, embedded = _pool_lookup(p)
    except Exception:
        pool_names, embedded = [], []
    try:
        wiz = _wizdom_release_names(p)
    except Exception:
        wiz = []
    for rel in list(pool_names) + list(wiz):
        low = (rel or '').strip().lower()
        if low and low not in seen:
            seen.add(low)
            names.append(rel)
    return names, embedded


def release_names(meta):
    """Hebrew-subtitle release names available for this media -- a PURE CACHE
    READ (pool + Wizdom + OpenSubtitles + Ktuvit-fallback, all written by the
    background warm). NEVER networks: this runs inside POV's source-results
    build, and the old synchronous pool/Wizdom calls froze the source list for
    several seconds. On a cache miss we fire the warm and return [] now; the
    badge fills in the next time the list renders (cheap disk read). [] when
    disabled / unknown."""
    try:
        if not _enabled():
            return []
        p = _media_params(meta)
        if not p:
            return []
        key = _media_key(p)
        names = _cached_names(key)
        if names is None:
            _fire_engine_warm(key, p, meta)   # warms pool+Wizdom+OS+Ktuvit
            return []
        return names
    except Exception:
        return []


def embedded_names(meta):
    """Release names flagged (by the community) as carrying a built-in Hebrew
    track, for THIS media. Pure cache read; [] when none / not warmed yet."""
    try:
        if not _enabled():
            return []
        p = _media_params(meta)
        if not p:
            return []
        return _cached_embedded(_media_key(p))
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


def label_prefix(src_release, names, embedded=None):
    """A small coloured prefix for the START of the source's info line, or ''
    when there's no usable match.

    If this source's release matches one the community flagged as carrying a
    BUILT-IN Hebrew track, it gets a distinct top-priority green badge
    ('HEB BUILT-IN 100%') so everyone knows it already has Hebrew and is well
    worth picking. Otherwise a normal 'HEB <NN>%' match badge: green high /
    amber mid / red low.

    Deliberately LTR-only (no Hebrew letters): a Hebrew word inline in the
    mostly-English info line triggers bidi reordering (it jumps to the end) and
    gets clipped when the line is full. An LTR badge stays at the start and
    always shows, since the line truncates from the end."""
    try:
        # Embedded Hebrew = best possible: it's already in the file. We treat a
        # high token overlap with a flagged release as a match (same scorer as
        # the % badge, threshold 80) so it survives small release-name diffs.
        if embedded and src_release:
            emb_best = best_score(src_release, embedded)
            if emb_best >= 80:
                return '[COLOR FF2ECC71][B]HEB BUILT-IN 100%[/B][/COLOR] | '
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
