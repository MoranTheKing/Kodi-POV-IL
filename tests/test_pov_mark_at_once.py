"""Wizard 0.5.6: a film or an episode marked watched in POV shows its mark at once (pov_list_snapshot.py).

The owner, Nov 2026: "marking watched in POV takes a while to show -- I want it at once". In the QA Kodi the
mark took 2.3 s on a fast PC: POV loaded to write it, the saved copy was shown without it, the rebuild waited
1.5 s for the home rows, POV loaded again, and only its refresh showed the mark.
"""
import importlib.util
import sqlite3
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_pov_list_snapshot as base      # its fake Kodi and POV-like route

MOVIE_MENU = [['[B]Options...[/B]', 'RunPlugin(plugin://plugin.video.pov/?mode=options_menu_choice&mediatype=movie&tmdb_id=27205)'],
              ['[B]Clear Progress[/B]', 'RunPlugin(plugin://plugin.video.pov/?mode=watched_unwatched_erase_bookmark&mediatype=movie&tmdb_id=27205&refresh=true)'],
              ['[B]Mark Watched POV[/B]', 'RunPlugin(plugin://plugin.video.pov/?mode=mark_as_watched_unwatched_movie&action=mark_as_watched&tmdb_id=27205&title=Film&year=2010)']]


def movie(tmdb='27205', playcount=0, menu=None, resume=True):
    ops = [['L', 'addContextMenuItems', [[list(e) for e in (menu or MOVIE_MENU)]], {}],
           ['L', 'setProperties', [{'pov_sort_order': '1', 'watchedprogress': '40'}], {}],
           ['L', 'getVideoInfoTag', [], {}],
           ['t', 'setUniqueIDs', [{'imdb': 'tt1375666', 'tmdb': tmdb}], {}],
           ['t', 'setMediaType', ['movie'], {}],
           ['t', 'setPlaycount', [playcount], {}]]
    if resume:
        ops.append(['t', 'setResumePoint', [600.0, 6000], {}])
    return ops


def episode(season=1, number=2, watched=False):
    action = 'mark_as_unwatched' if watched else 'mark_as_watched'
    label = '[B]Mark Unwatched POV[/B]' if watched else '[B]Mark Watched POV[/B]'
    ops = [['L', 'addContextMenuItems', [[{'__tuple__': [label, 'RunPlugin(plugin://plugin.video.pov/?mode=mark_as_watched_unwatched_episode'
                                                         '&action=%s&year=2025&tmdb_id=247718&tvdb_id=1&season=%d&episode=%d&title=x)'
                                                         % (action, season, number)]}]], {}],
           ['L', 'setProperties', [{'episode_type': 'standard', 'watchedprogress': '0'}], {}],
           ['L', 'getVideoInfoTag', [], {}],
           ['t', 'setMediaType', ['episode'], {}],
           ['t', 'setEpisode', [number], {}],
           ['t', 'setSeason', [season], {}],
           ['t', 'setUniqueIDs', [{'imdb': 'tt1', 'tmdb': '247718', 'tvdb': '1'}], {}]]
    if watched:
        ops.append(['t', 'setPlaycount', [1], {}])
    return ops


class Window(object):
    def __init__(self):
        self.values = {}

    def getProperty(self, key):
        return self.values.get(key, '')

    def setProperty(self, key, value):
        self.values[key] = value


def module():
    env = types.SimpleNamespace(log=lambda *a: None, LOGINFO=1, LOGWARNING=2)
    with mock.patch.dict(sys.modules, {'xbmc': env}):
        spec = importlib.util.spec_from_file_location('snap_mark_test', base.MOD)
        loaded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded)
    return loaded


