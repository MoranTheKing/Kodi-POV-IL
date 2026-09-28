import os
import re
import sqlite3
import xbmc
import xbmcvfs

POV_ADDON_ID = 'plugin.video.pov'
CACHE_SOURCE = 'resources/lib/modules/cache.py'
PATHS_SOURCE = 'resources/lib/modules/kodi_utils.py'

REBUILDABLE = frozenset((
    'maincache',
    'metadata',
    'season_metadata',
    'function_cache',
    'results_data',
))

LEGACY_FAVOURITES = ('favourites.db', 'favourites')
CURRENT_FAVOURITES = ('watched.db', 'favorites')

def _log(msg):
    xbmc.log(f'pov_cache_schema: {msg}', xbmc.LOGINFO)

def _translate(path):
    return xbmcvfs.translatePath(path)

def _pov_file(rel):
    base = _translate(f'special://home/addons/{POV_ADDON_ID}/')
    if not base: return ''
    path = os.path.join(base, *rel.split('/'))
    return path if os.path.isfile(path) else ''

def _read(path):
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return handle.read()
    except Exception:
        return ''

def _declared_paths():
    source = _pov_file(PATHS_SOURCE)
    if not source: return {}
    out = {}
    for match in re.finditer(r'^\s*(\w+_db)\s*=\s*[\'"](special://[^\'"]+)[\'"]', _read(source), re.M):
        resolved = _translate(match.group(2))
        if resolved:
            out[match.group(1)] = resolved
    return out

def _balanced(body, open_index):
    depth = 0
    for i in range(open_index, len(body)):
        if body[i] == '(': depth += 1
        elif body[i] == ')':
            depth -= 1
            if depth == 0: return i + 1
    return -1

def _column_names(definition):
    names, depth, field = [], 0, ''
    for char in definition:
        if char == '(': depth += 1
        elif char == ')': depth -= 1
        if char == ',' and depth == 0:
            names.append(field)
            field = ''
        else: field += char
    names.append(field)
    out = []
    for name in names:
        name = name.strip()
        if not name or name.upper().startswith(('UNIQUE', 'PRIMARY', 'FOREIGN', 'CHECK', 'CONSTRAINT')):
            continue
        out.append(name.split()[0])
    return out

def _declared_tables():
    source = _pov_file(CACHE_SOURCE)
    if not source: return []
    body = _read(source)
    start = body.find('def check_databases')
    if start == -1: return []
    end = body.find('\ndef ', start + 1)
    body = body[start:end if end != -1 else len(body)]

    connects = []
    for match in re.finditer(r'database_connect\(\s*(\w+_db)\s*\)', body):
        line_start = body.rfind('\n', 0, match.start()) + 1
        prefix = body[line_start:match.start()]
        if (prefix.count("'") % 2) or (prefix.count('"') % 2): continue
        connects.append((match.start(), match.group(1)))

    def _owner(position):
        found = None
        for where, variable in connects:
            if where < position: found = variable
            else: break
        return found

    groups = {}
    for match in re.finditer(r'^\s*(\w+)\s*=\s*\(', body, re.M):
        close = _balanced(body, body.index('(', match.start()))
        if close != -1: groups[match.group(1)] = (match.start(), close)

    consumers = {}
    for match in re.finditer(r'for\s+\w+\s+in\s+(\w+)\s*:', body):
        if match.group(1) in groups:
            consumers.setdefault(match.group(1), []).append(match.start())

    def _group_owners(position):
        for name, (g_start, g_end) in groups.items():
            if g_start <= position < g_end and name in consumers:
                return [_owner(w) for w in consumers[name]]
        return []

    tables, indexes = [], {}
    for match in re.finditer(r'CREATE INDEX IF NOT EXISTS\s+\w+\s+ON\s+(\w+)\s*\(', body):
        close = _balanced(body, match.end() - 1)
        if close != -1:
            indexes.setdefault(match.group(1), []).append(' '.join(body[match.start():close].split()))

    for match in re.finditer(r'CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\(', body):
        close = _balanced(body, match.end() - 1)
        if close == -1: continue
        statement = ' '.join(body[match.start():close].split())
        columns = _column_names(statement[statement.index('(') + 1:-1])
        if not columns: continue
        owners = [o for o in _group_owners(match.start()) if o]
        if not owners:
            single = _owner(match.start())
            owners = [single] if single else []
        for owner in owners:
            tables.append((owner, match.group(1), columns, statement))

    seen, conflicting = {}, set()
    for db, table, cols, _stmt in tables:
        key = (db, table)
        if key in seen and seen[key] != cols: conflicting.add(key)
        seen[key] = cols

    tables = [t for t in tables if (t[0], t[1]) not in conflicting]
    return [(db, table, cols, stmt, indexes.get(table, [])) for db, table, cols, stmt in tables]

