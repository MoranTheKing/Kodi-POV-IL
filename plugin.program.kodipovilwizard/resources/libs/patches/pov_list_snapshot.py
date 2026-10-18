"""Open POV lists from the finished list saved last time ("saved lists").

Every POV list -- home rows, tiles, categories, "Continue watching" -- is built
from scratch on each visit: per-title metadata from SQLite in ~20 threads,
then ~60 ListItem/InfoTag calls per title. On an Android box that is 0.6-3 s
per list, and 10 s for "Continue watching" right after Kodi starts while a
dozen add-on services start beside it (field logs, Oct 2026).

A list built normally is RECORDED: every ListItem/InfoTag call POV makes and
every xbmcplugin call for the handle, in order, as plain data (marshal). The next visit
REPLAYS that record -- the same calls on fresh ListItems -- without importing
POV's menus, without metadata, threads or network.

When a saved list may be used:
* never after a change -- POV's settings or watch-state databases
  (watched/progress/Trakt/MDBList, dropped shows) differ from when it was
  saved: watching an episode, marking something watched, a setting or a sync
  makes every saved list rebuild at once (personal lists also follow POV's
  list cache); a POV or Wizard update starts over as well;
* while fresh (general lists such as popular/new 3 hours, personal lists 30
  minutes) it is simply shown;
* while merely old (up to a week -- e.g. the first list after Kodi starts
  in the morning) or saved on an earlier day (next/in-progress episodes
  depend on the date) it is shown at once AND rebuilt right after, in the
  same call; when the rebuilt list differs, the open list or the home rows
  refresh themselves (POV's own widget refresh), already from the new copy;
* older than that, the list is built as before.
Search/discover routes and child profiles are never saved. Anything the
recorder cannot reproduce exactly (an unknown argument type, a ListItem it did
not create) leaves the list unsaved: it simply keeps working as before.

Start-up cost matters more than the replay: every home row is a new Python
interpreter, and while Kodi starts a dozen add-on services, importing json
took 0.3-1.2 s, hashlib and sqlite3 0.1-0.3 s each (QA log, Oct 2026). The
path that serves a saved list therefore imports none of them: the record is
read with marshal (built in), and "nothing changed" is first proven by the
files' sizes and times. Only when a file was written since does it fall back
to the content checks below (and records the new times once they match).
"""
import marshal
import os
import zlib
import sys
import time

FORMAT = 5
SUFFIX = '.snap'
# A file written this recently may be written again within the same tick of
# its modification time, so its time proves nothing yet.
FRESH_STAT_S = 2.0
# POV's own menus (genres, years, networks, "My content", the main menus,
# shortcut folders): what skins open as categories. Built from POV's menu
# database, its settings and the account manager's (the Wizard hides rows of
# services that are not connected); the years list follows the date.
NAVIGATOR_MODES = frozenset((
    'navigator.main', 'navigator.genres', 'navigator.years', 'navigator.networks',
    'navigator.anime_genres', 'navigator.anime_years', 'navigator.my_content',
    'navigator.because_you_watched', 'navigator.favorites',
    'navigator.shortcut_folders', 'navigator.build_shortcut_folder_list'))
# A show's seasons and a season's episodes: rebuilt from scratch on every
# visit -- 3-4.5 s on a Shield when the player returns to them (field log and
# video, Oct 2026). They follow the show's rows in POV's metadata cache and the
# watch state (a watched episode or a resume point: shown, then refreshed).
SHOW_MODES = frozenset(('build_season_list', 'build_episode_list'))
META_DB = 'metacache.db'
ROUTES = frozenset(('build_movie_list', 'build_tvshow_list',
                    'build_next_episode', 'build_in_progress_episode')) | NAVIGATOR_MODES | SHOW_MODES
NAVIGATOR_DB = 'navigator.db'
ACCTMGR_SETTINGS = os.path.join(os.pardir, 'script.module.acctmgr', 'settings.xml')
GENERAL_TTL_S = 3 * 3600
PERSONAL_TTL_S = 30 * 60
# Shown at once up to a week old (rebuilt right after when old): people come
# back to Kodi after half a day or a day, and that first screen matters most.
MAX_AGE_S = 7 * 24 * 3600
MAX_FILES = 400
# How long a dependency read waits for a locked database (shorter on exit).
DB_TIMEOUT = 2.0
# Lists built ahead of a first visit stop here, leaving room for visited ones.
PREBUILD_MAX_FILES = 300
# What a list depends on, by CONTENT: Kodi and POV's syncs rewrite these files
# at every start without changing them, so file times would discard every
# saved list. Watch state = row count, last row and last watch per table.
WATCH_DBS = ('watched.db', 'traktcache.db', 'mdblcache.db')
WATCH_TABLES = ('watched_status', 'progress', 'dropped', 'favorites')
HASHED_FILES = ('settings.xml', 'povil_dropped_trakt.json', 'povil_dropped_mdblist.json')
# Sizes and times of every file above (and POV's list cache): unchanged files
# mean unchanged dependencies, without opening a database.
STAT_FILES = HASHED_FILES + (ACCTMGR_SETTINGS,) + tuple(
    name + suffix for name in WATCH_DBS + ('maincache.db', NAVIGATOR_DB, META_DB)
    for suffix in ('', '-wal'))
# profile_age_guard's files (a test keeps these equal to its constants).
GUARD_POLICY_FILE = 'povil_profiles.json'
GUARD_CHILD_MARKER = 'povil.child-profile'
# Emergency switch: this file in the Wizard's profile folder turns saved lists off.
KILL_SWITCH = 'special://profile/addon_data/plugin.program.kodipovilwizard/povil_snapshots_off'
# Account lists (Trakt/MDBList/TMDb lists) also follow POV's list caches;
# "Continue watching" / in-progress read watch state only.
ACCOUNT_CACHES = (('maincache.db', 'maincache'), ('traktcache.db', 'trakt_data'),
                  ('mdblcache.db', 'mdbl_data'))
# TMDb account lists are cached as tmdblist_<list>_<type>, not under the action.
TMDB_ACCOUNT_CACHE = 'tmdblist'
PERSONAL_PREFIXES = ('tmdb_my', 'trakt_', 'mdblist_', 'in_progress', 'next_episode',
                     'tmdb_watchlist', 'tmdb_favorites', 'tmdb_recommendations',
                     'favorites_', 'watched_')
EPISODE_ROUTES = ('build_next_episode', 'build_in_progress_episode')
# Trakt's public charts (POV's trakt_main: trending, most watched, ...) are
# the same for everyone; only the account's own Trakt lists follow its syncs.
TRAKT_PUBLIC_PREFIXES = ('trakt_movies_', 'trakt_tv_', 'trakt_moviesanime_', 'trakt_tvanime_')
_LISTITEM_RECORDED = ('set', 'add', 'select')


class Unsupported(Exception):
    pass


