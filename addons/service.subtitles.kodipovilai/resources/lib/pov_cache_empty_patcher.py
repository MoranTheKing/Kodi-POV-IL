# Self-healing patcher for plugin.video.pov/resources/lib/caches/
# main_cache.py's cache_object() so it doesn't cache empty results
# for 24 hours.
#
# Why this exists:
#
# POV's cache_object() is the universal wrapper around expensive API
# calls (TMDB lists, Trakt lists, recommendations, search, etc.). Its
# loop is:
#   1. ask the cache; if hit, return cached value
#   2. otherwise call the API function
#   3. write the result into the cache for `expiration` hours
#      (default 24)
#   4. return the result
#
# The functions it wraps (e.g. _get_tmdblist_paginated_list) follow
# a defensive "return [] on any exception" pattern. So when the API
# call fails -- transient network blip, expired auth, server hiccup
# -- the wrapper hands back an empty list. cache_object then
# faithfully caches THAT EMPTY LIST for 24 hours.
#
# End-user symptom (real user report): the user adds a movie to
# their TMDB favorites via the in-app context menu, sees POV's
# success notification, navigates to the "My Movies (TMDB)" home
# tile, and the list shows "No results". Verifying on
# themoviedb.org confirms the movie IS in their TMDB favorites --
# the write went through, but POV's read returns the stale empty
# cache for 24 hours. clear_tmdbl_cache() is supposed to clear the
# tmdblist_* rows but the next read can hit a transient failure
# (or any other reason `result` ends up empty) and immediately
# re-cache the empty result.
#
# Fix: insert `if not result: return result` just before the
# `maincache.set(...)` line. Empty results are no longer persisted;
# the next read will retry the API instead of returning the stuck
# empty for 24 hours.
#
# Trade-off: if the API legitimately returns empty (e.g. user truly
# has no favorites), the read will hit the API on every tile open
# instead of caching the empty. That's a minor cost compared to the
# "stuck empty for 24h" failure mode; users with empty lists won't
# open them repeatedly anyway.
#
# Marker-gated, idempotent, atomic write. Quiet on no-op (already
# patched or POV not installed). Logs WARNING if the source shape
# doesn't match (defends against POV refactor).

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
MAIN_CACHE_REL = 'resources/lib/caches/main_cache.py'

# Sticky marker so we know we've touched the file. Bumped if a
# future iteration of this patcher needs to re-run.
MARKER = '# AI_SUBS_POV_CACHE_EMPTY_v1'

# The exact line we INSERT BEFORE (`maincache.set(...)`) -- a
# regex that tolerates either tabs or spaces for indentation since
# POV uses tabs but we want to be safe against accidental retab.
_INSERT_BEFORE_RE = re.compile(
    rb'^(?P<indent>[ \t]+)maincache\.set\(string,\s*result,\s*expiration\)',
    re.MULTILINE,
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log(
            'pov_cache_empty_patcher: ' + msg, level=level)
    except Exception:
        pass


def _main_cache_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, MAIN_CACHE_REL)
    return p if os.path.isfile(p) else ''


def ensure_patched():
    """Idempotent. Returns one of:
    'no_pov' | 'no_file' | 'already_patched' | 'unmatched'
    | 'read_failed' | 'write_failed' | 'patched'."""
    path = _main_cache_path()
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
        _log('expected exactly 1 maincache.set(string, result, '
             'expiration) line in main_cache.py, got {0} -- POV may '
             'have refactored; leaving file alone'.format(len(matches)),
             level='WARNING')
        return 'unmatched'

    m = matches[0]
    indent = m.group('indent')
    # Skip-cache-on-empty + marker comment, prepended at the same
    # indent as the original maincache.set line. Preserving the
    # original line below so all other cache behaviour is unchanged.
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

    # Drop any stale .pyc for main_cache so Python recompiles on
    # next import. Otherwise the cached bytecode keeps the unpatched
    # behaviour around until manual restart.
    pycache_dir = os.path.join(
        os.path.dirname(path), '__pycache__')
    if os.path.isdir(pycache_dir):
        for fn in os.listdir(pycache_dir):
            if fn.startswith('main_cache.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache_dir, fn))
                except OSError:
                    pass

    _log('patched cache_object to skip empty results (no more '
         '24-hour stuck-empty TMDB/Trakt list bug)', level='INFO')

    # ONE-SHOT: also clear any already-cached empty TMDB list rows
    # in maincache.db so the user doesn't have to wait for them to
    # expire naturally. Best-effort; failure here is non-fatal.
    _clear_empty_tmdblist_rows()

    return 'patched'


def _clear_empty_tmdblist_rows():
    """Wipe any tmdblist_* rows currently sitting in POV's
    maincache.db. The patched cache_object will refuse to re-cache
    them as empty going forward; this just unblocks the user from
    waiting up to 24h for the existing stuck rows to expire."""
    if xbmcvfs is None:
        return
    try:
        db_path = xbmcvfs.translatePath(
            'special://profile/addon_data/' + POV_ADDON_ID
            + '/maincache.db')
    except Exception:
        return
    if not os.path.isfile(db_path):
        return
    try:
        import sqlite3
        conn = sqlite3.connect(db_path, isolation_level=None)
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM maincache WHERE id LIKE 'tmdblist_%' "
            "OR id LIKE 'trakt_%'"
        )
        deleted = cur.rowcount
        cur.close()
        conn.close()
        if deleted:
            _log('cleared {0} stale list cache row(s)'.format(deleted),
                 level='INFO')
    except Exception as e:
        _log('could not clear stale rows: {0}'.format(e),
             level='WARNING')
