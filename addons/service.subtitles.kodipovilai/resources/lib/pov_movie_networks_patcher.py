# Fix POV's "movies by streaming service" tiles (Netflix / Disney+ / Apple TV+
# under the Movies hub) so they actually return that service's movies.
#
# The build's home tiles pass a TMDB *watch-provider* id (Netflix=8,
# Disney+=337, Apple TV+=350) to action=tmdb_movies_networks. But POV's
# indexers/tmdb_api.py tmdb_movies_networks() applies that id as
# `with_companies=<id>` -- a PRODUCTION-COMPANY filter -- so e.g. Netflix's
# provider id 8 is treated as company 8 (not Netflix), returning wrong/empty
# results. (TV works because tmdb_tv_networks correctly uses with_networks.)
#
# Fix: rewrite that one query to use TMDB's watch-provider discovery
# (with_watch_providers + watch_region + flatrate), which is what "movies on
# <service>" actually means. One exact-string swap; the id passed by the tiles
# is already the right (provider) id, so nothing else changes.
#
# Marker-gated, compile()-checked, atomic, .pyc dropped. Safe no-op if POV
# isn't installed or the line changed upstream.

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
MARKER = '# AI_SUBS_POV_MOVIE_PROVIDERS_v1'

_OLD = ("&sort_by=popularity.desc&certification_country=US"
        "&with_companies=%s' % network_id")
_NEW = ("&sort_by=popularity.desc&watch_region=US&with_watch_providers=%s"
        "&with_watch_monetization_types=flatrate' % network_id")


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
    """Returns 'patched' | 'already_patched' | 'no_pov' | 'no_file'
    | 'unmatched' | 'compile_failed' | 'read_failed' | 'write_failed'."""
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
    if _OLD not in content:
        _log('movie-networks line not found -- POV may have changed it; '
             'leaving alone', level='WARNING')
        return 'unmatched'

    new_content = content.replace(_OLD, _NEW, 1)
    # Stamp the marker on its own line right after the first newline.
    new_content = new_content.replace('\n', '\n' + MARKER + '\n', 1)

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

    _log('movie streaming-service tiles now use watch-providers', level='INFO')
    return 'patched'
