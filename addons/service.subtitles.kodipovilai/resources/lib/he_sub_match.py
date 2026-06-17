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

import re
import time
import json

try:
    import urllib.request as _req
    import urllib.parse as _parse
except Exception:
    _req = None
    _parse = None

POOL_URL = 'https://povil-subs-pool.moran200333.workers.dev'
_UA = 'KodiPOVIL-AISubs/he-match'
_ADDON_ID = 'service.subtitles.kodipovilai'

_CACHE = {}            # media_key -> (ts, [release names])
_TTL = 300.0           # seconds; POV's interpreter persists so this survives
_TIMEOUT = 2.5


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


def release_names(meta):
    """Return the release names of Hebrew subtitles available for this media
    (community pool). Cached per media. [] when disabled / unknown / on error
    -- so the caller simply shows no match prefix."""
    try:
        if not _enabled() or _req is None:
            return []
        p = _media_params(meta)
        if not p:
            return []
        key = _media_key(p)
        hit = _CACHE.get(key)
        now = time.time()
        if hit and (now - hit[0]) < _TTL:
            return hit[1]
        q = _parse.urlencode({k: v for k, v in p.items() if v})
        req = _req.Request(POOL_URL + '/lookup?' + q,
                           headers={'user-agent': _UA})
        raw = _req.urlopen(req, timeout=_TIMEOUT).read().decode('utf-8')
        data = json.loads(raw)
        names = []
        if data.get('ok'):
            for v in (data.get('variants') or []):
                rel = (v.get('release') or '').strip()
                if rel:
                    names.append(rel)
        _CACHE[key] = (now, names)
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
    """A small coloured '<NN>% עברית | ' prefix for the source's info line, or
    '' when there's no usable match. Colour: green high / amber mid / red low."""
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
        return '[COLOR {0}]{1}% עברית[/COLOR] | '.format(color, best)
    except Exception:
        return ''
