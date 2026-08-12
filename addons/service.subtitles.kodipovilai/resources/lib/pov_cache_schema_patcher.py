# Rebuild POV's cache tables when POV changed their column order under them.
#
# THE REPORT. "I just installed the build and search never works, it just
# errors." The log:
#
#     mode=search_history -> menus/history.py line 27, for query in contents:
#     TypeError: 'int' object is not iterable
#
# WHAT HAPPENED, exactly. The build ships POV 5.12.04 and the POV author's own
# repository, and Kodi is set to install add-on updates automatically -- so on
# the first launch POV updates itself to 6.08.10. That is legitimate and
# expected. What is not expected is that POV 6 REORDERED the columns of its own
# cache tables:
#
#     5.12.04:  CREATE TABLE IF NOT EXISTS maincache (id, data, expires)
#     6.08.10:  CREATE TABLE IF NOT EXISTS maincache (id, expires, data)
#
# The statement is CREATE TABLE **IF NOT EXISTS**, so on an upgrade the table
# keeps the OLD order. POV 6 then writes to it positionally --
#
#     INSERT OR REPLACE INTO maincache VALUES (?, ?, ?)
#     (string, int(expires), jsdumps(data))
#
# -- with no column list. So the expiry integer lands in the `data` column and
# the JSON lands in `expires`. Reading it back, `data` is now a number, and
# every caller that expects a list gets an int. Reproduced end to end against a
# table created by 5.12.04's own statement, and the error is character for
# character the one on the device.
#
# It also never expires: the condition is `expires > ?`, and in SQLite a TEXT
# value always compares greater than an INTEGER, so the poisoned row is
# returned forever.
#
# SIX TABLES, not one. maincache, metadata, season_metadata, function_cache and
# results_data all swapped their payload and expiry columns. Search is only
# where it surfaces loudest -- the metadata and scraper-result caches are
# poisoned the same way, which is why "nothing really works from the start".
#
# WHY WE FIX IT AND NOT THE USER. There is no setting for this and POV's own
# "clear cache" only deletes rows -- the table keeps the wrong column order, so
# the very next write poisons it again. The only repair is to rebuild the table
# itself, and that is a thing a person should not have to do with a file
# manager on an Android box.
#
# WHAT THIS WILL NOT TOUCH. Only caches, and only when the column NAMES match
# and just the ORDER differs. Anything holding something a user would miss --
# watched status, resume points, favourites, views, the navigator lists -- is
# out of scope by name AND by rule: a table whose set of columns changed is a
# migration, not a swap, and dropping it could throw away real data. We log and
# leave it.

import os
import re
import sqlite3

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
CACHE_SOURCE = 'resources/lib/modules/cache.py'
PATHS_SOURCE = 'resources/lib/modules/kodi_utils.py'

# Caches only. Every one of these is rebuilt from the network on demand, so
# dropping one costs a little speed once and nothing else. Deliberately NOT
# here: watched_status, progress, favorites, favourites, dropped, views,
# navigator, trakt_data, mdbl_data -- anything a user would notice losing.
REBUILDABLE = frozenset((
    'maincache',
    'metadata',
    'season_metadata',
    'function_cache',
    'results_data',
))

# THE SAME UPGRADE ORPHANS THE FAVOURITES, in a different way. POV 5 kept them
# in a file of their own, spelled the British way; POV 6 keeps them in
# watched.db, spelled the American way:
#
#     5.12.04  favourites.db  ->  table `favourites`
#     6.08.10  watched.db     ->  table `favorites`
#
# Nothing migrates them, so POV 6 opens a table it has just created, finds it
# empty, and the user's favourites are simply gone from the screen. The rows
# are still on disk in the old file -- which is why this copies them across
# instead of shrugging.
#
# Two other databases moved in the same release (traktcache4.db ->
# traktcache.db, providerscache2.db -> providerscache.db). Both are caches that
# refill themselves from Trakt or from the scrapers within a sync, so they are
# deliberately left alone: an empty cache costs a few seconds once. Favourites
# are typed by hand and come back from nowhere.
LEGACY_FAVOURITES = ('favourites.db', 'favourites')
CURRENT_FAVOURITES = ('watched.db', 'favorites')


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_cache_schema_patcher: ' + msg, level=level)
    except Exception:
        pass


