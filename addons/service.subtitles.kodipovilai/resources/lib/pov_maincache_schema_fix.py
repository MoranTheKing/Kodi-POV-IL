# "שגיאה: POV" the moment you open a search-history menu.
#
#     File "menus/history.py", line 27, in _builder
#       for query in contents:
#     TypeError: 'int' object is not iterable
#
# POV changed the column ORDER of its maincache table between 5.x and 6.x:
#
#     5.x  CREATE TABLE IF NOT EXISTS maincache (id text unique, data text, expires integer)
#     6.x  CREATE TABLE IF NOT EXISTS maincache (id TEXT UNIQUE, expires INTEGER, data TEXT)
#
# `IF NOT EXISTS` is the whole bug. On a device that already had the 5.x
# table, the 6.x statement does nothing and the OLD column order survives the
# upgrade -- while the 6.x code writes POSITIONALLY:
#
#     BASE_SET = 'INSERT OR REPLACE INTO maincache VALUES (?, ?, ?)'
#                self.dbcur.execute(BASE_SET, (string, int(expires), self.jsdumps(data)))
#
# so the timestamp lands in the `data` column and the JSON lands in `expires`.
# Because `data` has TEXT affinity SQLite converts the number to the string
# '1817981825', and `json.loads('1817981825')` hands back an int -- which is
# what `for query in contents` then tries to iterate. Reproduced exactly, from
# the two real schemas, before this was written.
#
# It also silently defeats expiry: `WHERE expires > ?` now compares the JSON
# TEXT against a number, and in SQLite TEXT always sorts above INTEGER, so
# every corrupted row reads back as "not expired" forever.
#
# Only rows WRITTEN by 6.x are damaged. Rows the old version wrote hold the
# right values in their own columns and still read back correctly, which is
# why this bites the moment a user runs their first search under 6.x and not
# before -- and why it hit several people at once after POV self-updated.
#
# This is POV's bug and the fix belongs in POV's own schema. We cannot ship
# POV, so we repair the table in place: rebuild it in the 6.x column order,
# copying every row BY COLUMN NAME so each value lands where it belongs, and
# dropping only the rows 6.x already corrupted -- identifiable because their
# `expires` holds text rather than an integer. Nothing salvageable is thrown
# away, and a cache row lost is a re-fetch, not data loss.
#
# Runs once per POV schema state, is a no-op on a correct table (which is
# every fresh install), and never raises.

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


MAINCACHE_DB = 'special://profile/addon_data/plugin.video.pov/maincache.db'

# The order POV 6.x writes positionally, and therefore the only order in
# which its own reads are correct.
WANTED_COLUMNS = ('id', 'expires', 'data')


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_maincache_schema_fix: ' + msg, level=level)
    except Exception:
        pass


def _db_path():
    if xbmcvfs is None:
        return ''
    try:
        p = xbmcvfs.translatePath(MAINCACHE_DB)
    except Exception:
        return ''
    return p if p and os.path.isfile(p) else ''


def _columns(cur):
    cur.execute('PRAGMA table_info(maincache)')
    return tuple(row[1] for row in cur.fetchall())


def repair(path=None):
    """Returns 'no_db' | 'no_table' | 'ok' | 'repaired' | 'failed'.
    Never raises."""
    path = path or _db_path()
    # Checked here and not only in _db_path(): sqlite3.connect CREATES a
    # missing file, so a path that does not exist has to stop us before we
    # leave an empty database lying in POV's profile.
    if not path or not os.path.isfile(path):
        return 'no_db'
    import sqlite3
    con = None
    try:
        con = sqlite3.connect(path, isolation_level=None)
        cur = con.cursor()
        cols = _columns(cur)
        if not cols:
            return 'no_table'
        if cols == WANTED_COLUMNS:
            return 'ok'
        if tuple(sorted(cols)) != tuple(sorted(WANTED_COLUMNS)):
            # Not the shape we know how to migrate. Leave it completely
            # alone rather than guess at somebody else's table.
            _log('unexpected maincache columns {0} -- leaving it alone'
                 .format(cols), level='WARNING')
            return 'failed'

        cur.execute('BEGIN IMMEDIATE')
        cur.execute('CREATE TABLE IF NOT EXISTS maincache_aifix '
                    '(id TEXT UNIQUE, expires INTEGER, data TEXT)')
        # BY NAME, so every value goes to the column it means -- and only the
        # rows whose `expires` is still a real integer, because the others are
        # the ones 6.x wrote through the swapped order and their contents are
        # already transposed beyond recovery.
        cur.execute('INSERT OR REPLACE INTO maincache_aifix (id, expires, data) '
                    'SELECT id, expires, data FROM maincache '
                    "WHERE typeof(expires) = 'integer'")
        kept = cur.rowcount
        cur.execute('SELECT COUNT(*) FROM maincache')
        total = cur.fetchone()[0]
        cur.execute('DROP TABLE maincache')
        cur.execute('ALTER TABLE maincache_aifix RENAME TO maincache')
        cur.execute('COMMIT')
        _log('maincache rebuilt in the 6.x column order: kept {0} of {1} row(s)'
             .format(kept, total), level='INFO')
        return 'repaired'
    except Exception as e:
        try:
            if con is not None:
                con.execute('ROLLBACK')
        except Exception:
            pass
        _log('repair failed: {0}'.format(e), level='WARNING')
        return 'failed'
    finally:
        try:
            if con is not None:
                con.close()
        except Exception:
            pass


def ensure_patched():
    return repair()
