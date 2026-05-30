# Self-healing patcher for plugin.video.pov/resources/lib/caches/
# trakt_cache.py's cache_trakt_object() so it doesn't cache empty
# results forever (yes, forever -- this cache has NO expiration).
#
# Companion to pov_cache_empty_patcher (which handles main_cache.py
# cache_object()). They patch two SEPARATE cache layers that POV
# uses for different purposes:
#
#   * cache_object()        -- main_cache.py / maincache.db
#                              TMDB lists, search results, recommendations,
#                              24-hour expiration
#
#   * cache_trakt_object()  -- trakt_cache.py  / trakt.db
#                              Trakt collection, watchlist, favorites,
#                              user lists. NO expiration -- stays cached
#                              until an explicit clear_trakt_*() call.
#
# Why this matters (real user report): after PR #187 patched
# main_cache.py, the user's "My Movies (TMDB)" tile worked. But the
# "My Movies (Trakt)" tile is STILL empty even after they confirmed
# items DO exist on trakt.tv. Root cause: a transient failure in
# trakt_fetch_collection_watchlist() / call_trakt() returned empty
# once, cache_trakt_object stored that empty in trakt.db as
# `trakt_collection_movie` (or `_tvshow`), and because there's no
# expiration it's there forever until POV's clear_trakt_collection_
# watchlist_data() runs. That clear happens on add/remove via
# trakt_manager_choice, but if the immediate re-read after the clear
# hits another transient failure -- back to stuck-empty.
#
# Fix: insert `if not result: return result` BEFORE the dbcur.execute
# (TC_BASE_SET, ...) line. Empty results are no longer persisted; the
# next read will retry. Also one-shot-clears any trakt_* rows already
# sitting in trakt.db so existing victims don't have to wait.
#
# Marker-gated, atomic write, idempotent.

import os
import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
TRAKT_CACHE_REL = 'resources/lib/caches/trakt_cache.py'

MARKER = '# AI_SUBS_POV_TRAKT_CACHE_EMPTY_v1'

# Match POV's TC_BASE_SET write line in cache_trakt_object:
#   <indent>dbcur.execute(TC_BASE_SET, (string, repr(result)))
# Tolerate tabs OR spaces. Single match expected in the file.
_INSERT_BEFORE_RE = re.compile(
    rb'^(?P<indent>[ \t]+)dbcur\.execute\(TC_BASE_SET,\s*'
    rb'\(string,\s*repr\(result\)\)\)',
    re.MULTILINE,
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log(
            'pov_trakt_cache_empty_patcher: ' + msg, level=level)
    except Exception:
        pass


def _trakt_cache_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, TRAKT_CACHE_REL)
    return p if os.path.isfile(p) else ''


def ensure_patched():
    """Idempotent. Returns one of:
    'no_pov' | 'no_file' | 'already_patched' | 'unmatched'
    | 'read_failed' | 'write_failed' | 'patched'."""
    path = _trakt_cache_path()
    if not path:
        return 'no_pov' if xbmcvfs is None else 'no_file'

    try:
        with open(path, 'rb') as f:
            content = f.read()
    except OSError as e:
        _log('read failed for {0}: {1}'.format(path, e),
             level='WARNING')
        return 'read_failed'

    if MARKER.encode('utf-8') in content:
        return 'already_patched'

    matches = list(_INSERT_BEFORE_RE.finditer(content))
    if len(matches) != 1:
        _log('expected exactly 1 dbcur.execute(TC_BASE_SET, ...) line '
             'in trakt_cache.py, got {0} -- POV may have refactored; '
             'leaving file alone'.format(len(matches)),
             level='WARNING')
        return 'unmatched'

    m = matches[0]
    indent = m.group('indent')
    insertion = (
        indent + MARKER.encode('utf-8') + b'\n'
        + indent + b'if not result: return result\n'
    )
    new_content = (
        content[:m.start()]
        + insertion
        + content[m.start():]
    )

    tmp_path = path + '.aitmp'
    try:
        with open(tmp_path, 'wb') as f:
            f.write(new_content)
        os.replace(tmp_path, path)
    except OSError as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        _log('write failed for {0}: {1}'.format(path, e),
             level='WARNING')
        return 'write_failed'

    # Drop stale .pyc so Python recompiles on next import.
    pycache_dir = os.path.join(
        os.path.dirname(path), '__pycache__')
    if os.path.isdir(pycache_dir):
        for fn in os.listdir(pycache_dir):
            if fn.startswith('trakt_cache.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache_dir, fn))
                except OSError:
                    pass

    _log('patched cache_trakt_object to skip empty results (no more '
         'permanent stuck-empty Trakt list bug)', level='INFO')

    # ONE-SHOT clear any trakt_collection_*, trakt_watchlist_*,
    # trakt_favorites_*, trakt_user_lists rows already sitting empty
    # in trakt.db. Best-effort; failure here is non-fatal.
    _clear_empty_trakt_rows()

    return 'patched'


def _clear_empty_trakt_rows():
    """Wipe stale list cache rows from POV's trakt.db. The patched
    cache_trakt_object will refuse to re-cache them as empty going
    forward; this just unblocks the user from the indefinite stuck-
    empty state."""
    if xbmcvfs is None:
        return
    try:
        db_path = xbmcvfs.translatePath(
            'special://profile/addon_data/' + POV_ADDON_ID
            + '/trakt.db')
    except Exception:
        return
    if not os.path.isfile(db_path):
        return
    try:
        import sqlite3
        conn = sqlite3.connect(db_path, isolation_level=None)
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM trakt_data WHERE id LIKE 'trakt_collection_%' "
            "OR id LIKE 'trakt_watchlist_%' "
            "OR id LIKE 'trakt_favorites_%' "
            "OR id LIKE 'trakt_user_lists%' "
            "OR id LIKE 'trakt_lists_%'"
        )
        deleted = cur.rowcount
        cur.close()
        conn.close()
        if deleted:
            _log('cleared {0} stale Trakt list cache row(s)'.format(
                deleted), level='INFO')
    except Exception as e:
        _log('could not clear stale rows: {0}'.format(e),
             level='WARNING')