class NotingTests(unittest.TestCase):
    def setUp(self):
        self.m = module()
        self.builtins = []
        self.screen = {'Container.PluginName': 'plugin.video.pov'}
        self.xbmc = types.SimpleNamespace(getInfoLabel=lambda key: self.screen.get(key, ''),
                                          executebuiltin=self.builtins.append)
        self.win = Window()

    def test_a_film_or_an_episode_marked_from_a_list_is_noted(self):
        of = self.m._mark_of
        self.assertEqual(of({'mode': 'mark_as_watched_unwatched_movie', 'action': 'mark_as_watched', 'tmdb_id': '27205'}),
                         ('movie', '27205', '', '', True))
        self.assertEqual(of({'mode': 'mark_as_watched_unwatched_episode', 'action': 'mark_as_unwatched', 'tmdb_id': '247718',
                             'season': '01', 'episode': '2'}), ('episode', '247718', '1', '2', False))
        for params in ({'mode': 'mark_as_watched_unwatched_season', 'action': 'mark_as_watched', 'tmdb_id': '1'},   # a batch: POV's way
                       {'mode': 'mark_as_watched_unwatched_movie', 'action': 'mark_as_watched', 'tmdb_id': '1', 'from_playback': 'true'},
                       {'mode': 'mark_as_watched_unwatched_movie', 'action': 'mark_as_watched', 'tmdb_id': '1', 'refresh': 'false'},
                       {'mode': 'mark_as_watched_unwatched_movie', 'action': 'other', 'tmdb_id': '1'},
                       {'mode': 'mark_as_watched_unwatched_movie', 'action': 'mark_as_watched', 'tmdb_id': 'x'},
                       {'mode': 'mark_as_watched_unwatched_episode', 'action': 'mark_as_watched', 'tmdb_id': '1', 'season': '0', 'episode': '1'},
                       {'mode': 'mark_as_watched_unwatched_episode', 'action': 'mark_as_watched', 'tmdb_id': '1', 'season': '1'},
                       {'mode': 'build_movie_list'}):
            self.assertIsNone(of(params), params)

    def test_the_list_is_asked_again_at_once_the_way_pov_would_ask(self):
        params = {'mode': 'mark_as_watched_unwatched_movie', 'action': 'mark_as_watched', 'tmdb_id': '27205'}
        self.assertTrue(self.m._note_mark(self.xbmc, self.win, params, now=1000.0))
        self.assertEqual(self.builtins, ['Container.Refresh'], 'an open POV list')
        self.assertEqual(self.m._pending_marks(self.win, 1001.0), [('movie', '27205', '', '', True, 1000.0)])
        self.screen['Container.PluginName'] = ''
        self.m._note_mark(self.xbmc, self.win, dict(params, tmdb_id='5'), now=1002.0)
        self.assertEqual(self.builtins[-1], 'UpdateLibrary(video,special://skin/foo)', 'the home rows')
        self.assertFalse(self.m._note_mark(self.xbmc, self.win, {'mode': 'build_movie_list'}))
        self.assertEqual(len(self.builtins), 2)

    def test_marks_are_kept_for_half_a_minute_and_a_title_has_one(self):
        note = lambda tmdb, action, at: self.m._note_mark(self.xbmc, self.win, {
            'mode': 'mark_as_watched_unwatched_movie', 'action': action, 'tmdb_id': tmdb}, now=at)
        note('1', 'mark_as_watched', 100.0)
        note('2', 'mark_as_watched', 101.0)
        note('1', 'mark_as_unwatched', 102.0)             # the viewer changed their mind
        marks = self.m._pending_marks(self.win, 103.0)
        self.assertEqual([(m[1], m[4]) for m in marks], [('2', True), ('1', False)])
        self.assertEqual(self.m._pending_marks(self.win, 101.0 + self.m.MARK_LIFE_S + 0.5), [('movie', '1', '', '', False, 102.0)])
        self.assertEqual(self.m._pending_marks(self.win, 102.0 + self.m.MARK_LIFE_S + 1), [])
        for n in range(20):
            note(str(100 + n), 'mark_as_watched', 200.0 + n / 10)
        self.assertEqual(len(self.m._pending_marks(self.win, 203.0)), self.m.MARK_KEEP)
        self.win.values[self.m.MARK_PROPERTY] = 'rubbish;movie|1|||1|not-a-time;movie|1|||7|5'
        self.assertEqual(self.m._pending_marks(self.win, 6.0), [], 'anything else is not a mark')


