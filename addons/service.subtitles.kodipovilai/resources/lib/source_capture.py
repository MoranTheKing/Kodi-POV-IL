# Self-contained capture helper for "remember the source the user picked".
#
# Called from a tiny block injected into POV's sources.py (see
# pov_remember_source_patcher). Kept in its OWN module with NO relative imports
# so POV's process can import it by path. Writes one JSON record per media
# under our addon_data/source_memory/, and logs each step so capture can be
# diagnosed from the Kodi log.

import os
import json

try:
    import xbmc
    import xbmcvfs
except Exception:
    xbmc = None
    xbmcvfs = None


def _log(msg, level=1):
    try:
        xbmc.log('[remember_source] ' + msg, level)
    except Exception:
        pass


def _enabled():
    try:
        import xbmcaddon
        return (xbmcaddon.Addon('service.subtitles.kodipovilai')
                .getSetting('remember_source') or '').strip().lower() == 'true'
    except Exception:
        return False


def _key(sources_self):
    s = sources_self
    meta = getattr(s, 'meta', None) or {}
    media_id = str(getattr(s, 'tmdb_id', '') or meta.get('imdb_id') or '')
    media_type = getattr(s, 'media_type', '') or 'movie'
    if not media_id:
        return None
    season = getattr(s, 'season', '') or 0
    episode = getattr(s, 'episode', '') or 0
    return '{0}_{1}_s{2}_e{3}'.format(media_type, media_id, season, episode)


def _dir():
    return xbmcvfs.translatePath(
        'special://profile/addon_data/service.subtitles.kodipovilai/'
        'source_memory/')


def capture(sources_self, item):
    """Record the chosen source for the media POV is about to play.
    sources_self is POV's Sources instance; item is the picked source dict."""
    try:
        key = _key(sources_self)
        if not key:
            _log('no media id (tmdb/imdb) -- skip')
            return
        rec = {
            'name': item.get('name', ''),
            'hash': item.get('hash', ''),
            'quality': item.get('quality', ''),
            'provider': item.get('scrape_provider') or item.get('provider', ''),
            'debrid': item.get('debrid', ''),
            'release_title': item.get('release_title', ''),
        }
        d = _dir()
        if not os.path.isdir(d):
            os.makedirs(d)
        tmp = os.path.join(d, key + '.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(json.dumps(rec))
        os.replace(tmp, os.path.join(d, key + '.json'))
        _log('captured ' + key + ' -> ' + (rec['name'] or '?')[:50])
    except Exception as e:
        _log('capture error: ' + str(e), 3)


def _get_record(sources_self):
    key = _key(sources_self)
    if not key:
        return None
    path = os.path.join(_dir(), key + '.json')
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.loads(f.read())
    except (IOError, OSError, ValueError):
        return None


def _norm(x):
    return (x or '').strip().lower()


# Prefix put on the remembered source's display name so the user can spot it.
_MARK = '⭐ '  # star + space


def _match_index(results, rec):
    """Index in `results` of the source the user picked last time, or None.
    Exact match by source hash first; else a conservative similar match (same
    quality AND provider, cached only)."""
    rhash = _norm(rec.get('hash'))
    if rhash:
        for i, it in enumerate(results):
            if _norm(it.get('hash')) == rhash:
                return i
    rq = _norm(rec.get('quality'))
    rprov = _norm(rec.get('provider'))
    if rq and rprov:
        for i, it in enumerate(results):
            if 'Uncached' in (it.get('cache_provider') or ''):
                continue
            if (_norm(it.get('quality')) == rq
                    and _norm(it.get('scrape_provider')
                              or it.get('provider')) == rprov):
                return i
    return None


def reorder(sources_self, results):
    """Move the remembered source to the TOP of `results` and mark its display
    name, so the user can re-pick it in one click -- instead of auto-playing and
    skipping the dialog. Modifies `results` IN PLACE. Best-effort: on any error
    or no remembered match, leaves `results` untouched. Returns True if it
    reordered. Gated by the `remember_source` setting (same as capture)."""
    try:
        if not _enabled():
            return False
        rec = _get_record(sources_self)
        if not rec:
            _log('reorder: nothing remembered for this item')
            return False
        idx = _match_index(results, rec)
        if idx is None:
            _log('reorder: no confident match in current results')
            return False
        item = results.pop(idx)
        # Mark the displayed name (POV shows item['URLName'] as tikiskins.name).
        # The stored record reads item['name'], not URLName, so the marker never
        # pollutes the remembered record on a re-pick.
        try:
            nm = item.get('URLName') or ''
            if nm and not nm.startswith(_MARK):
                item['URLName'] = _MARK + nm
        except Exception:
            pass
        results.insert(0, item)
        _log('reorder: remembered source moved to top + marked')
        return True
    except Exception as e:
        _log('reorder error: ' + str(e), 3)
        return False


def autopick(sources_self, results):
    """Return the source item from `results` that matches the one the user
    picked for this media last time, so POV can play it and skip the dialog.
    Exact match by source hash; otherwise a conservative "similar" match (same
    quality AND same provider, cached only). Returns None to fall back to the
    normal source dialog (first watch, or no confident match)."""
    try:
        if not _enabled():
            return None
        # If a video is already playing, this display_results call is an
        # explicit "change source" mid-playback -> let the user pick (show the
        # dialog), and the new pick will be captured. Auto-pick only on a fresh
        # open / resume (player not yet playing).
        try:
            if xbmc is not None and xbmc.Player().isPlayingVideo():
                _log('autopick: video already playing (change-source) -> dialog')
                return None
        except Exception:
            pass
        rec = _get_record(sources_self)
        if not rec:
            _log('autopick: nothing remembered for this item -> dialog')
            return None
        rhash = _norm(rec.get('hash'))
        if rhash:
            for it in results:
                if _norm(it.get('hash')) == rhash:
                    _log('autopick: exact hash match -> auto-play')
                    return it
        rq = _norm(rec.get('quality'))
        rprov = _norm(rec.get('provider'))
        if rq and rprov:
            for it in results:
                if 'Uncached' in (it.get('cache_provider') or ''):
                    continue
                if _norm(it.get('quality')) == rq and _norm(
                        it.get('scrape_provider') or it.get('provider')) == rprov:
                    _log('autopick: similar (same quality+provider) -> auto-play')
                    return it
        _log('autopick: no confident match -> dialog')
        return None
    except Exception as e:
        _log('autopick error: ' + str(e), 3)
        return None

