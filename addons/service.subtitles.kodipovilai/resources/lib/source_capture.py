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


def capture(sources_self, item):
    """Record the chosen source for the media POV is about to play.
    sources_self is POV's Sources instance; item is the picked source dict."""
    try:
        s = sources_self
        meta = getattr(s, 'meta', None) or {}
        media_id = str(getattr(s, 'tmdb_id', '') or meta.get('imdb_id') or '')
        media_type = getattr(s, 'media_type', '') or 'movie'
        if not media_id:
            _log('no media id (tmdb/imdb) -- skip')
            return
        season = getattr(s, 'season', '') or 0
        episode = getattr(s, 'episode', '') or 0
        key = '{0}_{1}_s{2}_e{3}'.format(media_type, media_id, season, episode)
        rec = {
            'name': item.get('name', ''),
            'hash': item.get('hash', ''),
            'quality': item.get('quality', ''),
            'provider': item.get('scrape_provider') or item.get('provider', ''),
            'debrid': item.get('debrid', ''),
            'release_title': item.get('release_title', ''),
        }
        d = xbmcvfs.translatePath(
            'special://profile/addon_data/service.subtitles.kodipovilai/'
            'source_memory/')
        if not os.path.isdir(d):
            os.makedirs(d)
        tmp = os.path.join(d, key + '.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(json.dumps(rec))
        os.replace(tmp, os.path.join(d, key + '.json'))
        _log('captured ' + key + ' -> ' + (rec['name'] or '?')[:50])
    except Exception as e:
        _log('capture error: ' + str(e), 3)
