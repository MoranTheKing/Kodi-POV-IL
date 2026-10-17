"""Open POV lists from the finished list saved last time ("saved lists").

Every POV list -- home rows, tiles, categories, "Continue watching" -- is built
from scratch on each visit: per-title metadata from SQLite in ~20 threads,
then ~60 ListItem/InfoTag calls per title. On an Android box that is 0.6-3 s
per list, and 10 s for "Continue watching" right after Kodi starts while a
dozen add-on services start beside it (field logs, Oct 2026).

A list built normally is RECORDED: every ListItem/InfoTag call POV makes and
every xbmcplugin call for the handle, in order, as plain JSON. The next visit
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
* while merely old (up to 24 hours -- e.g. the first list after Kodi starts
  in the morning) or saved on an earlier day (next/in-progress episodes
  depend on the date) it is shown at once AND rebuilt right after, in the
  same call; when the rebuilt list differs, the open list or the home rows
  refresh themselves (POV's own widget refresh), already from the new copy;
* older than that, the list is built as before.
Search/discover routes and child profiles are never saved. Anything the
recorder cannot reproduce exactly (an unknown argument type, a ListItem it did
not create) leaves the list unsaved: it simply keeps working as before.
"""
import hashlib
import json
import os
import sys
import time

FORMAT = 3
ROUTES = frozenset(('build_movie_list', 'build_tvshow_list',
                    'build_next_episode', 'build_in_progress_episode'))
GENERAL_TTL_S = 3 * 3600
PERSONAL_TTL_S = 30 * 60
MAX_AGE_S = 24 * 3600
MAX_FILES = 100
# What a list depends on, by CONTENT: Kodi and POV's syncs rewrite these files
# at every start without changing them, so file times would discard every
# saved list. Watch state = row count, last row and last watch per table.
WATCH_DBS = ('watched.db', 'traktcache.db', 'mdblcache.db')
WATCH_TABLES = ('watched_status', 'progress', 'dropped', 'favorites')
HASHED_FILES = ('settings.xml', 'povil_dropped_trakt.json', 'povil_dropped_mdblist.json')
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
_LISTITEM_RECORDED = ('set', 'add', 'select')


class Unsupported(Exception):
    pass


def _plain(value):
    """JSON-safe copy of a call argument, or Unsupported."""
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


def _personal(params):
    mode = params.get('mode', '')
    action = params.get('action', '') or ''
    return mode in ('build_next_episode', 'build_in_progress_episode') or action.startswith(PERSONAL_PREFIXES)


def _account_list(params):
    action = params.get('action', '') or ''
    return params.get('mode') in ('build_movie_list', 'build_tvshow_list') and action.startswith(PERSONAL_PREFIXES)


def eligible(params):
    if params.get('mode') not in ROUTES:
        return False
    action = (params.get('action') or '')
    return not any(word in action for word in ('search', 'discover'))


def _table_marks(con, table):
    cols = [r[1] for r in con.execute('PRAGMA table_info("%s")' % table)]
    if not cols:
        return None
    extra = ', max(last_played)' if 'last_played' in cols else ''
    return list(con.execute('SELECT count(*), max(rowid)%s FROM "%s"' % (extra, table)).fetchone())


def _db_marks(path, tables, hidden=False):
    import sqlite3
    if not os.path.isfile(path):
        return None
    con = sqlite3.connect(path, timeout=2)
    try:
        out = {t: _table_marks(con, t) for t in tables}
        if hidden:
            # Trakt shows hidden from progress steer "Continue watching".
            rows = con.execute("SELECT id, data FROM trakt_data WHERE id LIKE '%hidden%' ORDER BY id").fetchall()
            out['hidden'] = hashlib.sha1(json.dumps(rows).encode('utf-8')).hexdigest()
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
    import sqlite3
    if not os.path.isfile(path):
        return None
    pattern = action.replace('\\', '\\\\').replace('_', '\\_').replace('%', '\\%') + '\\_%'
    con = sqlite3.connect(path, timeout=2)
    try:
        return [list(r) for r in con.execute(
            "SELECT id, expires FROM maincache WHERE id LIKE ? ESCAPE '\\' AND expires > ? ORDER BY id",
            (pattern, int(time.time())))]
    except sqlite3.Error:
        return 'error'
    finally:
        con.close()


