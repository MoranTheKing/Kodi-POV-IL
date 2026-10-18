"""Saved lists: a POV list is recorded once and replayed on the next visit,
but never once something it depends on has changed."""

import importlib.util
import json
import marshal
import os
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / 'plugin.program.kodipovilwizard' / 'resources' / 'libs' / 'patches' / 'pov_list_snapshot.py'


def rec_load(path):
    import zlib
    data = Path(path).read_bytes()
    return marshal.loads(zlib.decompress(data[1:]) if data[:1] == b'Z' else data)


class FakeTag(object):
    def __init__(self, log):
        self.log = log

    def __getattr__(self, name):
        return lambda *a, **k: self.log.append(('tag', name, a, k))


class FakeListItem(object):
    def __init__(self, label='', offscreen=False, **kwargs):     # Kodi's default
        self.ctor = (label, dict(kwargs, offscreen=offscreen))
        self.log = []
        self.props = {}

    def getVideoInfoTag(self, *a, **k):
        self.log.append(('getVideoInfoTag', a, k))
        return FakeTag(self.log)

    def setLabel(self, v):
        self.log.append(('setLabel', v))

    def setArt(self, d):
        self.log.append(('setArt', d))

    def setProperty(self, k, v):
        self.props[k] = v
        self.log.append(('setProperty', k, v))

    def getProperty(self, k):
        return self.props.get(k, '')

    def addContextMenuItems(self, items):
        self.log.append(('addContextMenuItems', items))


class FakeActor(object):
    def __init__(self, name, role, order, thumb):
        self.args = (name, role, order, thumb)

    def getName(self): return self.args[0]
    def getRole(self): return self.args[1]
    def getOrder(self): return self.args[2]
    def getThumbnail(self): return self.args[3]


class Env(object):
    """Fake Kodi modules + a POV-like route."""

    def __init__(self, root):
        self.root = Path(root)
        self.profile = self.root / 'addon_data' / 'plugin.video.pov'
        self.profile.mkdir(parents=True)
        (self.profile / 'settings.xml').write_text('<settings/>')
        for db in ('watched.db', 'traktcache.db', 'mdblcache.db'):
            c = sqlite3.connect(str(self.profile / db))
            c.execute('create table watched_status (db_type, media_id, season, episode, last_played, title)')
            c.execute('create table progress (db_type, media_id, season, episode, resume_point, curr_time, last_played, resume_id)')
            c.execute('create table favorites (db_type, tmdb_id, title)')
            if db == 'traktcache.db':
                c.execute('create table trakt_data (id unique, data)')
            c.commit(); c.close()
        c = sqlite3.connect(str(self.profile / 'maincache.db'))
        c.execute('create table maincache (id unique, expires, data)')
        c.execute("insert into maincache values ('tmdb_movies_popular_1', ?, '[]')", (int(time.time()) + 3600,))
        c.commit(); c.close()
        self.sent = []
        self.built = 0
        env = self
        # The screen before a request (the parent menu); Kodi switches both
        # labels to the new list once it receives endOfDirectory.
        self.parent = {'Container.PluginName': 'plugin.video.pov',
                       'Container.FolderPath': 'plugin://plugin.video.pov/?mode=navigator'}
        self.labels_gui = dict(self.parent)
        self.query = ''
        self.child = False
        self.opens_window = True    # False: a home row (the home screen stays)
        self.builtins = []
        self.xbmc = types.SimpleNamespace(log=lambda *a: None, LOGINFO=1, LOGWARNING=2, Actor=FakeActor,
                                          getInfoLabel=lambda k: env.labels_gui.get(k, ''),
                                          executebuiltin=lambda c: env.builtins.append(c),
                                          getCondVisibility=lambda c: env.child and 'POVILChild' in c)
        self.window_id = 10000
        self.xbmcgui = types.SimpleNamespace(ListItem=FakeListItem, getCurrentWindowId=lambda: env.window_id)
        self.xbmcvfs = types.SimpleNamespace(translatePath=lambda p: str(
            self.root / p.replace('special://profile/', '').replace('special://home/', 'home/')).rstrip('/\\') + os.sep
            if p.endswith('/') else str(self.root / p.replace('special://profile/', '')))
        self.xbmcaddon = types.SimpleNamespace(Addon=lambda aid: types.SimpleNamespace(getAddonInfo=lambda k: '1.0'))

        def rec(name):
            def call(handle, *a, **k):
                env.sent.append((name, handle, a, k))
                if name == 'endOfDirectory' and env.opens_window:
                    env.labels_gui.update({'Container.PluginName': 'plugin.video.pov',
                                           'Container.FolderPath': 'plugin://plugin.video.pov/' + env.query})
                return True
            return call
        self.xbmcplugin = types.SimpleNamespace(**{n: rec(n) for n in (
            'addDirectoryItems', 'addDirectoryItem', 'setContent', 'setPluginCategory',
            'addSortMethod', 'endOfDirectory')})
        self.ku = types.SimpleNamespace(
            make_listitem=lambda: FakeListItem(offscreen=True),
            parsed_query=lambda q: dict(p.split('=') for p in q.lstrip('?').split('&') if p),
            set_view_mode=lambda *a, **k: env.sent.append(('view', a, k)),
            focus_index=lambda *a, **k: None,
            get_infolabel=lambda k: env.labels_gui.get(k, ''))
        self.label = 'Movie'
        self.extra_arg = None
        self.age_guard = types.SimpleNamespace(active_policy=lambda: None)

    def modules(self):
        return {'xbmc': self.xbmc, 'xbmcgui': self.xbmcgui, 'xbmcplugin': self.xbmcplugin,
                'xbmcvfs': self.xbmcvfs, 'xbmcaddon': self.xbmcaddon,
                'profile_age_guard': self.age_guard}

    def route(self, sys_obj):
        """What a POV menu does."""
        self.built += 1
        handle = int(sys_obj.argv[1])
        # What POV bakes in from the screen: is_widget and the way back.
        exit_to = self.ku.get_infolabel('Container.FolderPath')
        widget = 'pov' not in self.ku.get_infolabel('Container.PluginName')
        items = []
        for n in range(3):
            li = self.ku.make_listitem()
            li.setLabel('%s %d' % (self.label, n))
            li.setArt({'poster': 'p%d.jpg' % n})
            tag = li.getVideoInfoTag()
            tag.setTitle('%s %d' % (self.label, n))
            tag.setCast([self.xbmc.Actor('A', 'B', 1, 't.jpg')])
            if self.extra_arg is not None:
                tag.setTags(self.extra_arg)
            li.addContextMenuItems([('Info', 'RunPlugin(x&is_widget=%s)' % widget), ('Exit', exit_to)])
            items.append(('plugin://x/?n=%d' % n, li, False))
        self.xbmcplugin.addDirectoryItems(handle, items)
        self.xbmcplugin.setContent(handle, 'movies')
        self.xbmcplugin.endOfDirectory(handle, cacheToDisc=None)
        self.ku.set_view_mode('view.movies', 'movies', False)


