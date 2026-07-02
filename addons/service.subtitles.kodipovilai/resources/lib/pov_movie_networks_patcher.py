# Revert POV's "movies by streaming service" query back to stock.
#
# 0.2.305 rewrote tmdb_movies_networks() in resources/lib/indexers/tmdb_api.py
# from POV's stock `with_companies=%s` to a TMDB watch-provider discovery query
# (with_watch_providers + watch_region + flatrate), so the Netflix/Disney/Apple
# movie tiles would return that service's movies. In practice that tile then
# hung ("spins forever, returns nothing") on real devices, while every other
# movie list kept working -- so the watch-provider query is the regression.
#
# Until the provider query can be made to work reliably, this restores POV's
# stock line so the tile behaves exactly as it did before 0.2.305 (returns a
# result instead of hanging). Fresh/stock installs already have the stock line,
# so they're left untouched.
#
# Marker-gated, compile()-checked, atomic, .pyc dropped. Safe no-op if POV
# isn't installed or the line was changed by something else.

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
TMDB_API_REL = 'resources/lib/indexers/tmdb_api.py'
MARKER = '# AI_SUBS_POV_MOVIE_PROVIDERS_REVERT_v1'
# The now-superseded forward-patch marker, stripped on revert.
OLD_FWD_MARKER = '# AI_SUBS_POV_MOVIE_PROVIDERS_v1'

# What 0.2.305 wrote (the hanging query) -> restore POV's stock query.
_PATCHED = ("&sort_by=popularity.desc&watch_region=US&with_watch_providers=%s"
            "&with_watch_monetization_types=flatrate' % network_id")
_STOCK = ("&sort_by=popularity.desc&certification_country=US"
          "&with_companies=%s' % network_id")


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_movie_networks_patcher: ' + msg, level=level)
    except Exception:
        pass


def _tmdb_api_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, *TMDB_API_REL.split('/'))
    return p if os.path.isfile(p) else ''


def ensure_patched():
    """Restore POV's stock movie-networks query. Returns
    'patched' (reverted) | 'already_patched' | 'already_stock' | 'no_pov'
    | 'no_file' | 'unmatched' | 'compile_failed' | 'read_failed'
    | 'write_failed'."""
    path = _tmdb_api_path()
    if not path:
        return 'no_pov' if xbmcvfs is None else 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'already_patched'
    if _PATCHED not in content:
        # Nothing to revert. Stock line present -> leave as-is (no write);
        # neither present -> POV changed it, leave alone.
        return 'already_stock' if _STOCK in content else 'unmatched'

    new_content = content.replace(_PATCHED, _STOCK, 1)
    # Strip the superseded forward-patch marker line (best-effort).
    new_content = new_content.replace(OLD_FWD_MARKER + '\n', '')
    # Stamp the revert marker on its own line right after the first newline.
    new_content = new_content.replace('\n', '\n' + MARKER + '\n', 1)

    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('reverted content would not compile -- skipping ({0})'.format(e),
             level='WARNING')
        return 'compile_failed'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'

    pycache_dir = os.path.join(os.path.dirname(path), '__pycache__')
    if os.path.isdir(pycache_dir):
        for fn in os.listdir(pycache_dir):
            if fn.startswith('tmdb_api.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache_dir, fn))
                except OSError:
                    pass

    _log('movie streaming-service query reverted to stock (un-hang)',
         level='INFO')
    return 'patched'