class ApplyingTests(unittest.TestCase):
    def setUp(self):
        self.m = module()

    def test_a_film_marked_watched_shows_as_pov_builds_a_watched_film(self):
        other = movie('99', playcount=1, resume=False, menu=[
            ['[B]Mark Unwatched POV[/B]', 'RunPlugin(plugin://plugin.video.pov/?mode=mark_as_watched_unwatched_movie&action=mark_as_unwatched&tmdb_id=99&title=x&year=1)']])
        snap = {'items': [movie(), other], 'calls': [], 'created': 5.0}
        shown = self.m._marked(snap, [('movie', '27205', '', '', True, 1.0)])
        self.assertIsNot(shown, snap)
        self.assertEqual(snap['items'][0], movie(), 'the saved record itself is not touched')
        ops = shown['items'][0]
        self.assertIn(['t', 'setPlaycount', [1], {}], ops)
        self.assertEqual([op for op in ops if op[1] == 'setResumePoint'], [], 'no place to resume from')
        self.assertEqual(self.m._op_value(ops, 'L', 'setProperties')['watchedprogress'], '0')
        menu = self.m._op_value(ops, 'L', 'addContextMenuItems')
        self.assertEqual([e[0] for e in menu], ['[B]Options...[/B]', '[B]Mark Unwatched POV[/B]'],
                         'no "clear progress"; the entry offers the opposite, in POV\'s own words (seen on another title)')
        self.assertIn('action=mark_as_unwatched&tmdb_id=27205&', menu[1][1])
        self.assertIs(shown['items'][1], snap['items'][1], 'another title is not touched')
        self.assertEqual(shown['created'], 5.0)
        # and back
        again = self.m._marked(shown, [('movie', '27205', '', '', False, 2.0)])
        back = again['items'][0]
        self.assertIn(['t', 'setPlaycount', [0], {}], back)
        self.assertIn('action=mark_as_watched&tmdb_id=27205&', self.m._op_value(back, 'L', 'addContextMenuItems')[1][1])

    def test_pov_words_not_seen_yet_leave_the_label_and_the_window_remembers_them(self):
        win = Window()
        snap = {'items': [movie()], 'calls': []}
        shown = self.m._marked(snap, [('movie', '27205', '', '', True, 1.0)], win)
        menu = self.m._op_value(shown['items'][0], 'L', 'addContextMenuItems')
        self.assertEqual(menu[-1][0], '[B]Mark Watched POV[/B]', 'the old label until the rebuild; the action is already right')
        self.assertIn('action=mark_as_unwatched&', menu[-1][1])
        self.assertEqual(win.values[self.m.MARK_LABELS_PROPERTY + 'movie'], '[B]Mark Watched POV[/B]\x1f')
        # a later list shows the other word; from then on both are known in this Kodi session
        watched = movie('99', playcount=1, menu=[['[B]Mark Unwatched POV[/B]', MOVIE_MENU[2][1].replace('mark_as_watched&', 'mark_as_unwatched&')]])
        self.m._mark_labels([watched], 'movie', win)
        shown = self.m._marked(snap, [('movie', '27205', '', '', True, 1.0)], win)
        self.assertEqual(self.m._op_value(shown['items'][0], 'L', 'addContextMenuItems')[-1][0], '[B]Mark Unwatched POV[/B]')

    def test_an_episode_is_found_by_show_season_and_number(self):
        snap = {'items': [episode(1, 1), episode(1, 2), episode(2, 2)], 'calls': []}
        shown = self.m._marked(snap, [('episode', '247718', '1', '2', True, 1.0)])
        self.assertIs(shown['items'][0], snap['items'][0])
        self.assertIs(shown['items'][2], snap['items'][2])
        ops = shown['items'][1]
        self.assertEqual(ops[-1], ['t', 'setPlaycount', [1], {}], 'POV sets no play count on an unwatched episode: added')
        entry = self.m._op_value(ops, 'L', 'addContextMenuItems')[0]
        self.assertEqual(set(entry), {'__tuple__'}, 'recorded as a tuple, kept as one')
        self.assertIn('action=mark_as_unwatched&', entry['__tuple__'][1])
        unwatched = self.m._marked({'items': [episode(1, 2, watched=True)], 'calls': []}, [('episode', '247718', '1', '2', False, 1.0)])
        self.assertIn(['t', 'setPlaycount', [0], {}], unwatched['items'][0])

    def test_nothing_to_change_gives_the_record_itself(self):
        snap = {'items': [movie(playcount=1, resume=False, menu=[MOVIE_MENU[0]])], 'calls': []}
        snap['items'][0][1] = ['L', 'setProperties', [{'pov_sort_order': '1', 'watchedprogress': '0'}], {}]
        self.assertIs(self.m._marked(snap, [('movie', '27205', '', '', True, 1.0)]), snap, 'already shows it')
        self.assertIs(self.m._marked(snap, [('movie', '1', '', '', True, 1.0)]), snap, 'not in this list')
        self.assertIs(self.m._marked(snap, []), snap)
        self.assertIs(self.m._marked({'items': 'broken'}, [('movie', '1', '', '', True, 1.0)])['items'], 'broken')


