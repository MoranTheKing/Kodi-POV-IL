# Self-healing patcher for plugin.video.pov/resources/lib/indexers/
# metadata.py so a TRANSIENT per-item metadata fetch failure doesn't
# poison a movie/show for 2 days.
#
# Third sibling to pov_cache_empty_patcher (main_cache.py / maincache.db)
# and pov_trakt_cache_empty_patcher (trakt_cache.py / trakt.db). Those
# two fix the LIST caches. This one fixes the PER-ITEM metadata cache
# (metacache.db) -- the one cache neither of them touches.
#
# Why this exists (real user report + on-device diagnostic):
#
# The user adds movies to favorites; the diagnostic proved the rows
# ARE saved (watched.db -> favorites, 3 movie rows with valid tmdb_ids)
# and TMDB/Trakt auth is fully valid. Yet BOTH the "My Movies (POV)"
# and "My Movies (TMDB)" tiles show 0 results, in BOTH skins -- while
# normal movie browsing renders fine.
#
# Root cause is in metadata.movie_meta / tvshow_meta:
#   1. The favorites list yields the 3 tmdb_ids; each is resolved via
#      a live movie_details() fetch (same path as any list).
#   2. movie_details has an aggressive 3.05s timeout. On ANY transient
#      failure (timeout, network blip, rate-limit) movie_meta builds
#      meta = {'blank_entry': True, ...} and -- critically --
#      metacache_set('movie', id_type, meta, EXPIRES_2_DAYS) PERSISTS
#      that blank_entry into metacache.db for 2 FULL DAYS.
#   3. menus/movies.py build_movie_content drops every item whose meta
#      has blank_entry (`if not meta or meta_get('blank_entry'): return`).
#   So once the 3 favorites each hit one transient failure, they stay
#   invisible for ~48h regardless of skin or tile source, because the
#   blank_entry is served from cache on every subsequent open. Normal
#   browsing shows different ids that weren't poisoned, so it looks
#   fine -- which is exactly the reported symptom.
#
# Fix: neutralize the two `metacache_set(..., EXPIRES_2_DAYS)` calls
# that persist blank_entry. A transient failure still drops the item
# for the CURRENT render, but nothing is cached, so the very next open
# re-fetches and the item appears. This mirrors the "if not result:
# return result" philosophy of the two sibling patchers: never persist
# a failure.
#
# Trade-off: a genuinely-dead tmdb_id (deleted from TMDB) will re-fetch
# on every open instead of being cached blank for 2 days. For favorite
# lists (a handful of items) this is negligible, and it's far better
# than silently hiding real favorites for 48h.
#
# Also one-shot-clears any rows already poisoned with blank_entry in
# metacache.db so existing victims (like this user's 3 movies) recover
# immediately instead of waiting up to 2 days.
#
# Marker-gated, idempotent, atomic write. Quiet on no-op. Logs WARNING
# if the source shape doesn't match (defends against a POV refactor).

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
METADATA_REL = 'resources/lib/indexers/metadata.py'

MARKER = '# AI_SUBS_POV_META_BLANK_v1'

# Match BOTH the movie and tvshow blank_entry cache-write lines:
#   <indent>metacache_set('movie',  id_type, meta, EXPIRES_2_DAYS)
#   <indent>metacache_set('tvshow', id_type, meta, EXPIRES_2_DAYS)
# Tolerate tabs OR spaces. Exactly 2 matches expected.
_BLANK_SET_RE = re.compile(
    rb"^(?P<indent>[ \t]+)metacache_set\("
    rb"(?P<mt>'movie'|'tvshow'), id_type, meta, EXPIRES_2_DAYS\)",
    re.MULTILINE,
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_meta_blank_patcher: ' + msg, level=level)
    except Exception:
        pass


def _metadata_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, METADATA_REL)
    return p if os.path.isfile(p) else ''


def ensure_patched():
    """Idempotent. Returns one of:
    'no_pov' | 'no_file' | 'already_patched' | 'unmatched'
    | 'read_failed' | 'write_failed' | 'patched'."""
    path = _metadata_path()
    if not path:
        return 'no_pov' if xbmcvfs is None else 'no_file'

    try:
        with open(path, 'rb') as f:
            content = f.read()
    except OSError as e:
        _log('read failed for {0}: {1}'.format(path, e), level='WARNING')
        return 'read_failed'

    if MARKER.encode('utf-8') in content:
        # Already patched in code; still make sure existing poisoned
        # rows are cleared (cheap, idempotent) before returning.
        _clear_blank_meta_rows()
        return 'already_patched'

    matches = list(_BLANK_SET_RE.finditer(content))
    if len(matches) != 2:
        _log('expected exactly 2 metacache_set(..., EXPIRES_2_DAYS) '
             'blank_entry lines in metadata.py, got {0} -- POV may have '
             'refactored; leaving file alone'.format(len(matches)),
             level='WARNING')
        return 'unmatched'

    def _repl(m):
        indent = m.group('indent')
        mt = m.group('mt')
        # Replace the persisting set() with a no-op + marker. The
        # surrounding block still `return meta`s the blank entry for
        # this render; we just refuse to CACHE it, so the next open
        # re-fetches instead of serving the stale blank for 2 days.
        return (
            indent + MARKER.encode('utf-8')
            + b' (' + mt + b'): do NOT persist transient blank_entry\n'
            + indent + b'pass'
        )

    new_content = _BLANK_SET_RE.sub(_repl, content)

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
        _log('write failed for {0}: {1}'.format(path, e), level='WARNING')
        return 'write_failed'

    # Drop any stale .pyc so Python recompiles metadata.py on next
    # import; otherwise cached bytecode keeps the 2-day poison alive.
    pycache_dir = os.path.join(os.path.dirname(path), '__pycache__')
    if os.path.isdir(pycache_dir):
        for fn in os.listdir(pycache_dir):
            if fn.startswith('metadata.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache_dir, fn))
                except OSError:
                    pass

    _log('patched movie_meta/tvshow_meta to stop persisting transient '
         'blank_entry for 2 days (favorites no longer vanish on a single '
         'fetch hiccup)', level='INFO')

    # ONE-SHOT: clear any rows already poisoned with blank_entry so the
    # user's existing favorites recover now instead of waiting up to 2
    # days for the cache to expire. Best-effort; failure is non-fatal.
    _clear_blank_meta_rows()

    return 'patched'


def _clear_blank_meta_rows():
    """Delete any metacache.db metadata rows whose stored meta blob is
    a blank_entry. The `meta` column holds repr(dict); a poisoned row
    contains the literal substring blank_entry. The patched
    movie_meta/tvshow_meta won't re-cache these going forward; this
    just unblocks rows already stuck."""
    if xbmcvfs is None:
        return
    try:
        db_path = xbmcvfs.translatePath(
            'special://profile/addon_data/' + POV_ADDON_ID
            + '/metacache.db')
    except Exception:
        return
    if not os.path.isfile(db_path):
        return
    try:
        import sqlite3
        conn = sqlite3.connect(db_path, isolation_level=None)
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM metadata WHERE meta LIKE '%blank_entry%'")
        deleted = cur.rowcount
        cur.close()
        conn.close()
        if deleted:
            _log('cleared {0} poisoned blank_entry meta row(s)'.format(
                deleted), level='INFO')
    except Exception as e:
        _log('could not clear poisoned rows: {0}'.format(e),
             level='WARNING')
