"""Saved lists: a POV list is recorded once and replayed on the next visit,
but never once something it depends on has changed."""

import importlib.util
import json
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


class FakeTag(object):
    def __init__(self, log):
        self.log = log

    def __getattr__(self, name):
        return lambda *a, **k: self.log.append(('tag', name, a, k))


class FakeListItem(object):
    def __init__(self, offscreen=True):
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
        self.opens_window = True    # False: a home row (the home screen stays)
        self.builtins = []
        self.xbmc = types.SimpleNamespace(log=lambda *a: None, LOGINFO=1, LOGWARNING=2, Actor=FakeActor,
                                          getInfoLabel=lambda k: env.labels_gui.get(k, ''),
                                          executebuiltin=lambda c: env.builtins.append(c))
        self.xbmcgui = types.SimpleNamespace(ListItem=FakeListItem)
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

    def test_a_watch_change_rebuilds_at_once(self):
        self.open()
        c = sqlite3.connect(str(self.env.profile / 'watched.db'))
        c.execute("insert into watched_status values ('movie','1',0,0,'2026-10-17 10:00:00','x')")
        c.commit(); c.close()
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
        path = next((self.env.profile / 'povil_snapshots').glob('*.json'))
        data = json.loads(path.read_text()); data['created'] -= 5 * 3600
        path.write_text(json.dumps(data))
        self.env.label = 'Today'
        sent = self.open()
        self.assertEqual(self.labels(sent)[0], 'Movie 0')                 # shown at once
        self.assertEqual(len([s for s in sent if s[0] == 'endOfDirectory']), 1)   # shadow build sent nothing
        self.assertEqual(self.env.built, 2)
        self.assertEqual(self.labels(self.open())[0], 'Today 0')         # next visit: today's list

    def test_too_old_lists_are_built_normally(self):
        self.open()
        path = next((self.env.profile / 'povil_snapshots').glob('*.json'))
        data = json.loads(path.read_text()); data['created'] -= 25 * 3600
        path.write_text(json.dumps(data))
        self.open()
        self.assertEqual(self.env.built, 2)

    def test_unrecordable_lists_are_never_saved(self):
        self.env.extra_arg = object()
        self.open(); self.open()
        self.assertEqual(self.env.built, 2)
        self.assertFalse(list((self.env.profile / 'povil_snapshots').glob('*.json')) if
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
            path = next((self.env.profile / 'povil_snapshots').glob('*.json'))
            data = json.loads(path.read_text()); data['created'] -= 5 * 3600
            path.write_text(json.dumps(data))
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
        path = next((self.env.profile / 'povil_snapshots').glob('*.json'))
        data = json.loads(path.read_text()); data['day'] = day
        path.write_text(json.dumps(data))

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
        self.assertEqual(len(list((self.env.profile / 'povil_snapshots').glob('*.json'))), 1)

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
                         list((self.env.profile / 'povil_snapshots').glob('*.json')))

    def test_a_recording_failure_still_sends_real_items(self):
        orig = self.m.Recorder._index
        with mock.patch.object(self.m.Recorder, '_index', side_effect=RuntimeError('x')):
            sent = self.open()
        rows = [x for x in sent if x[0] == 'addDirectoryItems'][0][2][0]
        self.assertTrue(all(isinstance(li, FakeListItem) for _u, li, _f in rows))
        self.open()
        self.assertEqual(self.env.built, 2)                                # not saved


if __name__ == '__main__':
    unittest.main()
