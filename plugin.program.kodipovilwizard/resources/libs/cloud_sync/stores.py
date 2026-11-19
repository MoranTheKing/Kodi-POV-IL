"""POV's and Umbrella's own local lists, read as the sync's values and written back (records.py).

POV keeps them in addon_data/plugin.video.pov/watched.db: favorites, dropped, watched_status, progress.
Umbrella keeps its favourites in addon_data/plugin.video.umbrella/favourites.db (a table per kind: movies,
tvshows, episode -- each row's details a Python literal, read back by Umbrella with eval()) and its own watched
marks and places in addon_data/plugin.video.umbrella/watched.db (watched, progress).

A row is a key -- the add-on, the list, the kind and the row's identity -- and its values: every column, so it is
written back exactly as it was read. Rows are only ever written with SQL parameters, and an Umbrella favourite's
details are written as the repr() of plain strings and numbers this build built itself (records.clean) and read
with ast.literal_eval, never eval.
"""
import ast
import os
import re
import sqlite3

PART = re.compile(r'^[A-Za-z0-9_:\-]{1,40}$')

# (list, table, identity columns, other columns); the first identity column is the kind
POV_TABLES = (
    ('fav', 'favorites', ('db_type', 'tmdb_id'), ('title',)),
    ('drop', 'dropped', ('db_type', 'tmdb_id'), ('title',)),
    ('watched', 'watched_status', ('db_type', 'media_id', 'season', 'episode'), ('last_played', 'title')),
    ('progress', 'progress', ('db_type', 'media_id', 'season', 'episode'),
     ('resume_point', 'curr_time', 'last_played', 'resume_id', 'title')),
)
UMB_TABLES = (
    ('watched', 'watched', ('media_type', 'imdb_id', 'tmdb_id', 'season', 'episode'), ('title', 'last_played', 'overlay')),
    ('progress', 'progress', ('media_type', 'imdb_id', 'tmdb_id', 'season', 'episode'),
     ('title', 'resume_point', 'curr_time', 'last_played', 'resume_id')),
)
# Umbrella's favourites: a table per kind, created by Umbrella only when its first favourite is added
UMB_FAVOURITES = {
    'movies': ('CREATE TABLE IF NOT EXISTS movies (id TEXT, items TEXT, UNIQUE(id));', ('id', 'items')),
    'tvshows': ('CREATE TABLE IF NOT EXISTS tvshows (id TEXT, items TEXT, UNIQUE(id));', ('id', 'items')),
    'episode': ('CREATE TABLE IF NOT EXISTS episode (id TEXT, season TEXT, episode TEXT, items TEXT, imdb TEXT, UNIQUE(id));',
                ('id', 'season', 'episode', 'items', 'imdb')),
}


def _part(value):
    return '_' if value in (None, '') else str(value)


def _key(addon, kind, ids):
    parts = [_part(i) for i in ids]
    if not re.match(r'^[a-z]{2,12}$', parts[0]) or not all(PART.match(p) for p in parts[1:]):
        return None
    return '%s.%s.%s' % (addon, kind, '.'.join(parts))


def _connect(path):
    con = sqlite3.connect(path, timeout=20)
    con.row_factory = sqlite3.Row
    return con