def _plain(value):
    """Plain-data copy of a call argument, or Unsupported."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, tuple):
        # Kodi wants real tuples in places (context-menu entries).
        return {'__tuple__': [_plain(v) for v in value]}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise Unsupported('dict key %r' % type(k).__name__)
            out[k] = _plain(v)
        return out
    getter = getattr(value, 'getName', None)
    if callable(getter) and hasattr(value, 'getRole'):        # xbmc.Actor
        return {'__actor__': [value.getName(), value.getRole(), value.getOrder(),
                              value.getThumbnail()]}
    raise Unsupported(type(value).__name__)


def _live(value, xbmc):
    if isinstance(value, list):
        return [_live(v, xbmc) for v in value]
    if isinstance(value, dict):
        if set(value) == {'__tuple__'}:
            return tuple(_live(v, xbmc) for v in value['__tuple__'])
        if set(value) == {'__actor__'}:
            name, role, order, thumb = value['__actor__']
            return xbmc.Actor(name, role, order, thumb)
        return {k: _live(v, xbmc) for k, v in value.items()}
    return value


class _RecTag(object):
    """InfoTagVideo stand-in: records setters, forwards everything."""

    def __init__(self, real, ops, state):
        self._real, self._ops, self._state = real, ops, state

    def __getattr__(self, name):
        attr = getattr(self._real, name)
        if not callable(attr) or not name.startswith(('set', 'add')):
            return attr

        def call(*args, **kwargs):
            try:
                self._ops.append(['t', name, _plain(list(args)), _plain(kwargs)])
            except Unsupported as exc:
                self._state['unsupported'] = 'tag.%s(%s)' % (name, exc)
            return attr(*args, **kwargs)
        return call


class _RecItem(object):
    """ListItem stand-in: records state-changing calls, forwards everything."""

    def __init__(self, real, state):
        self._real, self._state, self._ops = real, state, []

    def getVideoInfoTag(self, *args, **kwargs):
        try:
            self._ops.append(['L', 'getVideoInfoTag', _plain(list(args)), _plain(kwargs)])
        except Unsupported as exc:
            self._state['unsupported'] = 'getVideoInfoTag(%s)' % exc
        return _RecTag(self._real.getVideoInfoTag(*args, **kwargs), self._ops, self._state)

    def __getattr__(self, name):
        attr = getattr(self._real, name)
        if not callable(attr) or not name.startswith(_LISTITEM_RECORDED):
            return attr

        def call(*args, **kwargs):
            try:
                self._ops.append(['L', name, _plain(list(args)), _plain(kwargs)])
            except Unsupported as exc:
                self._state['unsupported'] = '%s(%s)' % (name, exc)
            return attr(*args, **kwargs)
        return call


def _build(item_ops, xbmc, xbmcgui):
    if item_ops and item_ops[0][0] == 'N':      # recorded constructor call
        kwargs = _live(item_ops[0][3], xbmc)
        # offscreen: the item is only handed to the directory; without it every
        # setter waits for Kodi's GUI lock (0.4-0.8 s for a 662-entry row on a
        # phone at start-up, field log).
        kwargs.setdefault('offscreen', True)
        li = xbmcgui.ListItem(*_live(item_ops[0][2], xbmc), **kwargs)
        item_ops = item_ops[1:]
    else:
        li = xbmcgui.ListItem(offscreen=True)
    tag = None
    for kind, name, args, kwargs in item_ops:
        args, kwargs = _live(args, xbmc), _live(kwargs, xbmc)
        if kind == 'L' and name == 'getVideoInfoTag':
            tag = li.getVideoInfoTag(*args, **kwargs)
        elif kind == 'L':
            getattr(li, name)(*args, **kwargs)
        elif tag is not None:
            getattr(tag, name)(*args, **kwargs)
    return li


# ---------------------------------------------------------------- freshness --

def _profile_dir(xbmcvfs):
    return xbmcvfs.translatePath('special://profile/addon_data/plugin.video.pov/')


def _personal_action(action):
    return action.startswith(PERSONAL_PREFIXES) and not action.startswith(TRAKT_PUBLIC_PREFIXES)


def _personal(params):
    mode = params.get('mode', '')
    action = params.get('action', '') or ''
    return mode in EPISODE_ROUTES or _personal_action(action)


def _account_list(params):
    action = params.get('action', '') or ''
    return params.get('mode') in ('build_movie_list', 'build_tvshow_list') and _personal_action(action)


def eligible(params):
    if params.get('mode') not in ROUTES:
        return False
    if params.get('mode') in SHOW_MODES and not (params.get('tmdb_id') or '').isdigit():
        return False
    action = (params.get('action') or '')
    return not any(word in action for word in ('search', 'discover'))


def _db_module():
    """The C sqlite module alone: sqlite3/dbapi2 also imports datetime and
    friends, 0.1-0.3 s in a fresh interpreter while Kodi starts."""
    try:
        import _sqlite3 as db
        db.connect
        return db
    except (ImportError, AttributeError):
        import sqlite3 as db
        return db


def _crc(data):
    import binascii
    return '%08x' % binascii.crc32(data)


def _json_items(raw):
    """The "items" of a dropped-shows file, which its writer stores compactly
    as {...,"items":[...],"complete":...}; json only if that ever changes."""
    text = raw.decode('utf-8')
    start = text.find('"items":')
    end = text.find(',"complete"', start) if start >= 0 else -1
    if end > start >= 0:
        return text[start + 8:end].encode('utf-8')
    import json
    return json.dumps(json.loads(text).get('items')).encode('utf-8')


def _rows_crc(path, table):
    """Every row of a small table (POV's menus), as one checksum."""
    sqlite3 = _db_module()
    if not os.path.isfile(path):
        return None
    con = sqlite3.connect(path, timeout=DB_TIMEOUT)
    try:
        return _crc(repr(con.execute('SELECT * FROM "%s" ORDER BY 1, 2' % table).fetchall()).encode('utf-8'))
    except sqlite3.Error:
        return 'error'
    finally:
        con.close()


def _show_meta(path, params):
    """The show's metadata row and, for an episode list, its season row(s), as
    one checksum (POV refetches them when they expire or a new episode airs)."""
    sqlite3 = _db_module()
    if not os.path.isfile(path):
        return None
    tmdb_id = params.get('tmdb_id') or ''
    season = params.get('season') or ''
    con = sqlite3.connect(path, timeout=DB_TIMEOUT)
    try:
        rows = con.execute("SELECT meta FROM metadata WHERE db_type = 'tvshow' AND tmdb_id = ?",
                           (tmdb_id,)).fetchall()
        if params.get('mode') == 'build_episode_list':
            if season == 'all':
                rows += con.execute("SELECT tmdb_id, meta FROM season_metadata WHERE tmdb_id LIKE ? "
                                    "ESCAPE '\\' ORDER BY tmdb_id", (tmdb_id + '\\_%',)).fetchall()
            else:
                rows += con.execute('SELECT meta FROM season_metadata WHERE tmdb_id = ?',
                                    ('%s_%s' % (tmdb_id, season),)).fetchall()
        return _crc(repr(rows).encode('utf-8'))
    except sqlite3.Error:
        return 'error'
    finally:
        con.close()


def _table_marks(con, table):
    cols = [r[1] for r in con.execute('PRAGMA table_info("%s")' % table)]
    if not cols:
        return None
    extra = ', max(last_played)' if 'last_played' in cols else ''
    return list(con.execute('SELECT count(*), max(rowid)%s FROM "%s"' % (extra, table)).fetchone())


def _db_marks(path, tables, hidden=False):
    sqlite3 = _db_module()
    if not os.path.isfile(path):
        return None
    con = sqlite3.connect(path, timeout=DB_TIMEOUT)
    try:
        out = {t: _table_marks(con, t) for t in tables}
        if hidden:
            # Trakt shows hidden from progress steer "Continue watching".
            rows = con.execute("SELECT id, data FROM trakt_data WHERE id LIKE '%hidden%' ORDER BY id").fetchall()
            out['hidden'] = _crc(repr(rows).encode('utf-8'))
        return out
    except sqlite3.Error:
        return 'error'
    finally:
        con.close()


def _list_marks(path, action):
    """POV's own cache rows for this list (every page/variant), unexpired.

    POV re-fetching the list (its data lives 2 days), a cleared cache or an
    expired row all change this, so the saved list is rebuilt from fresh data
    exactly when POV's list changes."""
    sqlite3 = _db_module()
    if not os.path.isfile(path):
        return None
    pattern = action.replace('\\', '\\\\').replace('_', '\\_').replace('%', '\\%') + '\\_%'
    con = sqlite3.connect(path, timeout=DB_TIMEOUT)
    try:
        return [list(r) for r in con.execute(
            "SELECT id, expires FROM maincache WHERE id LIKE ? ESCAPE '\\' AND expires > ? ORDER BY id",
            (pattern, int(time.time())))]
    except sqlite3.Error:
        return 'error'
    finally:
        con.close()


# POV caches a parameterised list under action_<value>_<page>
# (tmdb_movies_genres_28_1, tmdb_tv_year_2024_1, tmdb_tv_networks_213_1):
# each genre/year/network is its own list, so browsing one leaves the others.
LIST_PARAMS = ('genre_id', 'year', 'network_id', 'collection_id', 'tmdb_id', 'company_id', 'key_id')


def _list_rows(path, action, params):
    value = next((params[k] for k in LIST_PARAMS if params.get(k)), '')
    if value and value.replace(',', '').isalnum():
        rows = _list_marks(path, '%s_%s' % (action, value))
        if rows:          # else: the list's rows are gone (cache cleared) or named differently
            return rows
    return _list_marks(path, action)


def _dep_file(key):
    """The file a dependency is read from (its -wal file counts too)."""
    if key in ('list', 'tmdblist'):
        return 'maincache.db'
    if key == 'acctmgr':
        return ACCTMGR_SETTINGS
    return key.split(':')[0]


def _changed_keys(old_sig, new_sig, deps):
    """Dependencies whose file changed between two file-time signatures."""
    changed = {name[:-4] if name.endswith('-wal') else name
               for name in set(old_sig) | set(new_sig) if old_sig.get(name) != new_sig.get(name)}
    return {key for key in deps if _dep_file(key) in changed}


def _deps(profile, params, keep=None, fresh=None):
    """Everything a list depends on. With keep (the record's dependencies)
    and fresh (the keys to read again), only those are read; the rest are
    taken from keep -- their files have not changed."""
    def reuse(key):
        return keep is not None and fresh is not None and key not in fresh and key in keep
    out = {}
    action = params.get('action') or ''
    if action:
        out['list'] = keep['list'] if reuse('list') else _list_rows(
            os.path.join(profile, 'maincache.db'), action, params)
        if action.startswith(('tmdb_watchlist', 'tmdb_favorites', 'tmdb_recommendations')):
            out['tmdblist'] = keep['tmdblist'] if reuse('tmdblist') else _list_marks(
                os.path.join(profile, 'maincache.db'), TMDB_ACCOUNT_CACHE)
    for name in HASHED_FILES:
        if reuse(name):
            out[name] = keep[name]
            continue
        try:
            with open(os.path.join(profile, name), 'rb') as fh:
                raw = fh.read()
        except OSError:
            out[name] = None
            continue
        if name.endswith('.json'):
            # Only the dropped shows themselves; retry/check stamps change
            # on every check without changing any list.
            try:
                raw = _json_items(raw)
            except (ValueError, AttributeError, UnicodeDecodeError):
                pass
        out[name] = _crc(raw)
    for name in WATCH_DBS:
        out[name] = keep[name] if reuse(name) else _db_marks(
            os.path.join(profile, name), WATCH_TABLES, hidden=(name == 'traktcache.db'))
    if (params.get('mode') or '').startswith('navigator.'):
        out[NAVIGATOR_DB] = keep[NAVIGATOR_DB] if reuse(NAVIGATOR_DB) else _rows_crc(
            os.path.join(profile, NAVIGATOR_DB), 'navigator')
        if reuse('acctmgr'):
            out['acctmgr'] = keep['acctmgr']
        else:
            try:
                with open(os.path.join(profile, ACCTMGR_SETTINGS), 'rb') as fh:
                    out['acctmgr'] = _crc(fh.read())
            except OSError:
                out['acctmgr'] = None
    if params.get('mode') in SHOW_MODES:
        out[META_DB] = keep[META_DB] if reuse(META_DB) else _show_meta(
            os.path.join(profile, META_DB), params)
    if _account_list(params):
        for name, table in ACCOUNT_CACHES:
            key = name + ':' + table
            out[key] = keep[key] if reuse(key) else _db_marks(os.path.join(profile, name), (table,))
    return out


def _versions(xbmcaddon):
    out = []
    for aid in ('plugin.video.pov', 'plugin.program.kodipovilwizard'):
        try:
            out.append(xbmcaddon.Addon(aid).getAddonInfo('version'))
        except Exception:
            out.append('?')
    return out


PINNED_LABELS = ('Container.PluginName', 'Container.FolderPath')
MENU_MODULES = ('menus.movies', 'menus.tvshows')


PREBUILD_PROPERTY = 'povil.prebuild'


def _labels(xbmc, argv=None, consume=False):
    """What POV reads from the screen while it builds a list:
    * Container.PluginName -- external_browse(): a home row or another
      add-on's list is built differently (context menus, hidden watched
      titles, view mode, paging);
    * Container.FolderPath -- full-screen lists keep it as their way back
      (exit_list_params) unless the request already carries one.
    Read once per request; the build sees exactly these values (Recorder
    pins them until endOfDirectory), because Kodi switches both the moment
    a list -- or a saved copy -- reaches the screen.
    A list built ahead of its first visit (prebuild) is built for the screen
    it will be opened from, which the Wizard names in PREBUILD_PROPERTY."""
    if argv is not None:
        mark = xbmc.getInfoLabel('Window(10000).Property(%s)' % PREBUILD_PROPERTY)
        if mark:
            parts = mark.split('\x1f')
            try:
                if len(parts) == 4 and float(parts[0]) > time.time() and parts[1] == (
                        argv[2] if len(argv) > 2 else ''):
                    if consume:
                        # Read by the build itself (wrap), one request only: a
                        # real click on the same entry from another screen
                        # must read its own screen. serve_early must not clear
                        # it -- POV builds after it, in the same request.
                        xbmc.executebuiltin('ClearProperty(%s,home)' % PREBUILD_PROPERTY)
                    return {'Container.PluginName': parts[2], 'Container.FolderPath': parts[3]}
            except ValueError:
                pass
    return {name: xbmc.getInfoLabel(name) for name in PINNED_LABELS}


def _context(labels, params):
    widget = 'pov' not in labels['Container.PluginName']
    folder = '' if params.get('exit_list_params') else labels['Container.FolderPath']
    return [widget, folder]


def _fnv64(text):
    h = 0xcbf29ce484222325
    for byte in text.encode('utf-8'):
        h = ((h ^ byte) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return '%016x' % h


def _key(argv, versions, context):
    """(file name, full key). The name is a short hash; the full key is kept
    in the file and compared on load, so a hash collision is just a miss."""
    raw = repr([FORMAT, argv[0], argv[2] if len(argv) > 2 else '', versions, context])
    return _fnv64(raw), raw


def _path(profile, argv, versions, context):
    name, raw = _key(argv, versions, context)
    return os.path.join(_store_dir(profile), name + SUFFIX), raw


def _stat_sig(profile, now=None):
    """Size and modification time of every dependency file, or None when one
    was written too recently to prove anything."""
    now = time.time() if now is None else now
    out = {}
    for name in STAT_FILES:
        try:
            st = os.stat(os.path.join(profile, name))
        except OSError:
            out[name] = None
            continue
        if now - st.st_mtime < FRESH_STAT_S:
            return None
        out[name] = (st.st_mtime_ns, st.st_size)
    return out


def _expiry(deps):
    """When POV's cached rows for this list start expiring (they leave the
    'list' dependency without any file being written)."""
    ends = [row[1] for key in ('list', 'tmdblist') if isinstance(deps.get(key), list)
            for row in deps[key] if isinstance(row, (list, tuple)) and len(row) > 1]
    return min(ends) if ends else None


def _settled_sig(profile, take_deps):
    """(deps, sig): sig only when no file changed while deps were read."""
    before = _stat_sig(profile)
    deps = take_deps()
    after = _stat_sig(profile)
    return deps, (before if before is not None and before == after else None)


def _store_dir(profile):
    return os.path.join(profile, 'povil_snapshots')


def _trusted(deps):
    """A dependency that could not be read (locked database) proves nothing."""
    if deps == 'error':
        return False
    if isinstance(deps, dict):
        return all(_trusted(v) for v in deps.values())
    return True


def _today():
    return time.strftime('%Y-%m-%d')


def read(path, raw):
    """The saved record for this full key, or None."""
    try:
        with open(path, 'rb') as fh:
            data = fh.read()
        snap = marshal.loads(zlib.decompress(data[1:]) if data[:1] == b'Z' else data)
    except (OSError, ValueError, EOFError, TypeError, zlib.error):
        return None
    if not isinstance(snap, dict) or snap.get('format') != FORMAT or snap.get('key') != raw:
        return None
    return snap


def _age(snap, now):
    age = now - float(snap.get('created', 0))
    return age if 0 <= age < MAX_AGE_S else None


def load(path, raw, deps, now=None):
    """(snapshot, age_s) when the saved list may be shown, else (None, None)."""
    now = time.time() if now is None else now
    if not _trusted(deps):
        return None, None
    snap = read(path, raw)
    if snap is None or snap.get('deps') != deps:
        return None, None
    age = _age(snap, now)
    return (snap, age) if age is not None else (None, None)


def proven(snap, sig, now=None):
    """True when the files show nothing changed since the record was taken,
    so its dependencies need not be read again."""
    now = time.time() if now is None else now
    if sig is None or snap.get('sig') is None or snap['sig'] != sig:
        return False
    expires = snap.get('expires')
    return expires is None or now < expires


MENUS_INDEX = '_menus.idx'


def _note_menu(folder, path, snap):
    """Remember which records are POV menus, so building lists ahead reads
    those few instead of every record."""
    if not snap.get('menu'):
        return
    index = os.path.join(folder, MENUS_INDEX)
    name = os.path.basename(path)
    try:
        with open(index, 'r', encoding='utf-8') as fh:
            if name in fh.read().split():
                return
    except OSError:
        pass
    with open(index, 'a', encoding='utf-8') as fh:
        fh.write(name + '\n')


def save(path, snap):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    # Two interpreters may save at once: a private temporary name each.
    tmp = '%s.%d.%d.tmp' % (path, os.getpid(), int(time.perf_counter() * 1e9) ^ id(snap))
    try:
        with open(tmp, 'xb') as fh:
            # ~5x smaller; decompressing a list costs about a millisecond.
            fh.write(b'Z' + zlib.compress(marshal.dumps(snap), 1))
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    try:
        _note_menu(folder, path, snap)
    except OSError:
        pass
    try:
        now = time.time()
        entries = [os.path.join(folder, n) for n in os.listdir(folder)]
        for stray in [e for e in entries if (e.endswith('.tmp') and now - os.path.getmtime(e) > 600)
                      or e.endswith('.json')]:        # format 3 and older
            os.remove(stray)
        names = [e for e in entries if e.endswith(SUFFIX)]
        if len(names) > MAX_FILES:
            for old in sorted(names, key=os.path.getmtime)[:len(names) - MAX_FILES]:
                os.remove(old)
    except OSError:
        pass


# ------------------------------------------------------------ record/replay --

class Recorder(object):
    """Swaps POV's list-building entry points for recording ones."""

    PLUGIN_CALLS = ('addDirectoryItems', 'addDirectoryItem', 'setContent',
                    'setPluginCategory', 'addSortMethod', 'endOfDirectory', 'setResolvedUrl')
    UTIL_CALLS = ('set_view_mode', 'focus_index')

    def __init__(self, kodi_utils, xbmcplugin, xbmcgui, handle, shadow=False, labels=None,
                 listitem_class=False):
        # shadow: rebuild after a replay already ended this handle -- record
        # only, nothing reaches Kodi. labels: screen labels POV is shown
        # while it builds (see _labels).
        self.ku, self.xp, self.xg, self.handle = kodi_utils, xbmcplugin, xbmcgui, handle
        self.shadow, self.labels = shadow, labels or {}
        # listitem_class: the host builds xbmcgui.ListItem(...) itself (Idan
        # Plus) instead of POV's kodi_utils.make_listitem().
        self.listitem_class = listitem_class
        self.state = {'unsupported': None, 'ended': False}
        self.items, self.calls, self.saved, self.menus, self.pinned = [], [], {}, [], None

    def _index(self, li):
        if not isinstance(li, _RecItem):
            raise Unsupported('ListItem not built by make_listitem')
        # The item carries its own index: a host that drops each ListItem
        # after adding it (Idan Plus) lets Python reuse id() values, so an
        # id-keyed table replayed later items as earlier ones.
        index = li.__dict__.get('_index')
        if index is None:
            index = li.__dict__['_index'] = len(self.items)
            self.items.append(li._ops)
        return index

    def __enter__(self):
        ku, xp, xg, state = self.ku, self.xp, self.xg, self.state
        if ku is not None:
            self.saved['ku.make_listitem'] = ku.make_listitem
            ku.make_listitem = lambda: _RecItem(xg.ListItem(offscreen=True), state)
        if self.listitem_class:
            real_cls = xg.ListItem
            self.saved['xg.ListItem'] = real_cls

            def listitem(*args, **kwargs):
                li = _RecItem(real_cls(*args, **kwargs), state)
                try:
                    li._ops.append(['N', 'ListItem', _plain(list(args)), _plain(kwargs)])
                except Unsupported as exc:
                    state['unsupported'] = 'ListItem(%s)' % exc
                return li
            xg.ListItem = listitem
        if self.labels and ku is not None and hasattr(ku, 'get_infolabel'):
            real_label, labels = ku.get_infolabel, self.labels
            self.saved['ku.get_infolabel'] = real_label
            pinned = lambda name: (labels[name] if name in labels and not state['ended']
                                   else real_label(name))
            ku.get_infolabel = pinned
            self.pinned = (pinned, real_label)
            # POV's menus keep their own alias (get_infolabel =
            # kodi_utils.get_infolabel); with "fast navigation" the add-on's
            # interpreter is reused and those modules stay imported.
            for name in MENU_MODULES:
                menu = sys.modules.get(name)
                if menu is not None and hasattr(menu, 'get_infolabel'):
                    self.menus.append((menu, menu.get_infolabel))
                    menu.get_infolabel = pinned

        def plugin_call(name, original):
            def call(handle, *args, **kwargs):
                if name == 'setResolvedUrl':
                    # Playback, never a list: Kodi gets the real item.
                    state['unsupported'] = 'playback'
                    args = tuple(getattr(a, '_real', a) for a in args)
                    kwargs = {k: getattr(v, '_real', v) for k, v in kwargs.items()}
                    return original(handle, *args, **kwargs)
                if handle != self.handle:
                    return original(handle, *args, **kwargs)
                if name == 'addDirectoryItem' and not args and 'url' in kwargs:
                    # Keyword call (Idan Plus): record it in positional form.
                    args = [kwargs.pop('url'), kwargs.pop('listitem')]
                    if 'isFolder' in kwargs or 'totalItems' in kwargs:
                        args.append(kwargs.pop('isFolder', False))
                    if 'totalItems' in kwargs:
                        args.append(kwargs.pop('totalItems'))
                    args = tuple(args)
                elif name == 'addDirectoryItems' and not args and 'items' in kwargs:
                    args = (kwargs.pop('items'),)
                try:
                    if name == 'addDirectoryItems':
                        rows = [[url, self._index(li), bool(folder)] for url, li, folder in args[0]]
                        self.calls.append([name, [rows], _plain(kwargs)])
                        args = ([(url, li._real, folder) for url, li, folder in args[0]],) + args[1:]
                    elif name == 'addDirectoryItem':
                        url, li = args[0], args[1]
                        self.calls.append([name, [url, self._index(li)] + _plain(list(args[2:])), _plain(kwargs)])
                        args = (url, li._real) + args[2:]
                    else:
                        self.calls.append([name, _plain(list(args)), _plain(kwargs)])
                except Exception as exc:
                    state['unsupported'] = '%s(%s)' % (name, exc)
                    if name == 'addDirectoryItems' and args:
                        args = ([tuple(getattr(v, '_real', v) for v in row) for row in args[0]],) + tuple(args[1:])
                    else:
                        args = tuple(getattr(a, '_real', a) for a in args)
                if name == 'endOfDirectory':
                    state['ended'] = True      # the list goes on screen: real labels again
                if self.shadow:
                    return True
                return original(handle, *args, **kwargs)
            return call

        for name in self.PLUGIN_CALLS:
            if not hasattr(xp, name):
                continue
            self.saved['xp.' + name] = getattr(xp, name)
            setattr(xp, name, plugin_call(name, self.saved['xp.' + name]))

        def util_call(name, original):
            def call(*args, **kwargs):
                try:
                    self.calls.append(['ku.' + name, _plain(list(args)), _plain(kwargs)])
                except Unsupported as exc:
                    state['unsupported'] = '%s(%s)' % (name, exc)
                if self.shadow:
                    return None
                return original(*args, **kwargs)
            return call

        for name in self.UTIL_CALLS:
            if ku is not None and hasattr(ku, name):
                self.saved['ku.' + name] = getattr(ku, name)
                setattr(ku, name, util_call(name, self.saved['ku.' + name]))
        return self

    def stop_listitems(self, reason):
        """From here on the host gets real ListItems (it is about to play
        one); this request is not a list and is never saved."""
        self.state['unsupported'] = reason
        if 'xg.ListItem' in self.saved:
            self.xg.ListItem = self.saved['xg.ListItem']

    def __exit__(self, *exc):
        for menu, real in self.menus:
            menu.get_infolabel = real
        self.menus = []
        if self.pinned:
            # A menu first imported during this build took the pinned alias.
            pinned, real_label = self.pinned
            for name in MENU_MODULES:
                menu = sys.modules.get(name)
                if menu is not None and getattr(menu, 'get_infolabel', None) is pinned:
                    menu.get_infolabel = real_label
            self.pinned = None
        for key, value in self.saved.items():
            owner = {'xp.': self.xp, 'xg.': self.xg, 'ku.': self.ku}[key[:3]]
            setattr(owner, key[3:], value)
        self.saved = {}
        return False

    def snapshot(self, deps):
        ended = any(c[0] == 'endOfDirectory' for c in self.calls)
        if self.state['unsupported'] or not ended or not self.items or not _trusted(deps):
            return None
        return {'format': FORMAT, 'created': time.time(), 'day': _today(), 'deps': deps,
                'items': self.items, 'calls': self.calls}


class BadRecord(Exception):
    """The saved record cannot be replayed; nothing was sent to Kodi yet."""


def replay(snap, handle, kodi_utils, xbmc, xbmcgui, xbmcplugin, widget=False):
    """kodi_utils may be a zero-argument loader: POV's view-mode helpers run
    after endOfDirectory, so the list is on screen before POV is imported.
    Everything is built and checked before the first call reaches Kodi: a
    damaged record raises BadRecord and the list is simply built as usual."""
    try:
        items = [_build(ops, xbmc, xbmcgui) for ops in snap['items']]
        for name, args, kwargs in snap['calls']:
            if not isinstance(args, list) or not isinstance(kwargs, dict):
                raise ValueError(name)
            if name == 'addDirectoryItems':
                [items[row[1]] for row in args[0]]
            elif name == 'addDirectoryItem':
                items[args[1]]
    except Exception as exc:
        raise BadRecord('%s: %s' % (type(exc).__name__, exc))
    pending = []        # consecutive single items, sent as one addDirectoryItems call
    for name, args, kwargs in snap['calls']:
        args, kwargs = _live(args, xbmc), _live(kwargs, xbmc)
        if name == 'addDirectoryItem' and len(args) <= 3 and not kwargs:
            pending.append((args[0], items[args[1]], bool(args[2]) if len(args) > 2 else False))
            continue
        if pending:
            xbmcplugin.addDirectoryItems(handle, pending, len(pending))
            pending = []
        if name == 'addDirectoryItems':
            xbmcplugin.addDirectoryItems(handle, [(url, items[i], folder) for url, i, folder in args[0]], **kwargs)
        elif name == 'addDirectoryItem':
            xbmcplugin.addDirectoryItem(handle, args[0], items[args[1]], *args[2:], **kwargs)
        elif name.startswith('ku.'):
            is_widget = args[2] if len(args) > 2 else kwargs.get('is_widget')
            if name == 'ku.set_view_mode' and (is_widget is True or (
                    is_widget is None and widget and xbmcgui.getCurrentWindowId() != 10025)):
                continue      # POV returns at once for home rows; importing it costs ~0.6 s
            if callable(kodi_utils) and not hasattr(kodi_utils, name[3:]):
                kodi_utils = kodi_utils()
            getattr(kodi_utils, name[3:])(*args, **kwargs)
        else:
            getattr(xbmcplugin, name)(handle, *args, **kwargs)
    if pending:
        xbmcplugin.addDirectoryItems(handle, pending, len(pending))
    return len(items)


# ------------------------------------------------------------------ install --

ROWS_PROPERTY = 'povil.rows.last'
PLAY_PROPERTY = 'povil.play.started'   # pov_play_guard.PROPERTY
PLAY_WINDOW_S = 60.0


def stamp(xbmcgui):
    """Tell the build's own services a list was just served: they hold
    their start-up work until the home rows stop arriving (shared CPU)."""
    try:
        xbmcgui.Window(10000).setProperty(ROWS_PROPERTY, '%.3f' % time.time())
    except Exception:
        pass


def _wait_rows_quiet(xbmc, quiet=1.5, cap=20.0):
    """Before rebuilding a list that is already on screen: let the other home
    rows load first (they share one CPU), and skip it while a video plays or
    an episode is starting (its source search needs the CPU; the old copy
    stays until the next visit). False: do not rebuild now."""
    try:
        import xbmcgui
        win = xbmcgui.Window(10000)
        monitor = xbmc.Monitor()
    except Exception:
        return True
    start = time.time()
    while time.time() - start < cap:
        if _play_starting(win):
            return False
        try:
            last = float(win.getProperty(ROWS_PROPERTY) or 0)
        except ValueError:
            last = 0.0
        if time.time() - last >= quiet:
            break
        if monitor.waitForAbort(0.25):
            return False
    if _play_starting(win):
        return False
    try:
        return not xbmc.Player().isPlayingVideo()
    except Exception:
        return True


def _play_starting(win):
    """An episode or movie was picked less than a minute ago and is still
    looking for sources (pov_play_guard sets the mark; it is cleared once the
    request ends or a video plays)."""
    try:
        started = float(win.getProperty(PLAY_PROPERTY) or 0)
    except ValueError:
        return False
    return 0 <= time.time() - started < PLAY_WINDOW_S


def _discard(path, xbmc):
    try:
        os.remove(path)
    except OSError:
        pass
    xbmc.log('[POV IL snapshot] damaged record removed; building the list', xbmc.LOGWARNING)


def _adult_profile():
    try:
        import profile_age_guard
        return profile_age_guard.active_policy() is None
    except Exception:
        return False


# handle -> the stale copy serve_early() already put on screen; the route then
# only rebuilds it (same interpreter: router.py's hook and POV share modules).
EARLY = {}


def _watch_only_change(old, new):
    """True when the only dependencies that differ are watch-state marks
    (watched/progress in POV's, Trakt's and MDBList's databases)."""
    if not isinstance(old, dict) or not isinstance(new, dict):
        return False
    changed = {k for k in set(old) | set(new) if old.get(k) != new.get(k)}
    return bool(changed) and changed <= set(WATCH_DBS)


def _stale(snap, age, personal):
    return age >= (PERSONAL_TTL_S if personal else GENERAL_TTL_S) or snap.get('day') != _today()


def _same(a, b):
    return a['items'] == b['items'] and a['calls'] == b['calls']


REFRESHED_PROPERTY = 'povil.rows.refreshed'


def _refresh_widgets(xbmc, saved_at):
    """POV's widget_refresh(), once for every row that changed around the
    same time: each refresh asks every home row again."""
    try:
        import xbmcgui
        win = xbmcgui.Window(10000)
        monitor = xbmc.Monitor()
    except Exception:
        win = monitor = None
    if win is not None:
        if monitor.waitForAbort(1.0):
            return 'abort'
        try:
            if float(win.getProperty(REFRESHED_PROPERTY) or 0) >= saved_at:
                return 'joined'          # another row's refresh already covers this one
        except ValueError:
            pass
        win.setProperty(REFRESHED_PROPERTY, repr(time.time()))
    xbmc.executebuiltin('UpdateLibrary(video,special://skin/foo)')
    return 'widgets'


def _refresh_shown(xbmc, argv, context, saved_at=None):
    """The rebuilt list differs from the copy on screen: show the new one --
    the open list (also when a home tile opened it) or the home rows."""
    shown = xbmc.getInfoLabel('Container.FolderPath')
    if shown and shown.rstrip('/') == (argv[0] + (argv[2] if len(argv) > 2 else '')).rstrip('/'):
        xbmc.executebuiltin('Container.Refresh')
        return 'container'
    if context[0]:
        return _refresh_widgets(xbmc, time.time() if saved_at is None else saved_at)
    return 'none'


def _query(argv):
    """mode/action/exit_list_params without importing urllib (and re): None
    when they are percent-encoded, so the normal route decides instead."""
    out = {}
    for part in (argv[2] if len(argv) > 2 else '').lstrip('?').split('&'):
        name, _, value = part.partition('=')
        if name:
            out[name] = value
    if any(c in out.get(k, '') for k in ('mode', 'action') for c in '%+'):
        return None
    return out


def _adult_fast(xbmc, xbmcvfs):
    """profile_age_guard.active_policy() is None, decided without importing
    it (json, re, urllib) where that is certain: no profile policy or child
    marker anywhere, so only the skin's child flag decides. None: undecided."""
    master = os.path.realpath(xbmcvfs.translatePath('special://masterprofile/'))
    active = os.path.realpath(xbmcvfs.translatePath('special://profile/'))
    if master != active and (os.path.isfile(os.path.join(master, GUARD_POLICY_FILE)) or
                             os.path.isfile(os.path.join(active, GUARD_CHILD_MARKER))):
        return None
    return not xbmc.getCondVisibility('Skin.HasSetting(POVILChild)')


def serve_early(argv):
    """From POV's router.py, BEFORE POV is imported: True when a fresh saved
    list was shown (the caller exits), False to continue as usual. Importing
    POV's entry costs 0.3-2.5 s per row on a busy Android box at start-up --
    more than the replay itself. An old copy (yesterday's, the first click
    after Kodi starts) is shown here too; False then lets POV load and
    rebuild it behind the scenes (EARLY)."""
    begun = time.perf_counter()
    try:
        import xbmc, xbmcgui, xbmcplugin, xbmcvfs, xbmcaddon
        argv = list(argv)
        params = _query(argv)
        handle = int(argv[1]) if len(argv) > 1 else -1
        if (params is None or handle < 0 or not eligible(params)
                or os.path.exists(xbmcvfs.translatePath(KILL_SWITCH))):
            return False
        adult = _adult_fast(xbmc, xbmcvfs)
        if not (_adult_profile() if adult is None else adult):
            return False
        profile = _profile_dir(xbmcvfs)
        personal = _personal(params)
        labels = _labels(xbmc, argv)
        path, raw = _path(profile, argv, _versions(xbmcaddon), _context(labels, params))
        now = time.time()
        sig = _stat_sig(profile, now)
        snap = read(path, raw)
        age = _age(snap, now) if snap is not None else None
        if age is None:
            return False      # missing or too old: the normal route builds it
        checked = None
        watch_changed = False
        if not proven(snap, sig, now):
            fresh = None
            if sig is not None and snap.get('sig') is not None and isinstance(snap.get('deps'), dict):
                # Only what the changed files feed (often just POV's list
                # cache) -- plus the list rows once they have expired.
                fresh = _changed_keys(snap['sig'], sig, snap['deps'])
                if snap.get('expires') is not None and now >= snap['expires']:
                    fresh |= {'list', 'tmdblist'}
            deps, sig = _settled_sig(profile, lambda: _deps(profile, params, snap.get('deps'), fresh))
            if not _trusted(deps):
                return False
            if snap.get('deps') != deps:
                if not _watch_only_change(snap.get('deps'), deps):
                    return False  # changed: the normal route builds it
                watch_changed = True  # shown now, rebuilt and refreshed right after
            else:
                checked = (deps, sig)
        stale = watch_changed or _stale(snap, age, personal)
    except Exception:
        return False
    started = time.perf_counter()

    def pov_utils():
        from modules import kodi_utils
        return kodi_utils
    try:
        count = replay(snap, handle, pov_utils, xbmc, xbmcgui, xbmcplugin, widget=_context(labels, params)[0])
    except BadRecord:
        _discard(path, xbmc)
        return False          # nothing sent: POV builds it as usual
    except Exception as exc:
        try:
            os.remove(path)
        except OSError:
            pass
        xbmc.log('[POV IL snapshot] early replay failed: %s' % type(exc).__name__, xbmc.LOGWARNING)
        return True           # this handle was already answered (partly)
    stamp(xbmcgui)
    xbmc.log('[POV IL snapshot] hit early mode=%s items=%d age_s=%d ms=%d check_ms=%d%s%s' % (
        params.get('mode'), count, age, round((time.perf_counter() - started) * 1000),
        round((started - begun) * 1000), ' (files)' if checked is None else ' (content)',
        ' (refreshing)' if stale else ''), xbmc.LOGINFO)
    if checked is not None and checked[1] is not None and not stale:
        # Same content, newer file times: record them so the next visit is
        # proven by the files alone. Already on screen; best effort.
        try:
            snap['sig'], snap['expires'] = checked[1], _expiry(checked[0])
            save(path, snap)
        except Exception:
            pass
    if stale:
        if not _wait_rows_quiet(xbmc):
            return True       # shown; rebuilt on a later visit
        EARLY[handle] = (snap, labels)
        return False          # POV loads and rebuilds it; nothing more is shown
    return True


IDANPLUS = 'plugin.video.idanplus'
# Idan Plus lists come from the broadcasters' sites (no local dependency to
# watch), so its saved rows work as "show, then refresh": shown at once, and
# rebuilt behind the scenes once older than this or after a change to Idan
# Plus's own data.
IDANPLUS_FRESH_S = 6 * 3600       # broadcasters' programme lists change slowly
IDANPLUS_LIVE_FRESH_S = 2 * 60      # live TV/radio rows show what is on now
# Listings only (no playback, dialogs, favourites editing or channel edits).
IDANPLUS_LIST_MODES = frozenset(('-1', '1', '2', '3', '10', '12', '13', '14'))


# Idan Plus's own data a row is built from: settings, favourites (mode 10),
# the channel list and the user's channel edits (order, names, logos).
IDANPLUS_FILES = ('settings.xml', 'favorites.json', 'channels.json', 'displayChannels.json')


def _idanplus_deps(profile):
    deps = {}
    for name in IDANPLUS_FILES:
        try:
            with open(os.path.join(profile, name), 'rb') as fh:
                deps[name] = _crc(fh.read())
        except OSError:
            deps[name] = None
    try:
        logos = os.path.join(profile, 'logos')
        deps['logos'] = _crc(repr(sorted((n, os.stat(os.path.join(logos, n)).st_mtime_ns)
                                         for n in os.listdir(logos))).encode('utf-8'))
    except OSError:
        deps['logos'] = None
    return deps


def _idanplus_eligible(params):
    if params.get('module'):
        return True     # a broadcaster's listing; its playback items never end a directory
    return params.get('mode', '-1') in IDANPLUS_LIST_MODES


def idanplus(argv):
    """From Idan Plus's default.py (after its child-profile guard): serve a
    home row from the copy saved last time and/or build it under the
    recorder. True when this request was answered here (the caller exits);
    False for everything else -- full-screen browsing, searches, playback --
    which runs exactly as before."""
    begun = time.perf_counter()
    try:
        import xbmc, xbmcgui, xbmcplugin, xbmcvfs, xbmcaddon
        argv = list(argv)
        handle = int(argv[1]) if len(argv) > 1 else -1
        query = argv[2] if len(argv) > 2 else ''
        params = _query([None, None, query]) or {}
        if (handle < 0 or 'search' in query.lower() or not _idanplus_eligible(params)
                or os.path.exists(xbmcvfs.translatePath(KILL_SWITCH))):
            return False
        labels = _labels(xbmc)
        if 'idanplus' in labels['Container.PluginName']:
            return False      # browsing Idan Plus itself: not a home row
        adult = _adult_fast(xbmc, xbmcvfs)
        if not (_adult_profile() if adult is None else adult):
            return False
        profile = xbmcvfs.translatePath('special://profile/addon_data/%s/' % IDANPLUS)
        versions = [xbmcaddon.Addon(IDANPLUS).getAddonInfo('version'),
                    xbmcaddon.Addon('plugin.program.kodipovilwizard').getAddonInfo('version')]
        path, raw = _path(profile, argv, versions, ['idanplus-row', 2])   # 2: per-item records
        deps = _idanplus_deps(profile)
        now = time.time()
        snap = read(path, raw)
        age = _age(snap, now) if snap is not None else None
    except Exception:
        return False
    shown = None
    if age is not None:
        started = time.perf_counter()
        try:
            count = replay(snap, handle, None, xbmc, xbmcgui, xbmcplugin, widget=True)
        except BadRecord:
            _discard(path, xbmc)
            age = None        # nothing sent: build it below as usual
        except Exception as exc:
            try:
                os.remove(path)
            except OSError:
                pass
            xbmc.log('[POV IL snapshot] idanplus replay failed: %s' % type(exc).__name__, xbmc.LOGWARNING)
            return True
    if age is not None:
        stamp(xbmcgui)
        limit = IDANPLUS_LIVE_FRESH_S if params.get('mode') in ('1', '3') and not params.get('module') \
            else IDANPLUS_FRESH_S
        fresh = age < limit and snap.get('deps') == deps
        xbmc.log('[POV IL snapshot] hit idanplus items=%d age_s=%d ms=%d check_ms=%d%s' % (
            count, age, round((time.perf_counter() - started) * 1000),
            round((started - begun) * 1000), '' if fresh else ' (refreshing)'), xbmc.LOGINFO)
        if fresh or not _wait_rows_quiet(xbmc):
            return True
        shown = snap
    from resources.main import route
    from resources.lib import common as idan_common
    recorder = Recorder(None, xbmcplugin, xbmcgui, handle, shadow=shown is not None,
                        listitem_class=True)
    play_stream = idan_common.PlayStream

    def playing(*args, **kwargs):
        recorder.stop_listitems('playback')
        return play_stream(*args, **kwargs)
    idan_common.PlayStream = playing
    try:
        with recorder:
            try:
                route(argv[2])
            except Exception:
                if shown is None:
                    raise
    finally:
        idan_common.PlayStream = play_stream
    if shown is None:
        stamp(xbmcgui)
    try:
        new = recorder.snapshot(deps)
        if new is not None:
            new.update(key=raw, sig=None, expires=None)
            prev = read(path, raw)
            # The same row asked twice (Kodi loads the home twice after a
            # profile login): the first rebuild already refreshed the rows.
            done = (shown is not None and prev is not None and
                    prev.get('created', 0) > shown.get('created', 0) and _same(prev, new))
            save(path, new)
            saved_at = time.time()          # the refresh must come after the file is in place
            if shown is not None and not done and not _same(new, shown):
                how = _refresh_widgets(xbmc, saved_at)
                xbmc.log('[POV IL snapshot] changed idanplus refresh=%s' % how, xbmc.LOGINFO)
        elif recorder.state['unsupported']:
            xbmc.log('[POV IL snapshot] idanplus not saved: %s' % recorder.state['unsupported'][:80],
                     xbmc.LOGINFO)
    except Exception:
        pass
    return True


# Built ahead of a first visit: POV's catalogue lists (not personal ones,
# searches or episode lists), at most this many children per menu.
PREBUILD_PER_MENU = 40
PREBUILD_IDLE_S = 15
# Targets tried this session (argv2 + screen -> time). A list that saves
# nothing (empty, an expired account, offline) must not be requested again on
# every idle poll and hold up the others.
_TRIED = {}
PREBUILD_RETRY_S = 3600
HOME_LABELS = {'Container.PluginName': '', 'Container.FolderPath': ''}
_SKIN_URLS = {}


def _children(snap):
    """Folder entries of a saved list: (argv0, argv2) of each."""
    out = []
    for name, args, _kwargs in snap.get('calls', ()):
        rows = args[0] if name == 'addDirectoryItems' else ([[args[0], None, args[2]]]
                                                              if name == 'addDirectoryItem' and len(args) > 2 else [])
        for url, _index, folder in rows:
            if folder and isinstance(url, str) and url.startswith('plugin://plugin.video.pov/?'):
                out.append(('plugin://plugin.video.pov/', url[len('plugin://plugin.video.pov/'):]))
    return out


def _prebuild_eligible(argv2):
    # Episode lists (next/in-progress) are left out: they follow the date and
    # every watch, and Kodi stalled fetching them over JSON-RPC in QA.
    params = _query([None, None, argv2])
    if not params or not eligible(params):
        return False
    return params.get('mode') in NAVIGATOR_MODES or params.get('mode') in ('build_movie_list', 'build_tvshow_list')


def skin_targets(skin_dir):
    """POV lists the active skin opens from its home screen (rows and tiles),
    read once per skin version from its XML."""
    import re
    try:
        stamp = os.path.getmtime(os.path.join(skin_dir, 'addon.xml'))
    except OSError:
        return []
    cached = _SKIN_URLS.get(skin_dir)
    if cached and cached[0] == stamp:
        return cached[1]
    found = []
    pattern = re.compile(r'plugin://plugin\.video\.pov/(\?[^"<\s,)]+)')
    for root, _dirs, files in os.walk(skin_dir):
        for name in files:
            if not name.endswith('.xml'):
                continue
            try:
                with open(os.path.join(root, name), encoding='utf-8', errors='replace') as fh:
                    text = fh.read()
            except OSError:
                continue
            for argv2 in pattern.findall(text):
                argv2 = argv2.replace('&amp;', '&')
                if '$' not in argv2 and '[' not in argv2 and argv2 not in found:
                    found.append(argv2)
    _SKIN_URLS[skin_dir] = (stamp, found)
    return found


def prebuild_targets(profile, versions, limit=PREBUILD_PER_MENU, skin_dir=None):
    """Lists with no saved copy yet, each with the screen it would be opened
    from: the skin's home rows and tiles (the home screen), and the entries
    of saved POV menus (the menu itself, in the Videos window)."""
    import ast
    folder = _store_dir(profile)
    try:
        names = [n for n in os.listdir(folder) if n.endswith(SUFFIX)]
    except OSError:
        names = []
    index = os.path.join(folder, MENUS_INDEX)
    if names and not os.path.exists(index):
        # Records saved before the index existed: find the menus once.
        found = []
        for name in names:
            try:
                with open(os.path.join(folder, name), 'rb') as fh:
                    data = fh.read()
                snap = marshal.loads(zlib.decompress(data[1:]) if data[:1] == b'Z' else data)
                if (_query([None, None, ast.literal_eval(snap['key'])[2]]) or {}).get(
                        'mode', '').startswith('navigator.'):
                    found.append(name)
            except Exception:
                continue
        try:
            with open(index, 'w', encoding='utf-8') as fh:
                fh.write(''.join(n + '\n' for n in found))
        except OSError:
            pass
    try:
        with open(index, 'r', encoding='utf-8') as fh:
            menus = sorted(set(fh.read().split()) & set(names))
    except OSError:
        menus = []
    targets, seen = [], set()
    # The skin's own home rows and tiles, opened from the home screen.
    for argv2 in (skin_targets(skin_dir) if skin_dir else [])[:60]:
        if not _prebuild_eligible(argv2) or ('', argv2) in seen:
            continue
        seen.add(('', argv2))
        child, _raw = _path(profile, ['plugin://plugin.video.pov/', '0', argv2], versions,
                            _context(HOME_LABELS, _query([None, None, argv2]) or {}))
        if not os.path.exists(child):
            targets.append(('plugin://plugin.video.pov/' + argv2, argv2, dict(HOME_LABELS)))
    for name in menus:
        path = os.path.join(folder, name)
        try:
            with open(path, 'rb') as fh:
                data = fh.read()
            snap = marshal.loads(zlib.decompress(data[1:]) if data[:1] == b'Z' else data)
            key = ast.literal_eval(snap['key'])
        except Exception:
            continue
        parent_argv2 = key[2]
        if not (_query([None, None, parent_argv2]) or {}).get('mode', '').startswith('navigator.'):
            continue
        parent = key[1] + parent_argv2
        for argv0, argv2 in _children(snap)[:limit]:
            if (argv0, argv2, parent) in seen or not _prebuild_eligible(argv2):
                continue
            seen.add((argv0, argv2, parent))
            labels = {'Container.PluginName': 'plugin.video.pov', 'Container.FolderPath': parent}
            child, _raw = _path(profile, [argv0, '0', argv2], versions,
                                _context(labels, _query([None, None, argv2]) or {}))
            if not os.path.exists(child):
                targets.append((argv0 + argv2, argv2, labels))
    return targets, len(names)


def resign(profile, limit=40, budget_s=3.0):
    """Records whose dependency files were written since they were checked
    (Trakt syncs, POV's caches, settings saved on exit) pay the content check
    on their next visit -- half a second each for the first home rows on a
    phone at start-up. While Kodi is idle, check them now and record the new
    file times when nothing really changed. Returns how many were updated."""
    import ast
    folder = _store_dir(profile)
    try:
        names = sorted((n for n in os.listdir(folder) if n.endswith(SUFFIX)),
                       key=lambda n: os.path.getmtime(os.path.join(folder, n)), reverse=True)[:limit]
    except OSError:
        return 0
    started, done = time.time(), 0
    for name in names:
        if time.time() - started > budget_s:
            break
        path = os.path.join(folder, name)
        try:
            with open(path, 'rb') as fh:
                data = fh.read()
            snap = marshal.loads(zlib.decompress(data[1:]) if data[:1] == b'Z' else data)
            if snap.get('format') != FORMAT or 'deps' not in snap:
                continue
            if proven(snap, _stat_sig(profile)):
                continue
            params = _query([None, None, ast.literal_eval(snap['key'])[2]]) or {}
            deps, sig = _settled_sig(profile, lambda: _deps(profile, params))
            if sig is not None and _trusted(deps) and deps == snap['deps']:
                snap['sig'], snap['expires'] = sig, _expiry(deps)
                save(path, snap)
                done += 1
        except Exception:
            continue
    return done


def prebuild_tick(xbmc, budget=1):
    """From the Wizard's idle loop: build up to `budget` lists ahead of their
    first visit, while Kodi is idle (no video, no key press for a while).
    Returns how many were requested."""
    try:
        import xbmcaddon, xbmcgui, xbmcvfs
        if (xbmc.Player().isPlayingVideo() or xbmc.getGlobalIdleTime() < PREBUILD_IDLE_S
                or os.path.exists(xbmcvfs.translatePath(KILL_SWITCH)) or not _adult_profile()):
            return 0
        win = xbmcgui.Window(10000)
        profile = _profile_dir(xbmcvfs)
        if time.time() >= _float(win.getProperty(PREBUILD_PROPERTY + '.signed')):
            # Re-check saved lists whose files changed since (a sync, a cache
            # write), so the next start shows them by file times alone.
            win.setProperty(PREBUILD_PROPERTY + '.signed', repr(time.time() + 600))
            resign(profile)
        if time.time() < _float(win.getProperty(PREBUILD_PROPERTY + '.next')):
            return 0              # nothing was left to build a few minutes ago
        targets, count = prebuild_targets(profile, _versions(xbmcaddon),
                                          skin_dir=xbmcvfs.translatePath('special://skin/'))
        if count >= PREBUILD_MAX_FILES or not targets:
            win.setProperty(PREBUILD_PROPERTY + '.next', repr(time.time() + 600))
            return 0
        done = 0
        now = time.time()
        fresh_targets = [t for t in targets
                         if now - _TRIED.get((t[1], t[2]['Container.FolderPath']), 0) > PREBUILD_RETRY_S]
        if not fresh_targets:
            win.setProperty(PREBUILD_PROPERTY + '.next', repr(time.time() + 600))
            return 0
        for url, argv2, labels in fresh_targets[:budget]:
            _TRIED[(argv2, labels['Container.FolderPath'])] = time.time()
            win.setProperty(PREBUILD_PROPERTY, '\x1f'.join((
                repr(time.time() + 30), argv2, labels['Container.PluginName'],
                labels['Container.FolderPath'])))
            try:
                xbmc.executeJSONRPC('{"jsonrpc": "2.0", "id": 1, "method": "Files.GetDirectory", '
                                    '"params": {"directory": %s, "media": "files"}}' % _json_string(url))
            finally:
                win.clearProperty(PREBUILD_PROPERTY)
            done += 1
            xbmc.log('[POV IL snapshot] prebuilt %s' % (_query([None, None, argv2]) or {}).get('mode'),
                     xbmc.LOGINFO)
        return done
    except Exception as exc:
        try:
            xbmc.log('[POV IL snapshot] prebuild skipped: %s' % type(exc).__name__, xbmc.LOGWARNING)
        except Exception:
            pass
        return 0


def _float(text):
    try:
        return float(text or 0)
    except ValueError:
        return 0.0


def _json_string(text):
    import json
    return json.dumps(text)


def wrap(original, native):
    """routing(sys_obj) that serves saved lists; install() order: before the
    latency wrapper, so timing lines also measure replays."""
    if getattr(original, '_povil_snapshot', False):
        return original

    def routing(sys_obj):
        try:
            import xbmc, xbmcgui, xbmcplugin, xbmcvfs, xbmcaddon
            ku = native['kodi_utils']
            argv = list(sys_obj.argv)
            params = ku.parsed_query(argv[2]) if len(argv) > 2 else {}
            handle = int(argv[1]) if len(argv) > 1 else -1
        except Exception:
            return original(sys_obj)
        if (handle < 0 or not eligible(params) or os.path.exists(xbmcvfs.translatePath(KILL_SWITCH))
                or not _adult_profile()):
            return original(sys_obj)
        early = EARLY.pop(handle, None)
        watch_stale = False
        try:
            profile = _profile_dir(xbmcvfs)
            personal = _personal(params)
            # After serve_early() the copy is on screen and the labels show
            # it, so the rebuild uses what was read before it was shown.
            labels = early[1] if early else _labels(xbmc, argv, consume=True)
            context = _context(labels, params)
            deps = _deps(profile, params)
            path, raw = _path(profile, argv, _versions(xbmcaddon), context)
            snap, age = (None, None) if early else load(path, raw, deps)
            if snap is None and not early and _trusted(deps):
                # Only the watch state changed (an episode was just watched and
                # Kodi returns to this list): show the saved copy at once and
                # rebuild it right after -- it refreshes in place.
                old = read(path, raw)
                old_age = _age(old, time.time()) if old is not None else None
                if old_age is not None and _watch_only_change(old.get('deps'), deps):
                    snap, age, watch_stale = old, old_age, True
        except Exception:
            snap, age, path, context, labels = None, None, None, None, None
        shadow = False
        shown = None
        if early is not None:
            if not path:
                return None    # shown already and nothing to rebuild with
            shadow = True      # serve_early() showed the old copy; only rebuild
            shown = early[0]
        elif snap is not None:
            started = time.perf_counter()
            try:
                count = replay(snap, handle, ku, xbmc, xbmcgui, xbmcplugin, widget=context[0])
            except BadRecord:
                _discard(path, xbmc)
                snap = count = None   # nothing sent: build it as usual
            except Exception as exc:
                # A partial replay already talked to Kodi for this handle;
                # drop the record and let Kodi's next request build it fresh.
                try:
                    os.remove(path)
                except OSError:
                    pass
                xbmc.log('[POV IL snapshot] replay failed: %s' % type(exc).__name__, xbmc.LOGWARNING)
                return None
            if snap is not None:
                stale = watch_stale or _stale(snap, age, personal)
                stamp(xbmcgui)
                xbmc.log('[POV IL snapshot] hit mode=%s items=%d age_s=%d ms=%d%s' % (
                    params.get('mode'), count, age, round((time.perf_counter() - started) * 1000),
                    ' (refreshing)' if stale else ''), xbmc.LOGINFO)
                if not stale:
                    return None
                if not _wait_rows_quiet(xbmc):
                    return None
                shadow = True      # shown already; rebuild today's list
                shown = snap
        recorder = Recorder(ku, xbmcplugin, xbmcgui, handle, shadow=shadow, labels=labels)
        with recorder:
            try:
                result = original(sys_obj)
            except Exception:
                if not shadow:
                    raise
                result = None
        if not shadow:
            stamp(xbmcgui)
        try:
            # Taken after the build: POV writes its own caches while building.
            new = None
            if path:
                deps, sig = _settled_sig(profile, lambda: _deps(profile, params))
                new = recorder.snapshot(deps)
                if new is not None:
                    new.update(key=raw, sig=sig, expires=_expiry(deps),
                               menu=(params.get('mode') or '').startswith('navigator.'))
            if new is not None:
                prev = read(path, raw)
                # Another request may have rebuilt (and refreshed) this list
                # meanwhile -- e.g. a home row asked for twice at start-up.
                done = (shown is not None and isinstance(prev, dict) and
                        prev.get('created', 0) > shown.get('created', 0) and _same(prev, new))
                save(path, new)
                saved_at = time.time()      # the refresh must come after the file is in place
                if shown is not None and not done and not _same(new, shown):
                    how = _refresh_shown(xbmc, argv, context, saved_at)
                    xbmc.log('[POV IL snapshot] changed mode=%s refresh=%s' % (params.get('mode'), how), xbmc.LOGINFO)
            elif recorder.state['unsupported']:
                xbmc.log('[POV IL snapshot] not saved: %s' % recorder.state['unsupported'][:80], xbmc.LOGINFO)
        except Exception:
            pass
        return result
    routing._povil_snapshot = True
    return routing
