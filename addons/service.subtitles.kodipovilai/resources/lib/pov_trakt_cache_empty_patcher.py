# Self-healing patcher for plugin.video.pov's caches/trakt_cache.py
# cache_trakt_object(). It fixes TWO separate POV bugs, each behind its own
# marker so they apply independently and idempotently:
#
#  A) MISSING TABLE -> hard crash (real user report, screenshot):
#       sqlite3.OperationalError: no such table: trakt_data
#     at `dbcur.execute(TC_BASE_GET, (string,))`. Root cause is a POV bug:
#     the `trakt_data` table is used (SELECT/INSERT/DELETE) but is NEVER
#     created by any CREATE TABLE in POV's code. POV's check_databases()
#     maps traktcache.db to the *watched* schema (watched_status + progress
#     only), and integrity_check() "repairs" a bad DB by truncating the file
#     and recreating just those -- so once traktcache.db is fresh/repaired/
#     partially wiped, `trakt_data` is gone for good and EVERY Trakt manager
#     / Trakt list click crashes. (Installs whose DB still carries the table
#     from an older POV keep working, which is why it hits only some users.)
#     Fix: inject `CREATE TABLE IF NOT EXISTS trakt_data (id TEXT UNIQUE,
#     data TEXT)` right after the cursor is obtained, before the first query.
#
#  B) EMPTY RESULTS CACHED FOREVER (this cache has NO expiration):
#     a transient call_trakt() failure returns empty once, gets stored, and
#     sticks until an explicit clear -> "My Movies/Shows (Trakt)" stays empty.
#     Fix: `if not result: return result` before the INSERT, so empties are
#     never persisted and the next read retries. Also one-shot-clears any
#     trakt_* list rows already sitting empty in traktcache.db.
#
# Marker-gated, atomic write, compile()-checked before writing, idempotent,
# .pyc invalidated. Safe no-op if POV isn't installed or the anchors moved.

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
TRAKT_CACHE_REL = 'resources/lib/caches/trakt_cache.py'
# POV 6.07 names the on-disk DB traktcache.db (kodi_utils.trakt_db).
TRAKT_DB_NAME = 'traktcache.db'
TRAKT_DATA_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS trakt_data (id TEXT UNIQUE, data TEXT)")

MARKER_TABLE = '# AI_SUBS_POV_TRAKT_TABLE_v1'
MARKER_EMPTY = '# AI_SUBS_POV_TRAKT_CACHE_EMPTY_v1'

# Bug A anchor: the line that gets the cursor at the top of cache_trakt_object.
#   <indent>dbcur = TraktCache().dbcur
_CURSOR_ANCHOR = 'dbcur = TraktCache().dbcur'
# Bug B anchor: the INSERT (write) line.
_SET_ANCHOR = 'dbcur.execute(TC_BASE_SET, (string, repr(result)))'


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


def _indent_of(line):
    return line[:len(line) - len(line.lstrip(' \t'))]