def _translate(path):
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath(path)
    except Exception:
        return ''


def _pov_file(rel):
    base = _translate('special://home/addons/' + POV_ADDON_ID + '/')
    if not base:
        return ''
    path = os.path.join(base, *rel.split('/'))
    return path if os.path.isfile(path) else ''


def _read(path):
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return handle.read()
    except OSError:
        return ''


def _declared_paths():
    """{'maincache_db': '/abs/path/maincache.db'} from POV's own kodi_utils."""
    source = _pov_file(PATHS_SOURCE)
    if not source:
        return {}
    out = {}
    for match in re.finditer(
            r'^\s*(\w+_db)\s*=\s*[\'"](special://[^\'"]+)[\'"]',
            _read(source), re.M):
        resolved = _translate(match.group(2))
        if resolved:
            out[match.group(1)] = resolved
    return out


def _declared_tables():
    """[(db_variable, table, columns, create_statement)] from POV's cache.py.

    Read out of POV rather than written down here. POV owns these definitions
    and has already changed them once; a copy in our tree would be a second
    source of truth that goes stale exactly when it matters."""
    source = _pov_file(CACHE_SOURCE)
    if not source:
        return []
    body = _read(source)
    start = body.find('def check_databases')
    if start == -1:
        return []
    end = body.find('\ndef ', start + 1)
    body = body[start:end if end != -1 else len(body)]

    out = []
    indexes = {}
    current = None
    for line in body.splitlines():
        connect = re.search(r'database_connect\(\s*(\w+_db)\s*\)', line)
        if connect:
            current = connect.group(1)
            continue
        index = re.search(
            r'(CREATE INDEX IF NOT EXISTS\s+\w+\s+ON\s+(\w+)\s*\([^)]*\))',
            line)
        if index:
            indexes.setdefault(index.group(2), []).append(index.group(1))
            continue
        create = re.search(
            r'(CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\((.*)\))\s*"""', line)
        if create and current:
            columns = _column_names(create.group(3))
            if columns:
                out.append((current, create.group(2), columns, create.group(1)))
    # DROP TABLE takes the table's indexes with it. POV would rebuild them the
    # next time check_databases() runs, but "the next time" can be a whole Kodi
    # session away, and metadata without its index is the slowest screen in the
    # build. Put them back in the same breath.
    return [(db, table, cols, stmt, indexes.get(table, []))
            for db, table, cols, stmt in out]


def _column_names(definition):
    """Column names in declaration order, ignoring table constraints.

    Depth counting, because UNIQUE (a, b) contains commas that are not column
    separators."""
    names, depth, field = [], 0, ''
    for char in definition:
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        if char == ',' and depth == 0:
            names.append(field)
            field = ''
        else:
            field += char
    names.append(field)
    out = []
    for name in names:
        name = name.strip()
        if not name or name.upper().startswith(
                ('UNIQUE', 'PRIMARY', 'FOREIGN', 'CHECK', 'CONSTRAINT')):
            continue
        out.append(name.split()[0])
    return out


def _actual_columns(cursor, table):
    try:
        cursor.execute('PRAGMA table_info(%s)' % table)
        return [row[1] for row in cursor.fetchall()]
    except sqlite3.Error:
        return []


def _table_columns(cursor, table):
    return _actual_columns(cursor, table)