def _tables(con):
    return {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _values(row, columns):
    from .records import clean_value
    return clean_value({c: row[c] for c in columns if row[c] is not None}) or {}


def read_tables(path, addon, specs):
    """key -> values for every row of the tables in specs; rows that cannot be named are counted in 'skipped'."""
    out, skipped = {}, 0
    if not os.path.isfile(path):
        return out, skipped
    con = _connect(path)
    try:
        have = _tables(con)
        for kind, table, ids, rest in specs:
            if table not in have:
                continue
            for row in con.execute('SELECT %s FROM "%s"' % (', '.join(ids + rest), table)):
                key = _key(addon, kind, [row[c] for c in ids])
                if key is None:
                    skipped += 1
                    continue
                out[key] = _values(row, ids + rest)
    finally:
        con.close()
    return out, skipped


def write_tables(path, addon, specs, put, remove, local):
    """Write put (key -> values) and take away remove (keys) in the tables of specs; local: what was read, so a row
    is removed by its own identity. Returns how many rows changed."""
    by_kind = {kind: (table, ids, rest) for kind, table, ids, rest in specs}
    done = 0
    con = _connect(path)
    try:
        with con:
            have = _tables(con)
            for key, value in put.items():
                parts = key.split('.')
                spec = by_kind.get(parts[1]) if parts[0] == addon else None
                if not spec or spec[0] not in have:
                    continue
                table, ids, rest = spec
                if _key(addon, parts[1], [value.get(c) for c in ids]) != key:
                    continue        # (values that do not name the row the key names: never written)
                columns = ids + rest
                con.execute('INSERT OR REPLACE INTO "%s" (%s) VALUES (%s)' % (table, ', '.join(columns), ', '.join('?' * len(columns))),
                            [value.get(c) for c in columns])
                done += 1
            for key in remove:
                parts = key.split('.')
                spec = by_kind.get(parts[1]) if parts[0] == addon else None
                if not spec or spec[0] not in have or key not in local:
                    continue
                table, ids, _rest = spec
                con.execute('DELETE FROM "%s" WHERE %s' % (table, ' AND '.join('%s IS ?' % c for c in ids)),
                            [local[key].get(c) for c in ids])
                done += 1
    finally:
        con.close()
    return done


# ------------------------------------------------------------------ Umbrella's favourites
def _details(text):
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def read_umbrella_favourites(path):
    from .records import clean_value
    out, skipped = {}, 0
    if not os.path.isfile(path):
        return out, skipped
    con = _connect(path)
    try:
        have = _tables(con)
        for kind, (_create, columns) in UMB_FAVOURITES.items():
            if kind not in have:
                continue
            for row in con.execute('SELECT %s FROM "%s"' % (', '.join(columns), kind)):
                key = _key('umb', 'fav', [kind, row['id']])
                details = clean_value(_details(row['items']) or {})
                if key is None or not details:
                    skipped += 1
                    continue
                value = {c: row[c] for c in columns if c != 'items' and row[c] is not None}
                value['items'] = details
                out[key] = clean_value(value)
    finally:
        con.close()
    return out, skipped


def write_umbrella_favourites(path, put, remove, local):
    from .records import clean_value
    done = 0
    con = _connect(path)
    try:
        with con:
            for key, value in put.items():
                parts = key.split('.')
                if parts[:2] != ['umb', 'fav'] or parts[2] not in UMB_FAVOURITES:
                    continue
                create, columns = UMB_FAVOURITES[parts[2]]
                details = clean_value(value.get('items')) if isinstance(value.get('items'), dict) else None
                if not details or _key('umb', 'fav', [parts[2], value.get('id')]) != key:
                    continue
                con.execute(create)
                row = [repr(details) if c == 'items' else (None if value.get(c) is None else str(value.get(c))) for c in columns]
                con.execute('INSERT OR REPLACE INTO "%s" (%s) VALUES (%s)' % (parts[2], ', '.join(columns), ', '.join('?' * len(columns))), row)
                done += 1
            have = _tables(con)
            for key in remove:
                parts = key.split('.')
                if parts[:2] != ['umb', 'fav'] or parts[2] not in have or key not in local:
                    continue
                con.execute('DELETE FROM "%s" WHERE id IS ?' % parts[2], [local[key].get('id')])
                done += 1
    finally:
        con.close()
    return done


# ------------------------------------------------------------------ POV with Trakt or MDBList
# A viewer whose POV keeps its watched marks with Trakt or MDBList (its setting watched_indicators 1 / 2): POV writes
# them -- the whole history it read from there, and every mark and place since -- into its own cache file of that
# service (traktcache.db / mdblcache.db, the same tables as watched.db), never into watched.db. The owner, Nov 2026:
# "keep it working in the background as long as Google is connected, alongside Trakt / MDBList". So every round
# copies what changed in that cache into watched.db (mirror_pov): the viewer's Drive holds a copy of it all, and a
# device of the same viewer without Trakt has it too. Only what changed in the cache since the last copy is written,
# and only rows the copy itself made are ever removed (a row another device sent stays).
POV_CACHE = {1: 'traktcache.db', 2: 'mdblcache.db'}
POV_MIRRORED = POV_TABLES[2:]           # watched_status, progress


def local_time(text):
    """A service's UTC time ('2026-11-19T22:15:00.000Z') as watched.db writes its own ('2026-11-20 00:15:00')."""
    from datetime import datetime, timezone
    for pattern in ('%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ'):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S')
        except (TypeError, ValueError):
            continue
    return text


def mirror_pov(pov_dir, indicators, copied):
    """Copy into watched.db what changed in POV's Trakt / MDBList cache since the last copy (copied: key -> values
    then). Returns (copied now, rows written or removed); (copied, 0) when POV keeps its marks itself."""
    name = POV_CACHE.get(indicators)
    source, target = (os.path.join(pov_dir, name) if name else None), os.path.join(pov_dir, 'watched.db')
    if not source or not os.path.isfile(source) or not os.path.isfile(target):
        return copied, 0
    found, _skipped = read_tables(source, 'pov', POV_MIRRORED)
    for value in found.values():
        if isinstance(value.get('last_played'), str):
            value['last_played'] = local_time(value['last_played'])
    put = {key: value for key, value in found.items() if copied.get(key) != value}
    remove = [key for key in copied if key not in found]
    done = write_tables(target, 'pov', POV_MIRRORED, put, remove, copied) if (put or remove) else 0
    return found, done


# ------------------------------------------------------------------ both add-ons
class Stores(object):
    """The lists of one device: POV's and Umbrella's, where their files are (pov_dir, umb_dir: their addon_data)."""

    def __init__(self, pov_dir, umb_dir, pov_indicators=0):
        self.pov_dir, self.pov_indicators = pov_dir, pov_indicators
        self.pov = os.path.join(pov_dir, 'watched.db') if pov_dir else None
        self.umb_watched = os.path.join(umb_dir, 'watched.db') if umb_dir else None
        self.umb_favourites = os.path.join(umb_dir, 'favourites.db') if umb_dir else None

    def mine(self, key):
        """Is this key of a list this device has? (POV's file is made by POV; Umbrella's favourites file only with its
        first favourite -- Umbrella is here when its folder is.)"""
        if key.startswith('pov.'):
            return bool(self.pov) and os.path.isfile(self.pov)
        if key.startswith('umb.fav.'):
            return bool(self.umb_favourites) and os.path.isdir(os.path.dirname(self.umb_favourites))
        if key.startswith('umb.'):
            return bool(self.umb_watched) and os.path.isfile(self.umb_watched)
        return False

    def read(self):
        """key -> values for everything both add-ons hold; and how many rows could not be named."""
        values, skipped = {}, 0
        for found, missed in (read_tables(self.pov, 'pov', POV_TABLES) if self.pov else ({}, 0),
                              read_tables(self.umb_watched, 'umb', UMB_TABLES) if self.umb_watched else ({}, 0),
                              read_umbrella_favourites(self.umb_favourites) if self.umb_favourites else ({}, 0)):
            values.update(found)
            skipped += missed
        return values, skipped

    def write(self, put, remove, local):
        """Write what the merge says; each add-on's file only if it is there (an add-on not installed is left out)."""
        done = 0
        groups = (
            (self.pov, lambda k: k.startswith('pov.'), lambda p, a, r: write_tables(p, 'pov', POV_TABLES, a, r, local)),
            (self.umb_watched, lambda k: k.startswith('umb.') and not k.startswith('umb.fav.'),
             lambda p, a, r: write_tables(p, 'umb', UMB_TABLES, a, r, local)),
            (self.umb_favourites, lambda k: k.startswith('umb.fav.'), lambda p, a, r: write_umbrella_favourites(p, a, r, local)),
        )
        for path, mine, writer in groups:
            a = {k: v for k, v in put.items() if mine(k)}
            r = [k for k in remove if mine(k)]
            if not (a or r) or not path or not os.path.isdir(os.path.dirname(path)):
                continue
            if not os.path.isfile(path) and not path.endswith('favourites.db'):
                continue        # (the add-on's own file: made by the add-on; Umbrella's favourites file is made on its first)
            done += writer(path, a, r)
        return done