def _actual_columns(cursor, table):
    try:
        cursor.execute('PRAGMA table_info(%s)' % table)
        return [row[1] for row in cursor.fetchall()]
    except sqlite3.Error:
        return None

def _renamed(statement, table, scratch):
    return re.sub(r'(CREATE TABLE IF NOT EXISTS\s+)%s\b' % re.escape(table), r'\g<1>' + scratch, statement, count=1)

def _rebuild(cursor, table, columns, statement, index_statements):
    scratch = table + '_aifix'
    cursor.execute('BEGIN IMMEDIATE')
    try:
        cursor.execute('DROP TABLE IF EXISTS %s' % scratch)
        cursor.execute(_renamed(statement, table, scratch))
        columns_sql = ', '.join(columns)

        tests = []
        if 'expires' in columns:
            openers = ('[', '{', chr(34), chr(39))
            tests.append("typeof(expires) = 'integer'")
            tests.append('substr(%s, 1, 1) IN (%s)' % (
                columns[-1],
                ', '.join("'%s'" % (o * 2 if o == chr(39) else o) for o in openers)))
        keep = ('WHERE ' + ' AND '.join(tests)) if tests else ''

        cursor.execute('INSERT OR REPLACE INTO %s (%s) SELECT %s FROM %s %s' % (scratch, columns_sql, columns_sql, table, keep))
        cursor.execute('DROP TABLE %s' % table)
        cursor.execute('ALTER TABLE %s RENAME TO %s' % (scratch, table))
        for idx in index_statements:
            cursor.execute(idx)
        cursor.execute('COMMIT')
    except Exception:
        try: cursor.execute('ROLLBACK')
        except Exception: pass
        raise

def _one_table(cursor, key, table, columns, statement, index_statements):
    actual = _actual_columns(cursor, table)
    if actual is None or not actual or actual == columns: return

    if sorted(actual) != sorted(columns): return
    if table not in REBUILDABLE: return
    _rebuild(cursor, table, columns, statement, index_statements)
    _log(f"Rebuilt cache transposed table: {key}")

def _migrate_favourites(data_dir, declared):
    if CURRENT_FAVOURITES[1] not in declared or LEGACY_FAVOURITES[1] in declared: return
    old_path = os.path.join(data_dir, LEGACY_FAVOURITES[0])
    new_path = os.path.join(data_dir, CURRENT_FAVOURITES[0])
    if not (os.path.isfile(old_path) and os.path.isfile(new_path)): return

    source = destination = None
    try:
        source = sqlite3.connect(old_path, timeout=10)
        destination = sqlite3.connect(new_path, timeout=10)
        old_cols = _actual_columns(source.cursor(), LEGACY_FAVOURITES[1])
        new_cols = _actual_columns(destination.cursor(), CURRENT_FAVOURITES[1])

        if not old_cols or not new_cols or sorted(old_cols) != sorted(new_cols): return
        if destination.execute('SELECT COUNT(*) FROM %s' % CURRENT_FAVOURITES[1]).fetchone()[0]: return

        rows = source.execute('SELECT %s FROM %s' % (', '.join(old_cols), LEGACY_FAVOURITES[1])).fetchall()
        if not rows: return

        destination.executemany(
            'INSERT OR IGNORE INTO %s (%s) VALUES (%s)' % (
                CURRENT_FAVOURITES[1], ', '.join(old_cols),
                ', '.join('?' * len(old_cols))), rows)
        destination.commit()
        _log(f"Migrated {len(rows)} legacy favourites successfully.")
    except Exception as e:
        _log(f"favourites migration failed: {e}")
    finally:
        for connection in (source, destination):
            if connection:
                try: connection.close()
                except Exception: pass

def run():
    paths = _declared_paths()
    tables = _declared_tables()
    if not paths or not tables: return

    by_db = {}
    for variable, table, columns, statement, table_indexes in tables:
        by_db.setdefault(variable, []).append((table, columns, statement, table_indexes))

    for variable, entries in by_db.items():
        path = paths.get(variable)
        if not path or not os.path.isfile(path): continue

        connection = None
        try:
            connection = sqlite3.connect(path, timeout=10, isolation_level=None)
            cursor = connection.cursor()
            for table, columns, statement, table_indexes in entries:
                key = f'{os.path.basename(path)}.{table}'
                try:
                    _one_table(cursor, key, table, columns, statement, table_indexes)
                except Exception as e:
                    _log(f"{key}: {e}")
        except Exception as e:
            _log(f"DB Connect Error {os.path.basename(path)}: {e}")
        finally:
            if connection:
                try: connection.close()
                except Exception: pass

    data_dir = os.path.dirname(next(iter(paths.values()), ''))
    if data_dir:
        _migrate_favourites(data_dir, {t for _, t, _, _, _ in tables})