class SnapshotTests(unittest.TestCase):
    QUERY = '?mode=build_movie_list&action=tmdb_movies_popular'

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env = Env(tmp.name)
        self.patch = mock.patch.dict(sys.modules, self.env.modules())
        self.patch.start()
        self.addCleanup(self.patch.stop)
        spec = importlib.util.spec_from_file_location('snap_test', MOD)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)
        self.routing = self.m.wrap(self.env.route, {'kodi_utils': self.env.ku})

    def open(self, query=None, handle=7):
        self.env.sent = []
        self.env.query = query or self.QUERY
        self.env.labels_gui = dict(self.env.parent)
        self.routing(types.SimpleNamespace(argv=['plugin://plugin.video.pov/', str(handle), query or self.QUERY]))
        return self.env.sent

    def labels(self, sent):
        rows = [s for s in sent if s[0] == 'addDirectoryItems'][0][2][0]
        return [next(e[1] for e in li.log if e[0] == 'setLabel') for _u, li, _f in rows]

    def test_second_visit_is_replayed_identically(self):
        first = self.open()
        second = self.open()
        self.assertEqual(self.env.built, 1)
        self.assertEqual(self.labels(first), self.labels(second))
        li1 = [s for s in first if s[0] == 'addDirectoryItems'][0][2][0][0][1]
        li2 = [s for s in second if s[0] == 'addDirectoryItems'][0][2][0][0][1]
        strip = lambda log: [e for e in log if e[0] != 'tag' or e[1] != 'setCast']
        self.assertEqual(strip(li1.log), strip(li2.log))
        cast = [e for e in li2.log if e[0] == 'tag' and e[1] == 'setCast'][0][2][0][0]
        self.assertEqual(cast.args, ('A', 'B', 1, 't.jpg'))           # actors rebuilt
        self.assertEqual([s[0] for s in second], [s[0] for s in first])  # same calls, same order

    def test_a_watch_change_shows_the_list_then_rebuilds_it(self):
        self.env.parent['Container.FolderPath'] = 'plugin://plugin.video.pov/' + self.QUERY  # back from the player
        self.env.opens_window = False
        self.open()
        c = sqlite3.connect(str(self.env.profile / 'watched.db'))
        c.execute("insert into watched_status values ('movie','1',0,0,'2026-10-17 10:00:00','x')")
        c.commit(); c.close()
        self.env.label = 'Updated'
        self.assertEqual(self.labels(self.open())[0], 'Movie 0')          # at once
        self.assertEqual(self.env.built, 2)                                # rebuilt right after
        self.assertEqual(self.labels(self.open())[0], 'Updated 0')         # and served from now on
        self.assertEqual(self.env.built, 2)

    def test_other_changes_still_rebuild_before_showing(self):
        self.open()
        (self.env.profile / 'settings.xml').write_text('<settings><x/></settings>')
        self.env.label = 'Updated'
        self.assertEqual(self.labels(self.open())[0], 'Updated 0')
        self.assertEqual(self.env.built, 2)

    def test_a_refetched_or_cleared_pov_list_rebuilds(self):
        self.open()
        c = sqlite3.connect(str(self.env.profile / 'maincache.db'))
        c.execute('delete from maincache'); c.commit(); c.close()        # "clear cache"
        self.open()
        self.assertEqual(self.env.built, 2)

    def test_rewritten_files_with_the_same_content_keep_the_list(self):
        self.open()
        (self.env.profile / 'settings.xml').write_text('<settings/>')      # Kodi rewrites on exit
        self.open()
        self.assertEqual(self.env.built, 1)
        (self.env.profile / 'settings.xml').write_text('<settings><x/></settings>')
        self.open()
        self.assertEqual(self.env.built, 2)

    def test_an_old_list_is_shown_then_rebuilt_for_the_next_visit(self):
        self.open()
        path = next((self.env.profile / 'povil_snapshots').glob('*.snap'))
        data = rec_load(path); data['created'] -= 5 * 3600
        path.write_bytes(marshal.dumps(data))
        self.env.label = 'Today'
        sent = self.open()
        self.assertEqual(self.labels(sent)[0], 'Movie 0')                 # shown at once
        self.assertEqual(len([s for s in sent if s[0] == 'endOfDirectory']), 1)   # shadow build sent nothing
        self.assertEqual(self.env.built, 2)
        self.assertEqual(self.labels(self.open())[0], 'Today 0')         # next visit: today's list

    def test_too_old_lists_are_built_normally(self):
        self.open()
        path = next((self.env.profile / 'povil_snapshots').glob('*.snap'))
        data = rec_load(path); data['created'] -= 8 * 24 * 3600
        path.write_bytes(marshal.dumps(data))
        self.open()
        self.assertEqual(self.env.built, 2)

    def test_unrecordable_lists_are_never_saved(self):
        self.env.extra_arg = object()
        self.open(); self.open()
        self.assertEqual(self.env.built, 2)
        self.assertFalse(list((self.env.profile / 'povil_snapshots').glob('*.snap')) if
                         (self.env.profile / 'povil_snapshots').exists() else [])

    def test_search_child_profiles_and_the_kill_switch_bypass_it(self):
        self.open('?mode=build_movie_list&action=tmdb_movies_search&query=x'); self.open('?mode=build_movie_list&action=tmdb_movies_search&query=x')
        self.assertEqual(self.env.built, 2)
        self.env.age_guard.active_policy = lambda: {'max_age': 7}
        self.open(); self.open()
        self.assertEqual(self.env.built, 4)
        self.env.age_guard.active_policy = lambda: None
        kill = self.env.root / 'addon_data' / 'plugin.program.kodipovilwizard' / 'povil_snapshots_off'
        kill.parent.mkdir(parents=True); kill.write_text('')
        self.open(); self.open()
        self.assertEqual(self.env.built, 6)

    def test_serve_early_shows_old_lists_and_pov_only_rebuilds_them(self):
        self.env.parent['Container.PluginName'] = ''                       # a home row
        self.env.opens_window = False
        self.open()
        argv = ['plugin://plugin.video.pov/', '9', self.QUERY]
        loaded = []
        fake_pov = types.SimpleNamespace(kodi_utils=self.env.ku)
        with mock.patch.dict(sys.modules, {'modules': fake_pov, 'modules.kodi_utils': self.env.ku}):
            self.env.sent = []
            self.env.labels_gui = dict(self.env.parent)
            self.assertTrue(self.m.serve_early(argv))
            self.assertIn('endOfDirectory', [s[0] for s in self.env.sent])
            self.assertIn('view', [s[0] for s in self.env.sent])          # view mode after the list
            path = next((self.env.profile / 'povil_snapshots').glob('*.snap'))
            data = rec_load(path); data['created'] -= 5 * 3600
            path.write_bytes(marshal.dumps(data))
            self.env.sent = []
            self.env.labels_gui = dict(self.env.parent)
            self.assertFalse(self.m.serve_early(argv))                     # old: shown, then POV rebuilds it
            self.assertIn('endOfDirectory', [s[0] for s in self.env.sent])
            self.assertIn(9, self.m.EARLY)
        self.env.label = 'Today'
        self.env.sent = []
        self.routing(types.SimpleNamespace(argv=argv))                     # POV's route, same handle
        self.assertEqual(self.env.sent, [])                                # nothing shown twice
        self.assertEqual(self.env.built, 2)
        self.assertNotIn(9, self.m.EARLY)
        self.assertEqual(self.env.builtins, ['UpdateLibrary(video,special://skin/foo)'])  # it changed

    def _age_day(self, day):
        path = next((self.env.profile / 'povil_snapshots').glob('*.snap'))
        data = rec_load(path); data['day'] = day
        path.write_bytes(marshal.dumps(data))

    def test_a_list_from_yesterday_is_shown_then_refreshed_in_place(self):
        q = '?mode=build_next_episode'
        self.open(q)
        self._age_day('2000-01-01')
        self.env.label = 'Today'
        self.assertEqual(self.labels(self.open(q))[0], 'Movie 0')          # instant
        self.assertEqual(self.env.builtins, ['Container.Refresh'])         # changed -> open list refreshed
        self.assertEqual(self.labels(self.open(q))[0], 'Today 0')
        self.assertEqual(self.env.built, 2)
        self._age_day('2000-01-01')
        self.open(q)                                                       # same content: no refresh
        self.assertEqual(self.env.builtins, ['Container.Refresh'])

    def test_home_rows_and_the_full_list_are_saved_apart(self):
        self.open()
        self.env.parent['Container.PluginName'] = ''                       # a home row
        self.open(); self.open()
        self.assertEqual(self.env.built, 2)

    def test_a_list_opened_from_a_home_tile_is_rebuilt_as_it_was_opened(self):
        q = '?mode=build_next_episode'
        self.env.parent = {'Container.PluginName': '', 'Container.FolderPath': ''}   # home screen
        first = self.open(q)
        self.assertEqual(self.env.labels_gui['Container.FolderPath'], 'plugin://plugin.video.pov/' + q)
        self._age_day('2000-01-01')
        self.env.label = 'Today'
        self.assertEqual(self.labels(self.open(q))[0], 'Movie 0')          # yesterday's, at once
        self.assertEqual(self.env.builtins, ['Container.Refresh'])         # the open window refreshes
        again = self.open(q)                                               # served, not rebuilt
        self.assertEqual(self.labels(again)[0], 'Today 0')
        self.assertEqual(self.env.built, 2)
        menu = lambda sent: [e for e in [x for x in sent if x[0] == 'addDirectoryItems'][0][2][0][0][1].log
                             if e[0] == 'addContextMenuItems'][0][1]
        self.assertEqual(menu(again), menu(first))                         # built as from the home tile

    def test_an_early_old_copy_is_rebuilt_under_its_own_key(self):
        self.open()
        argv = ['plugin://plugin.video.pov/', '9', self.QUERY]
        self._age_day('2000-01-01')
        self.env.label = 'Today'
        fake_pov = types.SimpleNamespace(kodi_utils=self.env.ku)
        with mock.patch.dict(sys.modules, {'modules': fake_pov, 'modules.kodi_utils': self.env.ku}):
            self.env.labels_gui = dict(self.env.parent)
            self.env.query = self.QUERY
            self.assertFalse(self.m.serve_early(argv))                     # shown; labels now the list
            self.routing(types.SimpleNamespace(argv=argv))                 # POV rebuilds it
        self.assertEqual(self.env.builtins, ['Container.Refresh'])
        self.assertEqual(self.labels(self.open())[0], 'Today 0')           # replaced, from the parent
        self.assertEqual(self.env.built, 2)
        self.assertEqual(len(list((self.env.profile / 'povil_snapshots').glob('*.snap'))), 1)

    def test_labels_are_pinned_in_menus_kept_from_an_earlier_request(self):
        menu = types.SimpleNamespace(get_infolabel=self.env.ku.get_infolabel)   # reused interpreter
        seen = []
        route = self.env.route

        def reading(sys_obj):
            seen.append(menu.get_infolabel('Container.FolderPath'))
            self.env.labels_gui['Container.FolderPath'] = 'elsewhere'
            seen.append(menu.get_infolabel('Container.FolderPath'))
            route(sys_obj)
        self.env.route = reading
        with mock.patch.dict(sys.modules, {'menus.movies': menu}):
            self.routing = self.m.wrap(lambda so: self.env.route(so), {'kodi_utils': self.env.ku})
            self.open()
        self.assertEqual(seen, [self.env.parent['Container.FolderPath']] * 2)
        self.assertIs(menu.get_infolabel, self.env.ku.get_infolabel)       # restored

    def _age_files(self):
        old = time.time() - 600
        for f in self.env.profile.iterdir():
            if f.is_file():
                os.utime(f, (old, old))

    def _early(self, query=None):
        argv = ['plugin://plugin.video.pov/', '9', query or self.QUERY]
        fake_pov = types.SimpleNamespace(kodi_utils=self.env.ku)
        with mock.patch.dict(sys.modules, {'modules': fake_pov, 'modules.kodi_utils': self.env.ku}):
            self.env.sent = []
            self.env.labels_gui = dict(self.env.parent)
            self.env.query = query or self.QUERY
            return self.m.serve_early(argv)

    def test_unchanged_files_serve_without_reading_any_database(self):
        self._age_files()
        self.open()
        imported = []
        real_import = __import__

        def spy(name, *a, **k):
            imported.append(name)
            return real_import(name, *a, **k)
        with mock.patch.object(self.m, '_deps', side_effect=AssertionError('deps read')),                 mock.patch('builtins.__import__', spy):
            self.assertTrue(self._early())
        self.assertIn('endOfDirectory', [x[0] for x in self.env.sent])
        heavy = {'json', 'hashlib', 'sqlite3', 're', 'urllib.parse', 'tempfile', 'profile_age_guard'}
        self.assertFalse(heavy & set(imported), imported)

    def test_a_written_file_is_checked_by_content(self):
        self._age_files()
        self.open()
        older = time.time() - 300
        os.utime(self.env.profile / 'settings.xml', (older, older))        # rewritten, same content
        self.assertTrue(self._early())                                     # content proves it
        with mock.patch.object(self.m, '_deps', side_effect=AssertionError('deps read')):
            self.assertTrue(self._early())                                 # new times recorded
        c = sqlite3.connect(str(self.env.profile / 'watched.db'))
        c.execute("insert into watched_status values ('movie','1',0,0,'2026-10-17 10:00:00','x')")
        c.commit(); c.close()
        self.assertFalse(self._early())                                    # a real change: rebuilt
        self.assertEqual(self.env.built, 1)

    def test_the_content_check_avoids_heavy_imports_too(self):
        self.open()
        os.utime(self.env.profile / 'settings.xml', (time.time() - 300,) * 2)
        imported = []
        real_import = __import__

        def spy(name, *a, **k):
            imported.append(name)
            return real_import(name, *a, **k)
        with mock.patch('builtins.__import__', spy):
            self.assertTrue(self._early())
        heavy = {'json', 'hashlib', 'sqlite3', 're', 'urllib.parse', 'tempfile', 'profile_age_guard'}
        self.assertFalse(heavy & set(imported), imported)
        self.assertIn('_sqlite3', imported)

    def test_dropped_show_stamps_do_not_count_but_shows_do(self):
        f = self.env.profile / 'povil_dropped_trakt.json'
        f.write_text('{"version":1,"items":[],"complete":false,"checked":1,"retry_at":5}')
        self.open()
        f.write_text('{"version":1,"items":[],"complete":false,"checked":2,"retry_at":9}')
        self.open()
        self.assertEqual(self.env.built, 1)
        f.write_text('{"version":1,"items":[["tv","1"]],"complete":false,"checked":2,"retry_at":9}')
        self.open()
        self.assertEqual(self.env.built, 2)

    def test_an_expired_list_row_is_noticed_without_any_file_write(self):
        self._age_files()
        self.open()
        path = next((self.env.profile / 'povil_snapshots').glob('*.snap'))
        data = rec_load(path)
        self.assertIsNotNone(data['sig'])
        data['expires'] = time.time() - 1                                  # POV's row ran out
        path.write_bytes(marshal.dumps(data))
        with mock.patch.object(self.m, '_deps', wraps=self.m._deps) as deps:
            self._early()
        self.assertTrue(deps.called)

    def test_child_profiles_and_encoded_requests_are_left_to_pov(self):
        self._age_files()
        self.open()
        self.env.child = True
        self.assertFalse(self._early())
        self.env.child = False
        self.assertFalse(self._early('?mode=build_movie_list&action=tmdb%5Fmovies_popular'))
        self.assertTrue(self._early())

    def test_home_rows_skip_povs_no_op_view_mode(self):
        loaded = []
        calls = [['ku.set_view_mode', ['view.movies', 'movies', True], {}]]     # is_widget=True
        self.m.replay({'items': [], 'calls': calls}, 9, lambda: loaded.append(1) or self.env.ku,
                      self.env.xbmc, self.env.xbmcgui, self.env.xbmcplugin)
        self.assertEqual(loaded, [])                                       # POV never imported
        calls[0][1][2] = False
        self.m.replay({'items': [], 'calls': calls}, 9, lambda: loaded.append(1) or self.env.ku,
                      self.env.xbmc, self.env.xbmcgui, self.env.xbmcplugin)
        self.assertEqual(loaded, [1])

    def test_trakt_charts_are_public_and_account_lists_personal(self):
        for action in ('trakt_tv_trending', 'trakt_movies_most_watched', 'trakt_tvanime_trending'):
            self.assertFalse(self.m._personal({'mode': 'build_tvshow_list', 'action': action}), action)
            self.assertFalse(self.m._account_list({'mode': 'build_tvshow_list', 'action': action}), action)
        for action in ('trakt_watchlist', 'trakt_collection_lists', 'trakt_recommendations', 'mdblist_watchlist'):
            self.assertTrue(self.m._account_list({'mode': 'build_movie_list', 'action': action}), action)

    def test_pov_menus_are_saved_and_follow_menu_and_account_changes(self):
        c = sqlite3.connect(str(self.env.profile / 'navigator.db'))
        c.execute('create table navigator (list_name, list_type, list_contents)')
        c.execute("insert into navigator values ('MovieList', 'default', '[]')")
        c.commit(); c.close()
        q = '?mode=navigator.genres&menu_type=movie'
        self.open(q); self.open(q)
        self.assertEqual(self.env.built, 1)
        c = sqlite3.connect(str(self.env.profile / 'navigator.db'))
        c.execute("update navigator set list_contents = '[1]'"); c.commit(); c.close()
        self.open(q)
        self.assertEqual(self.env.built, 2)                                # menu edited
        acct = self.env.profile.parent / 'script.module.acctmgr'
        acct.mkdir()
        (acct / 'settings.xml').write_text('<settings><setting id="trakt.token">x</setting></settings>')
        self.open(q)
        self.assertEqual(self.env.built, 3)                                # an account connected
        self.open(q)
        self.assertEqual(self.env.built, 3)
        self.assertFalse(self.m.eligible({'mode': 'navigator.search'}))
        self.assertFalse(self.m.eligible({'mode': 'navigator.downloads'}))

    def test_rows_changed_together_refresh_the_home_once(self):
        props = {}
        win = types.SimpleNamespace(getProperty=lambda k: props.get(k, ''),
                                    setProperty=lambda k, v: props.__setitem__(k, v))
        self.env.xbmc.Monitor = lambda: types.SimpleNamespace(waitForAbort=lambda s: False)
        with mock.patch.dict(sys.modules, {'xbmcgui': types.SimpleNamespace(Window=lambda wid: win)}):
            saved = time.time()
            self.assertEqual(self.m._refresh_widgets(self.env.xbmc, saved), 'widgets')
            self.assertEqual(self.m._refresh_widgets(self.env.xbmc, saved), 'joined')
            self.assertEqual(self.m._refresh_widgets(self.env.xbmc, time.time() + 5), 'widgets')
        self.assertEqual(self.env.builtins, ['UpdateLibrary(video,special://skin/foo)'] * 2)

    def test_a_damaged_record_is_dropped_and_the_list_built_as_usual(self):
        self.open()
        path = next((self.env.profile / 'povil_snapshots').glob('*.snap'))
        data = rec_load(path); data['items'] = data['items'][:1]
        path.write_bytes(marshal.dumps(data))
        sent = self.open()
        self.assertEqual(len(self.labels(sent)), 3)                        # full list, once
        self.assertEqual(len([x for x in sent if x[0] == 'endOfDirectory']), 1)
        self.assertEqual(self.env.built, 2)
        path.write_bytes(marshal.dumps(dict(data, items=[])))
        self.assertFalse(self._early())                                    # early path: POV builds it
        self.assertEqual(self.env.sent, [])

    def test_lists_one_click_from_a_saved_menu_are_built_ahead_for_that_menu(self):
        route = self.env.route
        menu_q = '?mode=navigator.genres&menu_type=movie'
        child_q = '?mode=build_movie_list&action=tmdb_movies_genres&genre_id=%d'

        def routes(sys_obj):
            if 'navigator' in sys_obj.argv[2]:
                self.env.built += 1
                for n in (28, 35):
                    li = self.env.ku.make_listitem(); li.setLabel('genre %d' % n)
                    self.env.xbmcplugin.addDirectoryItem(int(sys_obj.argv[1]),
                                                         'plugin://plugin.video.pov/' + child_q % n, li, True)
                self.env.xbmcplugin.endOfDirectory(int(sys_obj.argv[1]))
            else:
                route(sys_obj)
        self.env.route = routes
        self.routing = self.m.wrap(lambda so: self.env.route(so), {'kodi_utils': self.env.ku})
        self.open(menu_q)                                                  # the menu, saved
        targets, _count = self.m.prebuild_targets(str(self.env.profile) + os.sep, ['1.0', '1.0'])
        self.assertEqual([t[1] for t in targets], [child_q % 28, child_q % 35])
        parent = 'plugin://plugin.video.pov/' + menu_q
        self.assertEqual(targets[0][2], {'Container.PluginName': 'plugin.video.pov',
                                         'Container.FolderPath': parent})
        # The Wizard's prebuild of the first one, while Kodi shows the home screen.
        self.env.parent = {'Container.PluginName': '', 'Container.FolderPath': ''}
        self.env.labels_gui = dict(self.env.parent)
        mark = ''.join((repr(time.time() + 30), child_q % 28, 'plugin.video.pov', parent))
        props = {'Window(10000).Property(povil.prebuild)': mark}
        real, real_builtin = self.env.xbmc.getInfoLabel, self.env.xbmc.executebuiltin
        self.env.xbmc.getInfoLabel = lambda k: props.get(k) or real(k)

        def builtin(cmd):                       # like Kodi: the property really goes away
            real_builtin(cmd)
            if cmd == 'ClearProperty(povil.prebuild,home)':
                props.clear()
        self.env.xbmc.executebuiltin = builtin
        self.env.query = child_q % 28
        argv = ['plugin://plugin.video.pov/', '5', child_q % 28]
        fake_pov = types.SimpleNamespace(kodi_utils=self.env.ku)
        with mock.patch.dict(sys.modules, {'modules': fake_pov, 'modules.kodi_utils': self.env.ku}):
            self.assertFalse(self.m.serve_early(argv))                     # router.py first: no record
        self.assertTrue(props)                                             # ...and the screen is still named
        self.routing(types.SimpleNamespace(argv=argv))                     # then POV builds it
        self.assertFalse(props)
        self.env.xbmc.getInfoLabel, self.env.xbmc.executebuiltin = real, real_builtin
        self.assertIn('ClearProperty(povil.prebuild,home)', self.env.builtins)   # one request only
        index = (self.env.profile / 'povil_snapshots' / '_menus.idx').read_text().split()
        self.assertEqual(len(index), 1)                                    # the menu, not its lists
        built = self.env.built
        targets, _count = self.m.prebuild_targets(str(self.env.profile) + os.sep, ['1.0', '1.0'])
        self.assertEqual([t[1] for t in targets], [child_q % 35])
        # The real first click, from inside the menu: no build.
        self.env.parent = {'Container.PluginName': 'plugin.video.pov', 'Container.FolderPath': parent}
        self.open(child_q % 28)
        self.assertEqual(self.env.built, built)

    def test_one_genre_list_is_not_thrown_away_by_another(self):
        q = '?mode=build_movie_list&action=tmdb_movies_genres&genre_id=%d'
        c = sqlite3.connect(str(self.env.profile / 'maincache.db'))
        c.execute("insert into maincache values ('tmdb_movies_genres_28_1', ?, '[]')", (int(time.time()) + 3600,))
        c.commit(); c.close()
        self.open(q % 28)
        c = sqlite3.connect(str(self.env.profile / 'maincache.db'))
        c.execute("insert into maincache values ('tmdb_movies_genres_35_1', ?, '[]')", (int(time.time()) + 3600,))
        c.commit(); c.close()                                              # another genre fetched
        self.open(q % 28)
        self.assertEqual(self.env.built, 1)
        c = sqlite3.connect(str(self.env.profile / 'maincache.db'))
        c.execute("delete from maincache where id like 'tmdb_movies_genres_28%'"); c.commit(); c.close()
        self.open(q % 28)                                                  # its own rows cleared
        self.assertEqual(self.env.built, 2)

    def test_idle_resign_lets_the_next_start_skip_the_content_check(self):
        self._age_files()
        self.open()
        older = time.time() - 300
        os.utime(self.env.profile / 'traktcache.db', (older, older))       # a sync, same content
        self.assertEqual(self.m.resign(str(self.env.profile) + os.sep), 1)
        with mock.patch.object(self.m, '_deps', side_effect=AssertionError('deps read')):
            self.assertTrue(self._early())                                 # by file times alone
        c = sqlite3.connect(str(self.env.profile / 'watched.db'))
        c.execute("insert into watched_status values ('movie','1',0,0,'2026-10-17 10:00:00','x')")
        c.commit(); c.close()
        os.utime(self.env.profile / 'watched.db', (older + 10, older + 10))
        self.assertEqual(self.m.resign(str(self.env.profile) + os.sep), 0)  # a real change stays a change
        self.assertFalse(self._early())

    def test_the_skins_home_rows_and_tiles_are_targets_from_home(self):
        skin = self.env.root / 'skin'
        (skin / 'xml').mkdir(parents=True)
        (skin / 'addon.xml').write_text('<addon/>')
        (skin / 'xml' / 'Home.xml').write_text(
            '<content>plugin://plugin.video.pov/?mode=build_movie_list&amp;action=tmdb_my_movies</content>'
            '<onclick>ActivateWindow(videos,"plugin://plugin.video.pov/?mode=navigator.genres&amp;menu_type=movie",return)</onclick>'
            '<content>plugin://plugin.video.pov/?mode=build_next_episode</content>'
            '<content>plugin://plugin.video.pov/?mode=build_movie_list&amp;query=$INFO[x]</content>')
        targets, _n = self.m.prebuild_targets(str(self.env.profile) + os.sep, ['1.0', '1.0'], skin_dir=str(skin))
        self.assertEqual([t[1] for t in targets], ['?mode=build_movie_list&action=tmdb_my_movies',
                                                   '?mode=navigator.genres&menu_type=movie'])
        self.assertEqual(targets[0][2], {'Container.PluginName': '', 'Container.FolderPath': ''})

    def test_only_dependencies_of_changed_files_are_read_again(self):
        self._age_files()
        self.open()
        older = time.time() - 300
        os.utime(self.env.profile / 'maincache.db', (older, older))        # POV's list cache written
        read = []
        real = self.m._db_marks
        with mock.patch.object(self.m, '_db_marks', side_effect=lambda *a, **k: read.append(a[0]) or real(*a, **k)):
            self.assertTrue(self._early())
        self.assertEqual(read, [])                                         # no watch database opened
        os.utime(self.env.profile / 'watched.db', (older + 1, older + 1))
        c = sqlite3.connect(str(self.env.profile / 'watched.db'))
        c.execute("insert into watched_status values ('movie','1',0,0,'2026-10-17 10:00:00','x')")
        c.commit(); c.close()
        os.utime(self.env.profile / 'watched.db', (older + 2, older + 2))
        self.assertFalse(self._early())                                    # a real change is still seen

    def test_a_list_that_saves_nothing_does_not_hold_up_the_others(self):
        props, asked = {}, []
        win = types.SimpleNamespace(getProperty=lambda k: props.get(k, ''),
                                    setProperty=lambda k, v: props.__setitem__(k, v),
                                    clearProperty=lambda k: props.pop(k, None))
        xbmc = types.SimpleNamespace(
            Player=lambda: types.SimpleNamespace(isPlayingVideo=lambda: False),
            getGlobalIdleTime=lambda: 100, log=lambda *a: None, LOGINFO=1, LOGWARNING=2,
            executeJSONRPC=lambda req: asked.append(json.loads(req)['params']['directory']))
        targets = [('plugin://plugin.video.pov/?a=%d' % n, '?a=%d' % n, dict(self.m.HOME_LABELS)) for n in (1, 2)]
        with mock.patch.dict(sys.modules, {'xbmcgui': types.SimpleNamespace(Window=lambda wid: win)}),                 mock.patch.object(self.m, 'prebuild_targets', return_value=(targets, 5)),                 mock.patch.object(self.m, 'resign', return_value=0),                 mock.patch.object(self.m, '_adult_profile', return_value=True):
            self.m.prebuild_tick(xbmc); self.m.prebuild_tick(xbmc); self.m.prebuild_tick(xbmc)
        self.assertEqual(asked, ['plugin://plugin.video.pov/?a=1', 'plugin://plugin.video.pov/?a=2'])

    def test_a_rebuild_gives_way_to_an_episode_that_is_starting(self):
        props = {}
        win = types.SimpleNamespace(getProperty=lambda k: props.get(k, ''))
        xbmc = types.SimpleNamespace(
            Player=lambda: types.SimpleNamespace(isPlayingVideo=lambda: False),
            Monitor=lambda: types.SimpleNamespace(waitForAbort=lambda s: False))
        with mock.patch.dict(sys.modules, {'xbmcgui': types.SimpleNamespace(Window=lambda wid: win)}):
            self.assertTrue(self.m._wait_rows_quiet(xbmc))
            props[self.m.PLAY_PROPERTY] = repr(time.time() - 5)
            self.assertFalse(self.m._wait_rows_quiet(xbmc))
            props[self.m.PLAY_PROPERTY] = repr(time.time() - 120)          # an old mark
            self.assertTrue(self.m._wait_rows_quiet(xbmc))

    def test_play_property_matches_the_play_guard(self):
        spec = importlib.util.spec_from_file_location('ppg_test', MOD.parent / 'pov_play_guard.py')
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        self.assertEqual(self.m.PLAY_PROPERTY, guard.PROPERTY)
        self.assertEqual(self.m.PLAY_WINDOW_S, guard.WINDOW_S)

    def test_show_lists_follow_the_show_metadata(self):
        self.assertTrue(self.m.eligible({'mode': 'build_season_list', 'tmdb_id': '1396'}))
        self.assertTrue(self.m.eligible({'mode': 'build_episode_list', 'tmdb_id': '1396', 'season': '2'}))
        self.assertFalse(self.m.eligible({'mode': 'build_season_list'}))
        path = str(self.env.profile / 'metacache.db')
        c = sqlite3.connect(path)
        c.execute('CREATE TABLE metadata (db_type TEXT, tmdb_id TEXT, imdb_id TEXT, tvdb_id TEXT, expires INTEGER, meta TEXT)')
        c.execute('CREATE TABLE season_metadata (tmdb_id TEXT, expires INTEGER, meta TEXT)')
        c.execute("INSERT INTO metadata VALUES ('tvshow', '1396', '', '', 1, 'show')")
        c.execute("INSERT INTO season_metadata VALUES ('1396_1', 1, 's1')")
        c.execute("INSERT INTO season_metadata VALUES ('1396_2', 1, 's2')")
        c.execute("INSERT INTO season_metadata VALUES ('13960_1', 1, 'other show')")
        c.commit()
        ep2 = {'mode': 'build_episode_list', 'tmdb_id': '1396', 'season': '2'}
        every = {'mode': 'build_episode_list', 'tmdb_id': '1396', 'season': 'all'}
        seasons = {'mode': 'build_season_list', 'tmdb_id': '1396'}
        before = [self.m._show_meta(path, p) for p in (ep2, every, seasons)]
        c.execute("UPDATE season_metadata SET meta = 'other show 2' WHERE tmdb_id = '13960_1'")
        c.commit()
        self.assertEqual([self.m._show_meta(path, p) for p in (ep2, every, seasons)], before)
        c.execute("UPDATE season_metadata SET meta = 's1 new episode' WHERE tmdb_id = '1396_1'")
        c.commit()
        after = [self.m._show_meta(path, p) for p in (ep2, every, seasons)]
        self.assertEqual(after[0], before[0])           # season 2 list: unchanged
        self.assertNotEqual(after[1], before[1])        # all episodes: changed
        self.assertEqual(after[2], before[2])           # seasons list: show row only
        c.execute("UPDATE metadata SET meta = 'show, new season' WHERE tmdb_id = '1396'")
        c.commit(); c.close()
        self.assertNotEqual(self.m._show_meta(path, seasons), before[2])
        self.assertIn(self.m.META_DB, self.m._deps(str(self.env.profile), seasons))

    def test_guard_file_names_match_profile_age_guard(self):
        spec = importlib.util.spec_from_file_location('pag_test', MOD.parent / 'profile_age_guard.py')
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        self.assertEqual(self.m.GUARD_POLICY_FILE, guard.POLICY_FILE)
        self.assertEqual(self.m.GUARD_CHILD_MARKER, guard.CHILD_MARKER)

    def test_a_menu_imported_during_the_build_gets_the_real_labels_back(self):
        menu = types.SimpleNamespace()
        route = self.env.route

        def importing(sys_obj):
            menu.get_infolabel = self.env.ku.get_infolabel                 # first import, pinned alias
            sys.modules['menus.tvshows'] = menu
            route(sys_obj)
        self.env.route = importing
        try:
            self.routing = self.m.wrap(lambda so: self.env.route(so), {'kodi_utils': self.env.ku})
            self.open()
        finally:
            sys.modules.pop('menus.tvshows', None)
        self.assertIs(menu.get_infolabel, self.env.ku.get_infolabel)
        self.env.labels_gui['Container.FolderPath'] = 'now'
        self.assertEqual(menu.get_infolabel('Container.FolderPath'), 'now')

    def test_full_screen_lists_are_saved_per_parent_folder(self):
        self.env.parent['Container.FolderPath'] = 'plugin://plugin.video.pov/?mode=a'
        self.open(); self.open()
        self.env.parent['Container.FolderPath'] = 'plugin://plugin.video.pov/?mode=b'
        self.open()
        self.assertEqual(self.env.built, 2)

    def test_favourites_and_mdblist_dropped_shows_are_dependencies(self):
        self.open()
        c = sqlite3.connect(str(self.env.profile / 'watched.db'))
        c.execute("insert into favorites values ('movie','1','x')"); c.commit(); c.close()
        self.open()
        self.assertEqual(self.env.built, 2)
        (self.env.profile / 'povil_dropped_mdblist.json').write_text('{"items": [1]}')
        self.open()
        self.assertEqual(self.env.built, 3)

    def test_unreadable_dependencies_are_never_trusted(self):
        with mock.patch.object(self.m, '_list_marks', return_value='error'):
            self.open(); self.open()
        self.assertEqual(self.env.built, 2)
        self.assertFalse((self.env.profile / 'povil_snapshots').exists() and
                         list((self.env.profile / 'povil_snapshots').glob('*.snap')))

    def test_a_recording_failure_still_sends_real_items(self):
        orig = self.m.Recorder._index
        with mock.patch.object(self.m.Recorder, '_index', side_effect=RuntimeError('x')):
            sent = self.open()
        rows = [x for x in sent if x[0] == 'addDirectoryItems'][0][2][0]
        self.assertTrue(all(isinstance(li, FakeListItem) for _u, li, _f in rows))
        self.open()
        self.assertEqual(self.env.built, 2)                                # not saved