class EarlyTests(unittest.TestCase):
    """Through serve_early(), with the fake Kodi of the saved-lists tests and a route that builds films
    the way POV does (ids, a play count, the menu entry that marks)."""
    QUERY = base.SnapshotTests.QUERY

    def setUp(self):
        base.SnapshotTests.setUp(self)
        self.win = Window()
        self.env.xbmcgui.Window = lambda _id: self.win
        env = self.env

        def route(sys_obj):
            env.built += 1
            handle = int(sys_obj.argv[1])
            con = sqlite3.connect(str(env.profile / 'watched.db'))
            watched = {str(row[0]) for row in con.execute("select media_id from watched_status where db_type='movie'")}
            con.close()
            items = []
            for n in range(3):
                tmdb = str(100 + n)
                seen = tmdb in watched
                li = env.ku.make_listitem()
                li.addContextMenuItems([('[B]Mark %s POV[/B]' % ('Unwatched' if seen else 'Watched'),
                                         'RunPlugin(plugin://plugin.video.pov/?mode=mark_as_watched_unwatched_movie&action=%s&tmdb_id=%s&title=x&year=1)'
                                         % ('mark_as_unwatched' if seen else 'mark_as_watched', tmdb))])
                li.setProperty('pov_sort_order', str(n))
                li.setLabel('Movie %d' % n)
                tag = li.getVideoInfoTag()
                tag.setUniqueIDs({'imdb': 'tt%d' % n, 'tmdb': tmdb})
                tag.setMediaType('movie')
                tag.setPlaycount(1 if seen else 0)
                items.append(('plugin://x/?n=%d' % n, li, False))
            env.xbmcplugin.addDirectoryItems(handle, items)
            env.xbmcplugin.setContent(handle, 'movies')
            env.xbmcplugin.endOfDirectory(handle, cacheToDisc=None)
        self.routing = self.m.wrap(route, {'kodi_utils': env.ku})
        env.parent['Container.FolderPath'] = 'plugin://plugin.video.pov/' + self.QUERY     # the list itself is open

    def open(self, handle=7):
        return base.SnapshotTests.open(self, handle=handle)

    def early(self, argv):
        fake_pov = types.SimpleNamespace(kodi_utils=self.env.ku)
        with mock.patch.dict(sys.modules, {'modules': fake_pov, 'modules.kodi_utils': self.env.ku}):
            self.env.sent = []
            self.env.labels_gui = dict(self.env.parent)
            self.env.query = self.QUERY
            return self.m.serve_early(argv)

    def counts(self):
        rows = [s for s in self.env.sent if s[0] == 'addDirectoryItems'][0][2][0]
        return [[e[2][0] for e in li.log if e[0] == 'tag' and e[1] == 'setPlaycount'][-1] for _u, li, _f in rows]

    MARK = ['plugin://plugin.video.pov/', '-1', '?mode=mark_as_watched_unwatched_movie&action=mark_as_watched&tmdb_id=101&title=x']

    def test_the_marking_route_is_noted_before_pov_loads_and_pov_still_does_the_marking(self):
        self.open()
        self.assertFalse(self.early(self.MARK), 'False: POV goes on and writes the mark')
        self.assertEqual(self.env.builtins[-1], 'Container.Refresh')
        self.assertEqual([m[:5] for m in self.m._pending_marks(self.win)], [('movie', '101', '', '', True)])
        self.assertEqual(self.env.sent, [], 'a route with no list answers nothing')

    def test_a_child_profile_notes_nothing(self):
        self.env.child = True
        self.assertFalse(self.early(self.MARK))
        marks = {k: v for k, v in self.win.values.items() if k != self.m.ACTION_PROPERTY}
        self.assertEqual((self.env.builtins, marks), ([], {}))
        # (every POV action leaves its time for the home's trailers, on any profile: nothing starts under it)
        self.assertIn(self.m.ACTION_PROPERTY, self.win.values)

    def test_the_copy_is_shown_with_the_mark_at_once_and_the_rebuild_does_not_wait(self):
        self.open()
        argv = ['plugin://plugin.video.pov/', '9', self.QUERY]
        self.assertTrue(self.early(argv))
        self.assertEqual(self.counts(), [0, 0, 0])
        # the press: noted, the list asked again -- shown with the mark though no database has it yet
        self.early(self.MARK)
        built = self.env.built
        self.assertTrue(self.early(argv), 'nothing changed on disk: shown, and not rebuilt')
        self.assertEqual(self.counts(), [0, 1, 0])
        self.assertEqual(self.env.built, built, 'POV was not needed for it')
        # POV wrote the mark and asks again, as it always did: the marked copy, and the rebuild at once
        con = sqlite3.connect(str(self.env.profile / 'watched.db'))
        con.execute("insert into watched_status values ('movie','101',0,0,'2026-11-18 10:00:00','x')")
        con.commit(); con.close()
        waits = []
        with mock.patch.object(self.m, '_wait_rows_quiet', lambda xbmc, quiet=1.5, cap=20.0: waits.append(quiet) or True):
            self.assertFalse(self.early(argv), 'shown; POV rebuilds it behind')
        self.assertEqual(self.counts(), [0, 1, 0])
        self.assertEqual(waits, [0.0], "no 1.5 s for the home rows after the viewer's own mark")
        self.assertIs(self.m.EARLY[9][2], True)
        # the rebuild is compared with what is on screen: the same list (the label too, once POV's
        # word for it has been seen), so nothing flickers a third time
        refreshes = len(self.env.builtins)
        self.env.sent = []
        self.routing(types.SimpleNamespace(argv=argv))
        self.assertEqual(self.env.built, built + 1)
        changed = self.env.builtins[refreshes:]
        self.assertIn(changed, ([], ['Container.Refresh']))
        # a second film marked right after: both marks are on the next copy shown
        self.early(['plugin://plugin.video.pov/', '-1', '?mode=mark_as_watched_unwatched_movie&action=mark_as_watched&tmdb_id=102'])
        self.early(argv)
        self.assertEqual(self.counts(), [0, 1, 1])
        # without a pending mark a watch change waits for the rows as before (an episode just played)
        self.win.values.clear()
        con = sqlite3.connect(str(self.env.profile / 'watched.db'))
        con.execute("insert into watched_status values ('movie','100',0,0,'2026-11-18 10:01:00','x')")
        con.commit(); con.close()
        waits = []
        with mock.patch.object(self.m, '_wait_rows_quiet', lambda xbmc, quiet=1.5, cap=20.0: waits.append(quiet) or True):
            self.early(argv)
        self.assertEqual(waits, [1.5])


if __name__ == '__main__':
    unittest.main()