def _migrate_favourites(data_dir, declared, results):
    """Copy POV 5's favourites into the table POV 6 reads.

    ADDITIVE AND ONCE. The old file is never modified and never deleted -- if
    this is wrong in some way nobody has thought of, the originals are still
    there. It runs only while POV 6's table is still EMPTY, which is both the
    only moment it is safe and the reason it cannot run twice: the second time,
    the destination has rows and we stop.

    GATED ON POV'S OWN DECLARATIONS, not on a version number and not on the
    files being present. A device still running POV 5 declares `favourites` and
    knows nothing about `favorites`; copying rows into a table that version
    never reads would be a silent no-op at best, and my own test caught it
    happening. So: only when THIS POV says favourites live in the new table and
    no longer declares the old one."""
    if CURRENT_FAVOURITES[1] not in declared or LEGACY_FAVOURITES[1] in declared:
        return
    old_path = os.path.join(data_dir, LEGACY_FAVOURITES[0])
    new_path = os.path.join(data_dir, CURRENT_FAVOURITES[0])
    if not (os.path.isfile(old_path) and os.path.isfile(new_path)):
        return
    source = destination = None
    try:
        source = sqlite3.connect(old_path, timeout=10)
        destination = sqlite3.connect(new_path, timeout=10)
        old_cols = _table_columns(source.cursor(), LEGACY_FAVOURITES[1])
        new_cols = _table_columns(destination.cursor(), CURRENT_FAVOURITES[1])
        if not old_cols or not new_cols:
            return
        if sorted(old_cols) != sorted(new_cols):
            results['favourites'] = 'shape_differs'
            _log('favourites: the old table is {0} and the new one is {1} -- '
                 'not copying a shape we do not recognise'.format(
                     old_cols, new_cols), level='WARNING')
            return
        if destination.execute('SELECT COUNT(*) FROM %s'
                               % CURRENT_FAVOURITES[1]).fetchone()[0]:
            results['favourites'] = 'already_populated'
            return
        rows = source.execute('SELECT %s FROM %s' % (
            ', '.join(old_cols), LEGACY_FAVOURITES[1])).fetchall()
        if not rows:
            results['favourites'] = 'nothing_to_move'
            return
        destination.executemany(
            'INSERT OR IGNORE INTO %s (%s) VALUES (%s)' % (
                CURRENT_FAVOURITES[1], ', '.join(old_cols),
                ', '.join('?' * len(old_cols))), rows)
        destination.commit()
        results['favourites'] = 'migrated'
        _log('favourites: moved {0} entr(ies) from {1} into {2}, which is '
             'where this POV looks for them'.format(
                 len(rows), LEGACY_FAVOURITES[0], CURRENT_FAVOURITES[0]))
    except Exception as error:
        results['favourites'] = 'failed'
        _log('favourites: {0}'.format(error), level='WARNING')
    finally:
        for connection in (source, destination):
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass


def ensure_patched():
    """Returns {'db.table': status}. Statuses: 'rebuilt' | 'ok' | 'renamed'
    | 'skipped' | 'failed'."""
    results = {}
    paths = _declared_paths()
    tables = _declared_tables()
    if not paths or not tables:
        return results

    by_db = {}
    for variable, table, columns, statement, table_indexes in tables:
        by_db.setdefault(variable, []).append(
            (table, columns, statement, table_indexes))

    for variable, entries in by_db.items():
        path = paths.get(variable)
        # Never CREATE a database POV has not made yet: an empty file where
        # POV expects none is a way to break something that was working.
        if not path or not os.path.isfile(path):
            continue
        connection = None
        try:
            connection = sqlite3.connect(path, timeout=10)
            cursor = connection.cursor()
            for table, columns, statement, table_indexes in entries:
                key = '{0}.{1}'.format(os.path.basename(path), table)
                actual = _actual_columns(cursor, table)
                if not actual:
                    continue                    # not created yet; POV will
                if actual == columns:
                    results[key] = 'ok'
                    continue
                if sorted(actual) != sorted(columns):
                    # Columns were added or removed. That is a migration and
                    # POV owns it; dropping the table here could destroy
                    # something we do not understand.
                    results[key] = 'renamed'
                    _log('{0}: columns differ by name, not order -- leaving it '
                         'to POV'.format(key), level='WARNING')
                    continue
                if table not in REBUILDABLE:
                    results[key] = 'skipped'
                    _log('{0}: column order changed but this table is not a '
                         'cache -- refusing to rebuild it'.format(key),
                         level='WARNING')
                    continue
                cursor.execute('DROP TABLE %s' % table)
                cursor.execute(statement)
                for index_statement in table_indexes:
                    cursor.execute(index_statement)
                connection.commit()
                results[key] = 'rebuilt'
                _log('{0}: rebuilt -- POV writes {1} but the table on disk was '
                     '{2}, so every value was landing in the wrong '
                     'column'.format(key, columns, actual))
        except Exception as error:
            results[os.path.basename(path)] = 'failed'
            _log('{0}: {1}'.format(os.path.basename(path), error),
                 level='WARNING')
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    data_dir = os.path.dirname(next(iter(paths.values()), ''))
    if data_dir:
        _migrate_favourites(
            data_dir, {t for _, t, _, _, _ in tables}, results)
    return results