def _deps(profile, params):
    out = {}
    action = params.get('action') or ''
    if action:
        out['list'] = _list_marks(os.path.join(profile, 'maincache.db'), action)
        if action.startswith(('tmdb_watchlist', 'tmdb_favorites', 'tmdb_recommendations')):
            out['tmdblist'] = _list_marks(os.path.join(profile, 'maincache.db'), TMDB_ACCOUNT_CACHE)
    for name in HASHED_FILES:
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
                raw = json.dumps(json.loads(raw.decode('utf-8')).get('items')).encode('utf-8')
            except (ValueError, AttributeError, UnicodeDecodeError):
                pass
        out[name] = hashlib.sha1(raw).hexdigest()
    for name in WATCH_DBS:
        out[name] = _db_marks(os.path.join(profile, name), WATCH_TABLES,
                              hidden=(name == 'traktcache.db'))
    if _account_list(params):
        for name, table in ACCOUNT_CACHES:
            out[name + ':' + table] = _db_marks(os.path.join(profile, name), (table,))
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


def _labels(xbmc):
    """What POV reads from the screen while it builds a list:
    * Container.PluginName -- external_browse(): a home row or another
      add-on's list is built differently (context menus, hidden watched
      titles, view mode, paging);
    * Container.FolderPath -- full-screen lists keep it as their way back
      (exit_list_params) unless the request already carries one.
    Read once per request; the build sees exactly these values (Recorder
    pins them until endOfDirectory), because Kodi switches both the moment
    a list -- or a saved copy -- reaches the screen."""
    return {name: xbmc.getInfoLabel(name) for name in PINNED_LABELS}


def _context(labels, params):
    widget = 'pov' not in labels['Container.PluginName']
    folder = '' if params.get('exit_list_params') else labels['Container.FolderPath']
    return [widget, folder]


def _key(argv, versions, context):
    raw = json.dumps([FORMAT, argv[0], argv[2] if len(argv) > 2 else '', versions, context])
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()


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


def load(path, deps, now=None):
    """(snapshot, age_s) when the saved list may be shown, else (None, None)."""
    now = time.time() if now is None else now
    if not _trusted(deps):
        return None, None
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            snap = json.load(fh)
    except (OSError, ValueError):
        return None, None
    if not isinstance(snap, dict) or snap.get('format') != FORMAT or snap.get('deps') != deps:
        return None, None
    age = now - float(snap.get('created', 0))
    if not 0 <= age < MAX_AGE_S:
        return None, None
    return snap, age


def save(path, snap):
    import tempfile
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix='.tmp', dir=folder)   # two interpreters may save at once
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(snap, fh, separators=(',', ':'))
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    try:
        now = time.time()
        entries = [os.path.join(folder, n) for n in os.listdir(folder)]
        for stray in [e for e in entries if e.endswith('.tmp') and now - os.path.getmtime(e) > 600]:
            os.remove(stray)
        names = [e for e in entries if e.endswith('.json')]
        if len(names) > MAX_FILES:
            for old in sorted(names, key=os.path.getmtime)[:len(names) - MAX_FILES]:
                os.remove(old)
    except OSError:
        pass


# ------------------------------------------------------------ record/replay --