class IdanPlusTests(unittest.TestCase):
    URL = '?mode=1&url=&module=&moredata='

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env = Env(tmp.name)
        (self.env.root / 'addon_data' / 'plugin.video.idanplus').mkdir(parents=True)
        (self.env.root / 'addon_data' / 'plugin.video.idanplus' / 'settings.xml').write_text('<settings/>')
        self.env.labels_gui['Container.PluginName'] = ''                   # home row
        self.built = 0
        self.title = 'Channel'
        env = self.env

        def route(query):
            self.built += 1
            for n in range(3):
                li = sys.modules['xbmcgui'].ListItem('%s %d' % (self.title, n))
                li.setArt({'thumb': 't%d.png' % n})
                env.xbmcplugin.addDirectoryItem(handle=7, url='plugin://x/?c=%d' % n, listitem=li, isFolder=False)
            env.xbmcplugin.endOfDirectory(7)
        main = types.SimpleNamespace(route=route)
        common = types.SimpleNamespace(PlayStream=lambda *a, **k: None)
        lib = types.SimpleNamespace(common=common)
        mods = dict(self.env.modules(), **{'resources': types.SimpleNamespace(main=main, lib=lib),
                                           'resources.main': main, 'resources.lib': lib,
                                           'resources.lib.common': common})
        self.patch = mock.patch.dict(sys.modules, mods)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        spec = importlib.util.spec_from_file_location('snap_idan', MOD)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def call(self, query=None):
        self.env.sent = []
        return self.m.idanplus(['plugin://plugin.video.idanplus/', '7', query or self.URL])

    def rows(self):
        out = []
        for x in self.env.sent:
            if x[0] == 'addDirectoryItem':
                out.append((x[2][0], x[2][1].ctor[0], x[2][2]))
            elif x[0] == 'addDirectoryItems':           # a replay sends them in one call
                out.extend((u, li.ctor[0], f) for u, li, f in x[2][0])
        return out

    def test_a_home_row_is_saved_then_served_without_idan_plus(self):
        self.assertTrue(self.call())
        first = self.rows()
        self.assertTrue(self.call())
        self.assertEqual(self.built, 1)
        self.assertEqual(self.rows(), first)
        self.assertEqual(first[0], ('plugin://x/?c=0', 'Channel 0', False))

    def test_an_old_copy_is_shown_rebuilt_and_the_rows_refreshed(self):
        self.call()
        path = next((self.env.root / 'addon_data' / 'plugin.video.idanplus' / 'povil_snapshots').glob('*.snap'))
        data = rec_load(path); data['created'] -= 3600
        path.write_bytes(marshal.dumps(data))
        self.title = 'New'
        self.assertTrue(self.call())
        self.assertEqual(self.rows()[0][1], 'Channel 0')                   # shown at once
        self.assertEqual(self.built, 2)
        self.assertEqual(self.env.builtins, ['UpdateLibrary(video,special://skin/foo)'])
        self.call()
        self.assertEqual(self.rows()[0][1], 'New 0')
        self.assertEqual(self.built, 2)

    def test_playing_from_a_home_row_gets_a_real_listitem_and_saves_nothing(self):
        resolved = []
        env = self.env
        env.xbmcplugin.setResolvedUrl = lambda handle, *a, **k: resolved.append((a, k)) or True
        common = types.SimpleNamespace()

        def play_stream(url, quality='best', name='', iconimage='', adaptive=False):
            li = sys.modules['xbmcgui'].ListItem(name, path=url)
            env.xbmcplugin.setResolvedUrl(handle=7, succeeded=True, listitem=li)
        common.PlayStream = play_stream

        def route(query):
            sys.modules['resources.lib.common'].PlayStream('http://x/live.m3u8', name='ch')
            env.xbmcplugin.endOfDirectory(7)
        main = types.SimpleNamespace(route=route)
        lib = types.SimpleNamespace(common=common)
        with mock.patch.dict(sys.modules, {'resources.main': main, 'resources.lib': lib,
                                           'resources.lib.common': common,
                                           'resources': types.SimpleNamespace(main=main, lib=lib)}):
            self.assertTrue(self.call('?mode=3&module=keshet&url=x'))
        self.assertIsInstance(resolved[0][1]['listitem'], FakeListItem)    # not a recording proxy
        self.assertIs(common.PlayStream, play_stream)
        self.assertFalse(list((self.env.root / 'addon_data' / 'plugin.video.idanplus').rglob('*.snap')))

    def test_favourites_and_channel_edits_rebuild_the_row(self):
        self.call(); self.call()
        self.assertEqual(self.built, 1)
        data = self.env.root / 'addon_data' / 'plugin.video.idanplus'
        (data / 'favorites.json').write_text('[{"name": "x"}]')
        self.call()
        self.assertEqual(self.built, 2)
        (data / 'displayChannels.json').write_text('[1, 2]')
        self.call()
        self.assertEqual(self.built, 3)
        self.call()
        self.assertEqual(self.built, 3)

    def test_a_damaged_idan_plus_record_is_rebuilt_at_once(self):
        self.call()
        path = next((self.env.root / 'addon_data' / 'plugin.video.idanplus' / 'povil_snapshots').glob('*.snap'))
        data = rec_load(path); data['items'] = []
        path.write_bytes(marshal.dumps(data))
        self.assertTrue(self.call())
        self.assertEqual(len(self.rows()), 3)
        self.assertEqual(self.built, 2)

    def test_items_dropped_after_adding_keep_their_own_content(self):
        env = self.env

        def route(query):
            self.built += 1
            for n in range(50):          # each ListItem is dropped right after it is added
                env.xbmcplugin.addDirectoryItem(handle=7, url='plugin://x/?c=%d' % n,
                                                listitem=sys.modules['xbmcgui'].ListItem('Show %d' % n), isFolder=True)
            env.xbmcplugin.endOfDirectory(7)
        sys.modules['resources.main'].route = route
        shown = []
        # Like Kodi: the item is copied, the Python object is not kept.
        env.xbmcplugin.addDirectoryItem = lambda handle, url, listitem, isFolder=False, *a: shown.append(
            listitem.ctor[0]) or True
        env.xbmcplugin.addDirectoryItems = lambda handle, items, total=0: shown.extend(
            li.ctor[0] for _u, li, _f in items) or True
        self.call()
        shown[:] = []
        self.call()
        self.assertEqual(self.built, 1)
        self.assertEqual(shown, ['Show %d' % n for n in range(50)])

    def test_replayed_items_are_offscreen_and_sent_in_one_call(self):
        self.call(); self.call()
        batches = [x for x in self.env.sent if x[0] == 'addDirectoryItems']
        self.assertEqual(len(batches), 1)
        self.assertEqual([x[0] for x in self.env.sent].count('addDirectoryItem'), 0)
        self.assertTrue(all(li.ctor[1].get('offscreen') is True for _u, li, _f in batches[0][2][0]))

    def test_browsing_idan_plus_searches_and_playback_are_untouched(self):
        self.env.labels_gui['Container.PluginName'] = 'plugin.video.idanplus'
        self.assertFalse(self.call())
        self.env.labels_gui['Container.PluginName'] = ''
        self.assertFalse(self.call('?mode=5&url=x&module='))               # play live
        self.assertFalse(self.call('?mode=4&url=search'))
        self.assertEqual(self.built, 0)
        self.assertIs(sys.modules['xbmcgui'].ListItem, FakeListItem)       # class restored


if __name__ == '__main__':
    unittest.main()
