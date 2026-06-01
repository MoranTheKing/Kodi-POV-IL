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
TMDB_API_REL = 'resources/lib/indexers/tmdb_api.py'

MARKER = '# AI_SUBS_POV_META_BLANK_v2'

# v2 (the on-device log + watched.db proved why v1 didn't help this user):
#  - watched.db had 6 valid favorite rows, yet the POV-local favorites
#    list returned in 212ms with ZERO network calls and rendered empty.
#    That can only mean every one of those 6 ids was served from the
#    per-item meta cache (metacache.db) as a blank_entry and dropped at
#    menus/movies.py:57 -- the cache was poisoned and never cleared.
#  - v1 tied the one-shot blank-row purge to the SUCCESS of rewriting
#    metadata.py: the purge ran only on the 'patched'/'already_patched'
#    return paths. If the file rewrite path returned 'no_file' /
#    'unmatched' / a stale-marker mismatch, the purge was SKIPPED, so
#    the poisoned rows survived forever and the list stayed empty.
#  - The log showed pov_meta_blank_patcher never logged at all on the
#    user's device, i.e. the purge never ran.
# v2 fixes this by ALWAYS purging the poisoned rows first, unconditionally
# and on every startup (cheap DELETE), independent of the file-rewrite
# outcome -- and additionally widening tmdb_api's aggressive 3.05s
# per-item timeout (the root reason the fetch failed and got cached blank
# in the first place, especially on mobile/slow links) so the re-fetch
# actually succeeds and the posters fill in.

# tmdb_api.py ships `timeout = 3.05` at module level (verified: the only
# such assignment). 3.05s is too aggressive for per-item /movie/{id}
# detail calls on mobile; a single slow response -> blank_entry cached
# for 2 days. Widen to 15.05s. Marker via the value itself (idempotent:
# we only rewrite if the exact old literal is present).
_TMDB_TIMEOUT_OLD = b'\ntimeout = 3.05\n'
_TMDB_TIMEOUT_NEW = b'\ntimeout = 15.05  # AI_SUBS widened from 3.05 (mobile per-item fetch)\n'

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
    | 'read_failed' | 'write_failed' | 'patched'.

    v2: the poisoned-row purge and the tmdb timeout widening run
    UNCONDITIONALLY and FIRST, every startup, regardless of whether the
    metadata.py rewrite below matches. This is the actual fix for the
    user whose 6 valid favorites stayed invisible: v1 only purged on the
    rewrite-success paths, so a skipped/odd rewrite left the cache
    poisoned forever."""
    # (1) ALWAYS purge poisoned blank_entry rows first -- this is the
    # part that makes the user's existing 6 favorites reappear, and it
    # must not depend on anything else succeeding.
    _clear_blank_meta_rows()

    # (2) ALWAYS try to widen the aggressive per-item TMDB timeout so the
    # re-fetch succeeds instead of re-poisoning. Independent + idempotent.
    _widen_tmdb_timeout()

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

    # Note: the poisoned-row purge already ran unconditionally at the top
    # of ensure_patched (v2), so no need to repeat it here.
    return 'patched'


def _widen_tmdb_timeout():
    """Widen tmdb_api.py's module-level `timeout = 3.05` to 15.05s. The
    3.05s per-item /movie/{id} timeout is the root reason favorites get
    cached as blank_entry on mobile/slow links: one slow detail call ->
    movie_meta returns blank -> menus drop the item. Idempotent: only
    rewrites when the exact old literal is present; logs nothing if the
    file is missing or already widened. Drops stale .pyc on change."""
    if xbmcvfs is None:
        return
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return
    path = os.path.join(base, TMDB_API_REL)
    if not os.path.isfile(path):
        return
    try:
        with open(path, 'rb') as f:
            content = f.read()
    except OSError:
        return
    if _TMDB_TIMEOUT_NEW.strip() in content:
        return  # already widened
    if _TMDB_TIMEOUT_OLD not in content:
        return  # POV changed the line; leave it alone
    new_content = content.replace(_TMDB_TIMEOUT_OLD, _TMDB_TIMEOUT_NEW, 1)
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
        _log('tmdb timeout widen write failed: {0}'.format(e),
             level='WARNING')
        return
    pycache_dir = os.path.join(os.path.dirname(path), '__pycache__')
    if os.path.isdir(pycache_dir):
        for fn in os.listdir(pycache_dir):
            if fn.startswith('tmdb_api.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache_dir, fn))
                except OSError:
                    pass
    _log('widened tmdb_api per-item timeout 3.05s -> 15.05s (slow-link '
         'favorites no longer fail and cache blank)', level='INFO')


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
        _log('metacache.db not found; nothing to purge', level='INFO')
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
        # Always log (even 0) so we can confirm from kodi.log that the
        # purge actually ran on the device -- v1's silence is what hid
        # the fact that it was being skipped.
        _log('blank_entry purge ran: deleted {0} poisoned meta row(s)'
             .format(deleted), level='INFO')
    except Exception as e:
        _log('could not clear poisoned rows: {0}'.format(e),
             level='WARNING')