class Recorder(object):
    """Swaps POV's list-building entry points for recording ones."""

    PLUGIN_CALLS = ('addDirectoryItems', 'addDirectoryItem', 'setContent',
                    'setPluginCategory', 'addSortMethod', 'endOfDirectory')
    UTIL_CALLS = ('set_view_mode', 'focus_index')

    def __init__(self, kodi_utils, xbmcplugin, xbmcgui, handle, shadow=False, labels=None):
        # shadow: rebuild after a replay already ended this handle -- record
        # only, nothing reaches Kodi. labels: screen labels POV is shown
        # while it builds (see _labels).
        self.ku, self.xp, self.xg, self.handle = kodi_utils, xbmcplugin, xbmcgui, handle
        self.shadow, self.labels = shadow, labels or {}
        self.state = {'unsupported': None, 'ended': False}
        self.items, self.calls, self.saved, self.menus = [], [], {}, []

    def _index(self, li):
        if not isinstance(li, _RecItem):
            raise Unsupported('ListItem not built by make_listitem')
        try:
            return self._ids[id(li)]
        except KeyError:
            self._ids[id(li)] = len(self.items)
            self.items.append(li._ops)
            return self._ids[id(li)]

    def __enter__(self):
        self._ids = {}
        ku, xp, xg, state = self.ku, self.xp, self.xg, self.state
        self.saved['make_listitem'] = ku.make_listitem
        ku.make_listitem = lambda: _RecItem(xg.ListItem(offscreen=True), state)
        if self.labels and hasattr(ku, 'get_infolabel'):
            real_label, labels = ku.get_infolabel, self.labels
            self.saved['ku.get_infolabel'] = real_label
            pinned = lambda name: (labels[name] if name in labels and not state['ended']
                                   else real_label(name))
            ku.get_infolabel = pinned
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
                if handle != self.handle:
                    return original(handle, *args, **kwargs)
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
            if hasattr(ku, name):
                self.saved['ku.' + name] = getattr(ku, name)
                setattr(ku, name, util_call(name, self.saved['ku.' + name]))
        return self

    def __exit__(self, *exc):
        for menu, real in self.menus:
            menu.get_infolabel = real
        self.menus = []
        self.ku.make_listitem = self.saved.pop('make_listitem')
        for key, value in self.saved.items():
            owner, name = (self.xp, key[3:]) if key.startswith('xp.') else (self.ku, key[3:])
            setattr(owner, name, value)
        self.saved = {}
        return False

    def snapshot(self, deps):
        ended = any(c[0] == 'endOfDirectory' for c in self.calls)
        if self.state['unsupported'] or not ended or not self.items or not _trusted(deps):
            return None
        return {'format': FORMAT, 'created': time.time(), 'day': _today(), 'deps': deps,
                'items': self.items, 'calls': self.calls}


def replay(snap, handle, kodi_utils, xbmc, xbmcgui, xbmcplugin):
    """kodi_utils may be a zero-argument loader: POV's view-mode helpers run
    after endOfDirectory, so the list is on screen before POV is imported."""
    items = [_build(ops, xbmc, xbmcgui) for ops in snap['items']]
    for name, args, kwargs in snap['calls']:
        args, kwargs = _live(args, xbmc), _live(kwargs, xbmc)
        if name == 'addDirectoryItems':
            xbmcplugin.addDirectoryItems(handle, [(url, items[i], folder) for url, i, folder in args[0]], **kwargs)
        elif name == 'addDirectoryItem':
            xbmcplugin.addDirectoryItem(handle, args[0], items[args[1]], *args[2:], **kwargs)
        elif name.startswith('ku.'):
            if callable(kodi_utils) and not hasattr(kodi_utils, name[3:]):
                kodi_utils = kodi_utils()
            getattr(kodi_utils, name[3:])(*args, **kwargs)
        else:
            getattr(xbmcplugin, name)(handle, *args, **kwargs)
    return len(items)


# ------------------------------------------------------------------ install --

def _adult_profile():
    try:
        import profile_age_guard
        return profile_age_guard.active_policy() is None
    except Exception:
        return False


# handle -> the stale copy serve_early() already put on screen; the route then
# only rebuilds it (same interpreter: router.py's hook and POV share modules).
EARLY = {}


def _stale(snap, age, personal):
    return age >= (PERSONAL_TTL_S if personal else GENERAL_TTL_S) or snap.get('day') != _today()


def _same(a, b):
    return json.dumps([a['items'], a['calls']], sort_keys=True) == json.dumps([b['items'], b['calls']], sort_keys=True)


def _refresh_shown(xbmc, argv, context):
    """The rebuilt list differs from the copy on screen: show the new one --
    the open list (also when a home tile opened it) or the home rows."""
    shown = xbmc.getInfoLabel('Container.FolderPath')
    if shown and shown.rstrip('/') == (argv[0] + (argv[2] if len(argv) > 2 else '')).rstrip('/'):
        xbmc.executebuiltin('Container.Refresh')
        return 'container'
    if context[0]:
        xbmc.executebuiltin('UpdateLibrary(video,special://skin/foo)')   # POV's widget_refresh()
        return 'widgets'
    return 'none'


def _query(argv):
    from urllib.parse import parse_qsl
    return dict(parse_qsl((argv[2] if len(argv) > 2 else '').replace('?', '')))