def ensure_patched():
    """Idempotent. Returns one of:
    'no_pov' | 'no_file' | 'already_patched' | 'unmatched'
    | 'read_failed' | 'compile_failed' | 'write_failed' | 'patched'."""
    path = _trakt_cache_path()
    if not path:
        return 'no_pov' if xbmcvfs is None else 'no_file'

    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed for {0}: {1}'.format(path, e), level='WARNING')
        return 'read_failed'

    if MARKER_TABLE in content and MARKER_EMPTY in content:
        # Table healer still runs even when the file is fully patched: the DB
        # can be wiped after POV's process started this session.
        _ensure_trakt_data_table()
        return 'already_patched'

    lines = content.splitlines(keepends=True)
    out = []
    applied = []
    for line in lines:
        stripped = line.strip()
        # Bug A: create the table right after the cursor is obtained.
        if stripped == _CURSOR_ANCHOR and MARKER_TABLE not in content:
            ind = _indent_of(line)
            out.append(line)
            out.append(ind + MARKER_TABLE + '\n')
            out.append(ind + "dbcur.execute('" + TRAKT_DATA_SCHEMA + "')\n")
            applied.append('table')
            continue
        # Bug B: don't persist empty results (inject before the INSERT).
        if stripped == _SET_ANCHOR and MARKER_EMPTY not in content:
            ind = _indent_of(line)
            out.append(ind + MARKER_EMPTY + '\n')
            out.append(ind + 'if not result: return result\n')
            out.append(line)
            applied.append('empty')
            continue
        out.append(line)

    if not applied:
        _log('no cache_trakt_object anchors matched -- POV may have '
             'refactored; leaving file alone', level='WARNING')
        # Still try to heal the DB table externally (covers the crash even if
        # the in-code anchor moved).
        _ensure_trakt_data_table()
        return 'unmatched'

    new_content = ''.join(out)

    # SAFETY: never write a file that doesn't compile.
    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('patched content would not compile -- skipping ({0})'.format(e),
             level='WARNING')
        return 'compile_failed'

    tmp_path = path + '.aitmp'
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp_path, path)
    except OSError as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        _log('write failed for {0}: {1}'.format(path, e), level='WARNING')
        return 'write_failed'

    # Drop stale .pyc so Python recompiles on next import.
    pycache_dir = os.path.join(os.path.dirname(path), '__pycache__')
    if os.path.isdir(pycache_dir):
        for fn in os.listdir(pycache_dir):
            if fn.startswith('trakt_cache.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache_dir, fn))
                except OSError:
                    pass

    _log('patched cache_trakt_object ({0})'.format(', '.join(applied)),
         level='INFO')

    # Heal the on-disk DB now too: create the missing table and clear any
    # stale empty list rows so existing victims are unblocked immediately.
    _ensure_trakt_data_table()
    _clear_empty_trakt_rows()

    return 'patched'


def _trakt_db_path():
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath(
            'special://profile/addon_data/' + POV_ADDON_ID
            + '/' + TRAKT_DB_NAME)
    except Exception:
        return ''


def _ensure_trakt_data_table():
    """Create the trakt_data table in POV's traktcache.db if it is missing.
    Best-effort; only touches an existing DB file (POV creates the file on its
    own -- we don't want to race its schema init on a brand-new install; the
    in-code CREATE TABLE IF NOT EXISTS covers fresh installs)."""
    db_path = _trakt_db_path()
    if not db_path or not os.path.isfile(db_path):
        return
    try:
        import sqlite3
        conn = sqlite3.connect(db_path, timeout=5, isolation_level=None)
        try:
            conn.execute(TRAKT_DATA_SCHEMA)
        finally:
            conn.close()
    except Exception as e:
        _log('could not ensure trakt_data table: {0}'.format(e),
             level='WARNING')


def _clear_empty_trakt_rows():
    """Wipe stale empty list cache rows from POV's traktcache.db so existing
    victims don't wait for an explicit clear. The patched cache_trakt_object
    refuses to re-cache empties going forward. Best-effort."""
    db_path = _trakt_db_path()
    if not db_path or not os.path.isfile(db_path):
        return
    try:
        import sqlite3
        conn = sqlite3.connect(db_path, timeout=5, isolation_level=None)
        cur = conn.cursor()
        try:
            cur.execute(TRAKT_DATA_SCHEMA)
            cur.execute(
                "DELETE FROM trakt_data WHERE id LIKE 'trakt_collection_%' "
                "OR id LIKE 'trakt_watchlist_%' "
                "OR id LIKE 'trakt_favorites_%' "
                "OR id LIKE 'trakt_user_lists%' "
                "OR id LIKE 'trakt_lists_%'"
            )
            deleted = cur.rowcount
        finally:
            cur.close()
            conn.close()
        if deleted:
            _log('cleared {0} stale Trakt list cache row(s)'.format(deleted),
                 level='INFO')
    except Exception as e:
        _log('could not clear stale rows: {0}'.format(e), level='WARNING')
