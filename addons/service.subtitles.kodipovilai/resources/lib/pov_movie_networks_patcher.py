# Make POV's "movies by streaming service" query return the RIGHT movies.
#
# The Netflix/Disney/Apple movie tiles pass TMDB watch-PROVIDER ids
# (Netflix=8, Disney+=337, Apple TV+=350). POV's stock tmdb_movies_networks()
# applies them as `with_companies=%s` -- a production-company filter -- so
# `with_companies=8` returns ~44 random films (company 8 is NOT Netflix), not
# Netflix's catalogue. The correct TMDB query is watch-provider discovery:
# `with_watch_providers=<id>&watch_region=US&with_watch_monetization_types=flatrate`
# (verified: id 8 -> 4675 Netflix movies, 337 -> 1560 Disney movies).
#
# HISTORY / why this is safe now: 0.2.305 first tried exactly this query, it
# appeared to "hang forever", so 0.2.308 reverted it to `with_companies`. The
# hang was NOT the query -- it was a SEPARATE param-key bug: POV's native
# movies.py maps tmdb_movies_networks -> the 'company' key, so the tile's
# network_id was never read -> `if not function_var: return` exits run() before
# end_directory() -> infinite spinner. That key is now fixed to 'network_id'
# (pov_menus_patcher + pov_native_menus/movies.py), so the watch-provider query
# runs correctly and returns instantly. This patcher now FORWARD-patches the
# query (companies -> watch-providers) instead of reverting it.
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
MARKER = '# AI_SUBS_POV_MOVIE_PROVIDERS_v2'
# Superseded markers from the earlier forward-patch (v1) and the revert, both
# stripped when we re-apply the corrected forward patch.
OLD_MARKERS = ('# AI_SUBS_POV_MOVIE_PROVIDERS_v1',
               '# AI_SUBS_POV_MOVIE_PROVIDERS_REVERT_v1')

# TARGET = the correct watch-provider query; STOCK = POV's company filter.
_TARGET = ("&sort_by=popularity.desc&watch_region=US&with_watch_providers=%s"
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
    """Forward-patch POV's movie-networks query to watch-provider discovery.
    Returns 'patched' | 'already_patched' | 'already_stock'(nothing to change,
    POV line not found in either form) | 'no_pov' | 'no_file' | 'unmatched'
    | 'compile_failed' | 'read_failed' | 'write_failed'."""
    path = _tmdb_api_path()
    if not path:
        return 'no_pov' if xbmcvfs is None else 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    # Strip any superseded marker lines from a prior version so a re-apply is
    # clean (they may sit above an already-correct or a stock line).
    for _m in OLD_MARKERS:
        content = content.replace(_m + '\n', '')

    if MARKER in content and _TARGET in content:
        return 'already_patched'
    if _TARGET in content:
        # Query already correct but our marker was stripped above -> re-stamp.
        new_content = content.replace('\n', '\n' + MARKER + '\n', 1)
    elif _STOCK in content:
        new_content = content.replace(_STOCK, _TARGET, 1)
        new_content = new_content.replace('\n', '\n' + MARKER + '\n', 1)
    else:
        # POV changed the line to something we don't recognise -- leave alone.
        return 'unmatched'

    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('patched content would not compile -- skipping ({0})'.format(e),
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

    _log('movie streaming-service query set to watch-provider discovery',
         level='INFO')
    return 'patched'