def serve_early(argv):
    """From POV's router.py, BEFORE POV is imported: True when a fresh saved
    list was shown (the caller exits), False to continue as usual. Importing
    POV's entry costs 0.3-2.5 s per row on a busy Android box at start-up --
    more than the replay itself. An old copy (yesterday's, the first click
    after Kodi starts) is shown here too; False then lets POV load and
    rebuild it behind the scenes (EARLY)."""
    try:
        import xbmc, xbmcgui, xbmcplugin, xbmcvfs, xbmcaddon
        argv = list(argv)
        params = _query(argv)
        handle = int(argv[1]) if len(argv) > 1 else -1
        if (handle < 0 or not eligible(params) or os.path.exists(xbmcvfs.translatePath(KILL_SWITCH))
                or not _adult_profile()):
            return False
        profile = _profile_dir(xbmcvfs)
        personal = _personal(params)
        labels = _labels(xbmc)
        path = os.path.join(_store_dir(profile), _key(argv, _versions(xbmcaddon), _context(labels, params)) + '.json')
        snap, age = load(path, _deps(profile, params))
        if snap is None:
            return False      # missing or changed: the normal route builds it
        stale = _stale(snap, age, personal)
    except Exception:
        return False
    started = time.perf_counter()

    def pov_utils():
        from modules import kodi_utils
        return kodi_utils
    try:
        count = replay(snap, handle, pov_utils, xbmc, xbmcgui, xbmcplugin)
    except Exception as exc:
        try:
            os.remove(path)
        except OSError:
            pass
        xbmc.log('[POV IL snapshot] early replay failed: %s' % type(exc).__name__, xbmc.LOGWARNING)
        return True           # this handle was already answered (partly)
    xbmc.log('[POV IL snapshot] hit early mode=%s items=%d age_s=%d ms=%d%s' % (
        params.get('mode'), count, age, round((time.perf_counter() - started) * 1000),
        ' (refreshing)' if stale else ''), xbmc.LOGINFO)
    if stale:
        EARLY[handle] = (snap, labels)
        return False          # POV loads and rebuilds it; nothing more is shown
    return True


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
        try:
            profile = _profile_dir(xbmcvfs)
            personal = _personal(params)
            # After serve_early() the copy is on screen and the labels show
            # it, so the rebuild uses what was read before it was shown.
            labels = early[1] if early else _labels(xbmc)
            context = _context(labels, params)
            deps = _deps(profile, params)
            path = os.path.join(_store_dir(profile), _key(argv, _versions(xbmcaddon), context) + '.json')
            snap, age = (None, None) if early else load(path, deps)
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
                count = replay(snap, handle, ku, xbmc, xbmcgui, xbmcplugin)
            except Exception as exc:
                # A partial replay already talked to Kodi for this handle;
                # drop the record and let Kodi's next request build it fresh.
                try:
                    os.remove(path)
                except OSError:
                    pass
                xbmc.log('[POV IL snapshot] replay failed: %s' % type(exc).__name__, xbmc.LOGWARNING)
                return None
            stale = _stale(snap, age, personal)
            xbmc.log('[POV IL snapshot] hit mode=%s items=%d age_s=%d ms=%d%s' % (
                params.get('mode'), count, age, round((time.perf_counter() - started) * 1000),
                ' (refreshing)' if stale else ''), xbmc.LOGINFO)
            if not stale:
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
        try:
            # Taken after the build: POV writes its own caches while building.
            new = recorder.snapshot(_deps(profile, params)) if path else None
            if new is not None:
                try:
                    with open(path, 'r', encoding='utf-8') as fh:
                        prev = json.load(fh)
                except (OSError, ValueError):
                    prev = None
                # Another request may have rebuilt (and refreshed) this list
                # meanwhile -- e.g. a home row asked for twice at start-up.
                done = (shown is not None and isinstance(prev, dict) and
                        prev.get('created', 0) > shown.get('created', 0) and _same(prev, new))
                save(path, new)
                if shown is not None and not done and not _same(new, shown):
                    how = _refresh_shown(xbmc, argv, context)
                    xbmc.log('[POV IL snapshot] changed mode=%s refresh=%s' % (params.get('mode'), how), xbmc.LOGINFO)
            elif recorder.state['unsupported']:
                xbmc.log('[POV IL snapshot] not saved: %s' % recorder.state['unsupported'][:80], xbmc.LOGINFO)
        except Exception:
            pass
        return result
    routing._povil_snapshot = True
    return routing
