"""Wizard 0.5.41 + Onyx 1.0.37: the number on a picture's corner is the average of the sites' ratings.

The owner, Nov 2026 (and a viewer the day before): a poster said 6.6 where the row beside the title said TMDb 6.5,
IMDb 6.6 and Trakt 71% -- "the average on the poster is not the average ... I did not understand where this 6.6 was
made up from"; a new film with no votes on TMDb showed no number while Trakt had one. The corner showed POV's own
figure (TMDb's) alone.

patches/pov_rating.py holds the sums; ratings.py answers the average with the sites and keeps every title's sum in
one file; POV's lists (and their saved copies, pov_list_snapshot.py) put the average on each picture; the skin shows
it, and ends the row of sites with it.
"""
import importlib.util
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'plugin.program.kodipovilwizard'
PATCHES = WIZARD / 'resources/libs/patches'
XML = ROOT / 'skin.povil.onyx/xml'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rating = load('pov_rating', PATCHES / 'pov_rating.py')
ratings = load('ratings_for_average', WIZARD / 'resources/libs/ratings.py')
snapshot = load('snapshot_for_average', PATCHES / 'pov_list_snapshot.py')

# what the owner saw beside "A Story of Derry"
DERRY = {'tmdb': '6.5', 'imdb': '6.6', 'imdb_votes': '12K', 'trakt': '71%'}
# what Trakt answered for a film on 17 Nov 2026 (tests/test_ratings.py), as the row shows it
FILM = {'tmdb': '8.4', 'imdb': '8.8', 'trakt': '88%', 'tomato': '87%', 'tomato_state': 'fresh', 'popcorn': '91%',
        'popcorn_state': 'upright', 'meta': '74', 'meta_tone': 'good', 'letterboxd': '4.2'}


class Item(object):
    def __init__(self):
        self.properties = {}

    def setProperty(self, key, value):
        self.properties[key] = value


class SumTests(unittest.TestCase):
    def test_the_owners_poster(self):
        """6.5, 6.6 and 71% make 6.7 -- not the 6.6 the poster showed."""
        self.assertEqual(rating.entry_of(DERRY), [65 + 66 + 71, 3, True])
        self.assertEqual(rating.average(rating.entry_of(DERRY), '6.6'), '6.7')

    def test_every_site_counts_out_of_ten(self):
        # 8.4 + 8.8 + 8.8 + 8.7 + 9.1 + 7.4 + 8.4 (4.2 of 5) = 59.6 over 7 sites = 8.51
        self.assertEqual(rating.entry_of(FILM), [84 + 88 + 88 + 87 + 91 + 74 + 84, 7, True])
        self.assertEqual(rating.average(rating.entry_of(FILM)), '8.5')
        # words about a figure (a verdict, a count of votes) are not figures
        self.assertIsNone(rating.entry_of({'tomato_state': 'fresh', 'imdb_votes': '2.8M', 'meta_tone': 'good'}))
        self.assertEqual([site for site, _scale in rating.SITES],
                         ['tmdb', 'imdb', 'trakt', 'tomato', 'popcorn', 'meta', 'letterboxd'],
                         'the sites the row shows (tools/skin_onyx/ratings_row.py UNITS), no other')

    def test_a_new_film_with_no_votes_on_tmdb_takes_what_there_is(self):
        """The film beside it: nothing from TMDb, a rating on Trakt."""
        self.assertEqual(rating.average(rating.entry_of({'trakt': '78%'}), ''), '7.8')
        self.assertEqual(rating.average(rating.entry_of({'trakt': '78%'}), '0.0'), '7.8')

    def test_the_lists_own_figure_counts_only_when_trakt_gave_none_for_tmdb(self):
        # the row shows the list's figure as TMDb's then: it is one of the sites averaged
        self.assertEqual(rating.average(rating.entry_of({'imdb': '7.0'}), '8.0'), '7.5')
        # Trakt gave TMDb's: the list's own copy of it is not counted twice
        self.assertEqual(rating.average(rating.entry_of({'imdb': '7.0', 'tmdb': '7.0'}), '9.9'), '7.0')

    def test_a_title_not_asked_about_yet_shows_the_one_site_known_and_nothing_is_invented(self):
        self.assertEqual(rating.average(None, '6.6'), '6.6')
        self.assertEqual(rating.average(None, ''), '')
        self.assertEqual(rating.average([0, 0, False], ''), '')
        self.assertEqual(rating.average('nonsense', '7.1'), '7.1')
        self.assertEqual(rating.shown(6.634), '6.6')
        self.assertEqual(rating.shown(0.0), '')
        self.assertEqual(rating.shown(None), '')
        # Kodi keeps a rating in four bytes: 6.05 is a hair above itself there and the screen says 6.1
        self.assertEqual(rating.shown(6.05), '6.1')
        self.assertEqual('%.1f' % 6.05, '6.0', 'what eight bytes would have said')

    def test_half_a_tenth_rounds_up_as_a_person_would(self):
        self.assertEqual(rating.average([65 + 66, 2, True]), '6.6')     # 6.55
        self.assertEqual(rating.average([100, 1, True]), '10.0')

    def test_a_title_is_named_as_the_wizards_store_names_it(self):
        for key, kind, season, episode in (('tt1375666|movie||', 'movie', None, None),
                                           ('tt0903747|tvshow||', 'tvshow', '', ''),
                                           ('tt0903747|season|2|', 'season', 2, None),
                                           ('tt0903747|episode|5|14', 'episode', 5, 14)):
            self.assertEqual(rating.store_name(key.split('|')[0], kind, season, episode), ratings.parse(key)[0], key)
        self.assertIsNone(rating.store_name('', 'movie'))
        self.assertIsNone(rating.store_name('tt1', 'episode', None, 3))
        self.assertIsNone(rating.store_name('nm123', 'movie'))


class FileTests(unittest.TestCase):
    def test_the_one_file_is_read_with_marshal_and_only_when_it_changed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / rating.INDEX)
            self.assertEqual(rating.read_index(path), {})
            self.assertTrue(rating.write_index(path, {'movie-tt1': [202, 3, True]}))
            self.assertEqual(rating.read_index(path), {'movie-tt1': [202, 3, True]})
            clock = [100.0]
            self.assertEqual(rating.index(path, clock=lambda: clock[0]), {'movie-tt1': [202, 3, True]})
            with mock.patch.object(rating, 'read_index', side_effect=AssertionError('read again')):
                self.assertEqual(rating.index(path, clock=lambda: clock[0]), {'movie-tt1': [202, 3, True]})
                clock[0] += 60          # looked at again, found unchanged: still not read
                self.assertEqual(rating.index(path, clock=lambda: clock[0]), {'movie-tt1': [202, 3, True]})
            Path(path).write_bytes(b'not ours')
            clock[0] += 60
            self.assertEqual(rating.index(path, clock=lambda: clock[0]), {})
        source = (PATCHES / 'pov_rating.py').read_text('utf-8')
        self.assertNotIn('import json', source, "a list's process imports no json for this (pov_list_snapshot.py)")


class ItemTests(unittest.TestCase):
    TITLES = {'movie-tt31938062': [202, 3, True], 'movie-tt2': [78, 1, False]}

    def test_pov_gives_an_item_its_average_and_what_it_was_worked_out_from(self):
        item = Item()
        self.assertEqual(rating.stamp(item, 'tt31938062', 'movie', 6.634, titles=self.TITLES), '6.7')
        self.assertEqual(item.properties, {'povil_avg': '6.7', 'povil_avg_src': 'movie-tt31938062|6.6'})
        # the film with no votes on TMDb
        item = Item()
        rating.stamp(item, 'tt2', 'movie', 0.0, titles=self.TITLES)
        self.assertEqual(item.properties, {'povil_avg': '7.8', 'povil_avg_src': 'movie-tt2|'})
        # a title the Wizard has not asked about: POV's own figure, the one site known
        item = Item()
        rating.stamp(item, 'tt3', 'tvshow', 8.04, titles=self.TITLES)
        self.assertEqual(item.properties, {'povil_avg': '8.0', 'povil_avg_src': 'show-tt3|8.0'})
        # an item that names no title is left alone
        item = Item()
        self.assertEqual(rating.stamp(item, '', 'movie', 7.0, titles=self.TITLES), '')
        self.assertEqual(item.properties, {})

    def test_a_saved_list_shows_the_average_of_the_moment(self):
        """The list was saved when the title was not known; the Wizard asked about it since."""
        ops = [['L', 'setLabel', ['A Story of Derry'], {}],
               ['L', 'setProperty', ['povil_avg_src', 'movie-tt31938062|6.6'], {}],
               ['L', 'setProperty', ['povil_avg', '6.6'], {}]]
        made = []

        class ListItem(Item):
            def __init__(self, *args, **kwargs):
                Item.__init__(self)
                made.append(self)

            def setLabel(self, label):
                pass
        gui = types.SimpleNamespace(ListItem=ListItem)
        with mock.patch.dict(sys.modules, {'pov_rating': rating}), \
                mock.patch.object(rating, 'index', return_value=self.TITLES):
            snapshot._build(ops, None, gui)
        self.assertEqual(made[0].properties['povil_avg'], '6.7')
        self.assertEqual((snapshot.RATING_SOURCE, snapshot.RATING_AVERAGE), (rating.SOURCE, rating.PROPERTY))

    def test_two_records_that_differ_only_in_the_average_are_the_same_list(self):
        """A list rebuilt behind its saved copy must not ask every row again for a number the copy already shows."""
        def record(average, label='A'):
            return {'calls': [['endOfDirectory', [], {}]],
                    'items': [[['L', 'setLabel', [label], {}], ['L', 'setProperty', ['povil_avg_src', 'movie-tt1|6.6'], {}],
                               ['L', 'setProperty', ['povil_avg', average], {}]]]}
        self.assertTrue(snapshot._same(record('6.6'), record('6.7')))
        self.assertFalse(snapshot._same(record('6.6'), record('6.6', label='B')))


class Home(object):
    def __init__(self, **properties):
        self.properties = dict(properties)
        self.writes = []

    def getProperty(self, key):
        return self.properties.get(key, '')

    def setProperty(self, key, value):
        self.properties[key] = value
        self.writes.append(key)


TRAKT = {'trakt': {'rating': 7.08, 'votes': 900}, 'tmdb': {'rating': 6.5, 'votes': 300}, 'imdb': {'rating': 6.6, 'votes': 12000}}


class AnswerTests(unittest.TestCase):
    def test_the_average_is_answered_with_the_sites(self):
        home = Home(**{'povil.rt.ask': 'tt31938062|movie||', 'povil.rt.list': '6.6'})
        self.assertTrue(ratings.publish(home, 'povil.rt.', 'tt31938062|movie||', ratings.shape(TRAKT)))
        self.assertEqual(home.properties['povil.rt.avg'], '6.7')
        self.assertEqual(home.writes[-1], 'povil.rt.for', 'the title the fields belong to is still written last')
        # the list's figure stands in for TMDb's when Trakt gave none
        home = Home(**{'povil.rt.ask': 'tt0903747|episode|5|14', 'povil.rt.list': '9.0'})
        ratings.publish(home, 'povil.rt.', 'tt0903747|episode|5|14', {'imdb': '9.6'})
        self.assertEqual(home.properties['povil.rt.avg'], '9.3')
        # nothing known anywhere: no number
        home = Home(**{'povil.rt.ask': 'tt9|movie||'})
        ratings.publish(home, 'povil.rt.', 'tt9|movie||', {})
        self.assertEqual(home.properties['povil.rt.avg'], '')
        # the player's row has its average too
        home = Home(**{'povil.rtp.ask': 'tt1|movie||'})
        ratings.publish(home, 'povil.rtp.', 'tt1|movie||', {'imdb': '7.0'})
        self.assertEqual(home.properties['povil.rtp.avg'], '7.0')


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = [1000000.0]
        self.calls = []

    def store(self, answers=None):
        def fetch(path):
            self.calls.append(path)
            return (answers or {}).get(path, (200, TRAKT))
        return ratings.Store(self.tmp.name, fetch, clock=lambda: self.now[0])

    def index(self):
        return rating.read_index(str(Path(self.tmp.name) / rating.INDEX))

    def test_every_answer_reaches_the_one_file_a_moment_later(self):
        store = self.store()
        store.lookup('tt1|movie||')
        self.assertEqual(store.learned, 1)
        self.assertTrue(store.flush())
        self.assertEqual(self.index(), {'movie-tt1': [65 + 66 + 71, 3, True]})
        # the next titles are written together, not one write per title
        store.lookup('tt2|movie||')
        self.assertFalse(store.flush(), 'written a moment ago')
        store.lookup('tt3|movie||')
        self.now[0] += ratings.INDEX_EVERY
        self.assertTrue(store.flush())
        self.assertEqual(sorted(self.index()), ['movie-tt1', 'movie-tt2', 'movie-tt3'])
        with mock.patch.object(ratings.pov_rating, 'write_index', side_effect=AssertionError('written again')):
            self.assertTrue(store.flush(force=True), 'nothing changed: the file holds everything, nothing is written')

    def test_the_same_figures_again_are_not_news(self):
        store = self.store()
        store.lookup('tt1|movie||')
        self.now[0] += ratings.KEEP + 1
        store.lookup('tt1|movie||')
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(store.learned, 1)

    def test_an_answer_that_leaves_the_picture_as_it_was_is_not_news(self):
        """The picture showed TMDb's figure; the answer has that one figure, or figures that average to it."""
        store = self.store({'/movies/tt1/ratings': (200, {'tmdb': {'rating': 7.0, 'votes': 10}}),
                            '/movies/tt2/ratings': (200, {'tmdb': {'rating': 7.0, 'votes': 10}, 'imdb': {'rating': 7.0}}),
                            '/movies/tt3/ratings': (200, {'trakt': {'rating': 7.8, 'votes': 9}})})
        store.lookup('tt1|movie||')
        store.lookup('tt2|movie||')
        self.assertEqual(store.learned, 0)
        store.lookup('tt3|movie||')             # the picture had no number: now it has
        self.assertEqual(store.learned, 1)
        self.assertTrue(store.flush(force=True))
        self.assertEqual(sorted(self.index()), ['movie-tt1', 'movie-tt2', 'movie-tt3'], 'kept all the same')

    def test_a_write_that_fails_is_tried_again(self):
        """POV's process may hold the file for a moment (Windows)."""
        store = self.store()
        store.lookup('tt1|movie||')
        with mock.patch.object(ratings.pov_rating, 'write_index', return_value=False):
            self.assertFalse(store.flush(force=True))
        self.assertEqual(self.index(), {})
        self.assertTrue(store.flush(force=True))
        self.assertEqual(sorted(self.index()), ['movie-tt1'])

    def test_a_title_with_no_figures_is_not_in_the_file(self):
        store = self.store({'/movies/tt1/ratings': (200, {})})
        store.lookup('tt1|movie||')
        self.assertEqual(store.learned, 0)
        store.flush(force=True)
        self.assertEqual(self.index(), {})

    def test_the_file_is_gathered_from_the_titles_own_files_when_it_is_missing(self):
        """The first start after the update: the store is full, the file is new."""
        first = self.store()
        first.lookup('tt1|movie||')
        first.lookup('tt2|tvshow||')
        self.assertEqual(self.index(), {})
        second = self.store()
        self.assertTrue(second.flush(force=True))
        self.assertEqual(sorted(self.index()), ['movie-tt1', 'show-tt2'])
        self.assertEqual(second.learned, 0, 'gathered, not learned: the rows are not asked again for it')


class RefreshTests(unittest.TestCase):
    """Kodi works a picture's number out when its row is loaded, not again (seen on the QA Kodi's screen): what is
    learned after a row was loaded reaches its pictures by loading the rows again."""

    def desk(self, allowed=True, screen=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = [1000000.0]
        self.refreshes = []
        self.allowed = [allowed]
        self.screen = screen if screen is not None else {}

        def refresh(soon):
            if self.allowed[0]:
                self.refreshes.append({None: 'later', 'home': 'soon', 'view': 'the list'}[soon])
            return self.allowed[0]
        store = ratings.Store(self.tmp.name, lambda path: (200, TRAKT), clock=lambda: self.now[0])
        self.home = Home(**{ratings.SKIN_SHOWS: '1'})
        return ratings.Desk(self.home, store, read=lambda label: self.screen.get(label, ''), refresh=refresh)

    def on_screen(self, imdb, average, source=None, row=5011):
        self.screen.update({'System.CurrentControlID': str(row),
                            'Container(%d).ListItem.UniqueID(imdb)' % row: imdb,
                            'Container(%d).ListItem.Property(povil_avg)' % row: average,
                            'Container(%d).ListItem.Property(povil_avg_src)' % row:
                                ('movie-%s|%s' % (imdb, average)) if source is None else source})

    def test_one_refresh_once_nothing_more_is_being_asked(self):
        desk = self.desk()
        self.assertFalse(desk.settle(), 'nothing learned: nothing to refresh')
        for n in range(3):
            desk._put(desk.AHEAD, 'tt%d|movie||' % n, None)
        self.assertTrue(desk.step())
        self.assertFalse(desk.settle(), 'titles are still waiting to be asked')
        self.assertTrue(desk.step())
        self.assertTrue(desk.step())
        self.assertTrue(desk.settle())
        self.assertEqual(self.refreshes, ['later'])
        self.assertFalse(desk.owed())
        self.assertFalse(desk.settle())
        # the file was written before the rows were asked: their lists read it
        self.assertEqual(len(rating.read_index(str(Path(self.tmp.name) / rating.INDEX))), 3)

    def test_not_more_often_than_every_half_minute_and_only_at_the_right_moment(self):
        desk = self.desk()
        desk._put(desk.AHEAD, 'tt1|movie||', None)
        desk.step()
        self.assertTrue(desk.settle())
        desk._put(desk.AHEAD, 'tt2|movie||', None)
        desk.step()
        self.assertFalse(desk.settle(), 'the rows were asked a moment ago')
        self.assertTrue(desk.owed(), 'still owed')
        self.now[0] += ratings.REFRESH_EVERY
        self.allowed[0] = False             # a dialog is open, a trailer plays, a title is starting
        self.assertFalse(desk.settle())
        self.assertTrue(desk.owed())
        self.allowed[0] = True
        self.assertTrue(desk.settle())
        self.assertEqual(self.refreshes, ['later', 'later'])

    def test_the_rows_are_not_asked_again_before_the_file_is_written(self):
        desk = self.desk()
        desk._put(desk.AHEAD, 'tt1|movie||', None)
        with mock.patch.object(ratings.pov_rating, 'write_index', return_value=False):
            desk.step()
            self.assertFalse(desk.settle(), 'the lists would read the old file')
        self.assertEqual(self.refreshes, [])
        self.assertTrue(desk.owed())
        self.assertTrue(desk.settle())

    def test_the_picture_of_the_title_on_screen_is_put_right_at_once(self):
        """The owner's poster: the row beside the title says 6.7, the picture -- loaded before the title was asked
        about -- still says 6.6. That is the one place where both numbers are seen: the rows are asked again now,
        while the titles beside it are still being asked."""
        desk = self.desk()
        self.on_screen('tt50389959', '6.6')
        self.home.properties.update({'povil.rt.ask': 'tt50389959|movie||', 'povil.rt.list': '6.6'})
        for n in range(3):
            desk._put(desk.AHEAD, 'tt%d|movie||' % n, None)
        desk._put(desk.URGENT, 'tt50389959|movie||', 'home')
        self.assertTrue(desk.step())
        self.assertEqual(self.home.properties['povil.rt.avg'], '6.7')
        self.assertTrue(desk.stale)
        self.assertTrue(desk.settle(), 'not waiting for the titles asked ahead')
        self.assertEqual(self.refreshes, ['soon'])
        self.assertFalse(desk.stale)
        # the picture now agrees: nothing more is wanted for it
        self.on_screen('tt50389959', '6.7')
        self.assertFalse(desk.look())

    def test_a_picture_that_agrees_or_that_no_refresh_would_change_asks_for_nothing(self):
        desk = self.desk()
        self.home.properties.update({'povil.rt.ask': 'tt1|movie||', 'povil.rt.for': 'tt1|movie||', 'povil.rt.avg': '6.7'})
        self.on_screen('tt1', '6.7')
        self.assertFalse(desk.look(), 'the picture says what the row says')
        self.on_screen('tt1', '', source='')
        self.assertFalse(desk.look(), "POV's lists gave it no number (no patch in POV): a refresh would change nothing")
        self.on_screen('tt2', '6.6')
        self.assertFalse(desk.look(), 'the focus is on another title already')
        self.on_screen('tt1', '6.6', row=9100)
        self.assertFalse(desk.look(), "not one of the home's rows, nor an open list")
        self.home.properties['povil.rt.ask'] = 'tt2|movie||'
        self.on_screen('tt1', '6.6')
        self.assertFalse(desk.look(), 'the skin asks about another title already')
        self.assertFalse(desk.stale)

    def test_a_picture_is_never_chased(self):
        """A picture that stays behind its row after the refresh (a list that could not be loaded again) is left."""
        desk = self.desk()
        self.home.properties.update({'povil.rt.ask': 'tt1|movie||', 'povil.rt.for': 'tt1|movie||', 'povil.rt.avg': '6.7'})
        self.on_screen('tt1', '6.6')
        self.assertTrue(desk.look())
        self.assertTrue(desk.settle())
        self.assertFalse(desk.look(), 'asked for once')
        self.assertFalse(desk.owed())
        # ... and the next title's picture waits a few seconds after the last refresh
        self.home.properties.update({'povil.rt.ask': 'tt2|movie||', 'povil.rt.for': 'tt2|movie||', 'povil.rt.avg': '7.0'})
        self.on_screen('tt2', '6.0')
        self.assertTrue(desk.look())
        self.assertFalse(desk.settle())
        self.now[0] += ratings.REFRESH_SOON
        self.assertTrue(desk.settle())
        self.assertEqual(self.refreshes, ['soon', 'soon'])

    def test_in_an_open_list_the_list_is_loaded_again(self):
        """The reviewer: in a list of the Videos window a title first asked about there kept its older number."""
        desk = self.desk()
        self.home.properties.update({'povil.rt.ask': 'tt1|movie||', 'povil.rt.for': 'tt1|movie||', 'povil.rt.avg': '6.7'})
        for view in ratings.VIEW_LISTS:
            self.assertIn('id="%d"' % view, (XML / 'View_POVIL.xml').read_text('utf-8'))
        self.on_screen('tt1', '6.6', row=ratings.VIEW_LISTS[0])
        self.assertTrue(desk.look())
        self.assertEqual(desk.stale[0], 'view')
        desk.store.learned = 2              # what the home's rows are owed stays owed: the list says nothing of them
        self.assertTrue(desk.settle())
        self.assertEqual(self.refreshes, ['the list'])
        self.assertEqual(desk.store.learned, 2)
        self.assertEqual((ratings.VIEW_BUILTIN, ratings.REFRESH_VIEW.split(' + ')[0]), ('Container.Refresh', 'Window.IsActive(videos)'))
        self.assertIn('!Player.HasMedia', ratings.REFRESH_VIEW.split(' + '), "Kodi's busy dialog there would stop a trailer")

    def test_nothing_is_owed_on_a_skin_that_shows_no_averages(self):
        """FENtastic, Estuary, an older Onyx: a refresh would change nothing, and the worker would look every
        few seconds for nothing (the reviewer)."""
        desk = self.desk()
        desk._put(desk.AHEAD, 'tt1|movie||', None)
        desk.step()
        self.assertTrue(desk.owed())
        del self.home.properties[ratings.SKIN_SHOWS]
        self.assertFalse(desk.owed())
        self.assertFalse(desk.settle())
        self.assertEqual(self.refreshes, [])

    def test_the_pictures_refresh_waits_for_rest_and_for_the_title_to_be_on_screen(self):
        """The reviewer: a viewer moving across new titles must not get the rows loaded again under every press."""
        for when in (ratings.REFRESH_NOW, ratings.REFRESH_VIEW):
            self.assertIn('System.IdleTime(1)', when.split(' + '))
        desk = self.desk()
        self.home.properties.update({'povil.rt.ask': 'tt1|movie||', 'povil.rt.for': 'tt1|movie||', 'povil.rt.avg': '6.7'})
        self.on_screen('tt1', '6.6')
        self.assertTrue(desk.look())
        # the viewer moved on to the next title before the moment came
        self.home.properties.update({'povil.rt.ask': 'tt2|movie||', 'povil.rt.for': 'tt2|movie||', 'povil.rt.avg': '7.0'})
        self.assertFalse(desk.settle())
        self.assertIsNone(desk.stale)
        self.assertEqual(self.refreshes, [])

    def test_a_refresh_that_found_no_moment_is_dropped(self):
        """The viewer went on -- into a film, to another window: the next load of the rows puts the picture right."""
        desk = self.desk(allowed=False)
        self.home.properties.update({'povil.rt.ask': 'tt1|movie||', 'povil.rt.for': 'tt1|movie||', 'povil.rt.avg': '6.7'})
        self.on_screen('tt1', '6.6')
        self.assertTrue(desk.look())
        self.assertFalse(desk.settle())
        self.assertTrue(desk.owed())
        self.now[0] += ratings.STALE_S
        self.assertFalse(desk.settle())
        self.assertFalse(desk.owed(), 'nothing polls for it any more')

    def test_the_refresh_shows_no_dialog_and_keeps_away_from_what_plays(self):
        """The reviewer: Kodi's scan dialog stops a home trailer (the skin's povil_trailer_stop)."""
        self.assertEqual(ratings.REFRESH_BUILTIN, 'UpdateLibrary(video,special://skin/foo,false)')
        for when in (ratings.REFRESH_WHEN, ratings.REFRESH_NOW):
            for part in ('Window.IsActive(home)', '!System.HasActiveModalDialog', '!Library.IsScanningVideo',
                         'String.IsEmpty(Window(home).Property(povil.tr.opening))'):
                self.assertIn(part, when.split(' + '))
        # for the pictures beside the title: nothing plays; for the picture on screen: at most a trailer over the home
        self.assertTrue(ratings.REFRESH_WHEN.endswith(' + !Player.HasMedia'))
        self.assertIn(' + [!Player.HasMedia | !String.IsEmpty(Window(home).Property(povil.tr.on))] + ', ratings.REFRESH_NOW)
        self.assertGreaterEqual(ratings.REFRESH_EVERY, 30)
        self.assertGreaterEqual(ratings.REFRESH_SOON, 5)
        source = (WIZARD / 'resources/libs/ratings.py').read_text('utf-8')
        watch = source[source.index('def watch():'):]
        self.assertIn('if not home.getProperty(SKIN_SHOWS):\n            return False', watch,
                      'never for a skin that shows no averages')
        self.assertIn('if not xbmc.getCondVisibility(REFRESH_NOW if soon else REFRESH_WHEN):', watch)
        self.assertIn('xbmc.executebuiltin(VIEW_BUILTIN)', watch)
        self.assertIn('xbmc.executebuiltin(REFRESH_BUILTIN)', watch)
        self.assertIn('home.getProperty(PLAY_STARTED)', watch, 'never while a title looks for its sources')
        timers = (XML / 'Timers.xml').read_text('utf-8')
        self.assertIn('<onstart>SetProperty(%s,1,home)</onstart>' % ratings.SKIN_SHOWS, timers)
        self.assertEqual(ratings.ROWS_REFRESHED, snapshot.REFRESHED_PROPERTY)
        self.assertEqual(ratings.PLAY_STARTED, snapshot.PLAY_PROPERTY)
        self.assertEqual((ratings.ITEM_AVERAGE, ratings.ITEM_SOURCE),
                         ('Property(%s)' % rating.PROPERTY, 'Property(%s)' % rating.SOURCE))

    def test_the_lists_saved_before_pov_was_patched_are_let_go_once(self):
        """Seen in the QA Kodi: the first rows after the update are built while the Wizard patches POV -- by the POV
        of before -- and saved without the average."""
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(rating.lists_once(folder, ready=lambda: False), 'POV is not patched yet')
            self.assertFalse((Path(folder) / rating.LISTS_FLAG).exists())
            self.assertTrue(rating.lists_once(folder, ready=lambda: True))
            self.assertTrue((Path(folder) / rating.LISTS_FLAG).is_file())
            self.assertFalse(rating.lists_once(folder, ready=lambda: True), 'once')
        self.assertFalse(rating.lists_once(str(Path(folder) / 'gone')), 'no POV on this device')
        self.assertIn(rating.LISTS_FLAG, snapshot.HASHED_FILES, 'a saved list depends on it')
        config = {p['id']: p for p in load('config_for_flag', PATCHES / 'patches_config.py').PATCH_CONFIG}
        self.assertEqual((config['pov_rating_movie']['target_file'], config['pov_rating_movie']['marker'][2:]), rating.PATCHED)
        source = (WIZARD / 'resources/libs/ratings.py').read_text('utf-8')
        self.assertIn("pov_rating.lists_once(xbmcvfs.translatePath('special://profile/addon_data/plugin.video.pov/'), patched)", source)


class PatchTests(unittest.TestCase):
    """POV's lists call pov_rating.stamp: each hook lands at its line and runs."""
    HOSTS = {
        'pov_rating_movie': ("def build(listitem, imdb_id, meta_get, display):\n\ttry:\n\t\t\tlistitem.setLabel(display)\n"
                             "\t\t\tlistitem.done = True\n\texcept: pass\n",
                             dict(imdb_id='tt31938062', meta_get={'rating': 6.634}.get, display='x'),
                             ('tt31938062', 'movie', 6.634)),
        'pov_rating_tvshow': ("def build(listitem, imdb_id, meta_get, display):\n\ttry:\n\t\t\tlistitem.setLabel(display)\n"
                              "\t\t\tlistitem.done = True\n\texcept: pass\n",
                              dict(imdb_id='tt0903747', meta_get={'rating': 8.9}.get, display='x'),
                              ('tt0903747', 'tvshow', 8.9)),
        'pov_rating_episode': ("def build(listitem, imdb_id, item_get, season, episode, display):\n\ttry:\n"
                               "\t\t\tlistitem.setLabel(display)\n\t\t\tlistitem.done = True\n\texcept: pass\n",
                               dict(imdb_id='tt0903747', item_get={'rating': 9.0}.get, season=5, episode=14, display='x'),
                               ('tt0903747', 'episode', 9.0, 5, 14)),
        'pov_rating_season_episode': (
            "def info_tagger(listitem, info):\n\treturn listitem\n\ndef episode_infodict(meta, **item):\n\treturn item\n\n"
            "def build(listitem, show, item, item_get, season, episode):\n\ttry:\n\t\t\tif True:\n"
            "\t\t\t\tinfotag = info_tagger(listitem, episode_infodict(show.meta, **item))\n"
            "\t\t\tlistitem.done = True\n\texcept: pass\n",
            dict(show=types.SimpleNamespace(imdb_id='tt0903747', meta={}), item={}, item_get={'rating': 9.0}.get,
                 season=5, episode=14), ('tt0903747', 'episode', 9.0, 5, 14)),
    }

    def test_each_hook_lands_at_its_line_and_calls_the_stamp(self):
        xbmc = types.SimpleNamespace(LOGDEBUG=0, LOGINFO=1, LOGWARNING=2, LOGERROR=3)
        logger = types.SimpleNamespace(log=mock.Mock())
        with mock.patch.dict(sys.modules, {'xbmc': xbmc, 'xbmcaddon': types.SimpleNamespace(), 'xbmcvfs': types.SimpleNamespace(),
                                           'resources.libs.common': types.SimpleNamespace(logging=logger)}):
            engine = load('engine_for_average', WIZARD / 'resources/libs/patch_engine.py')
            config = {p['id']: p for p in load('config_for_average', PATCHES / 'patches_config.py').PATCH_CONFIG}
            for pid, (host, arguments, expected) in self.HOSTS.items():
                patch = config[pid]
                self.assertTrue(patch['optional'], pid + ": a POV that changed the line keeps its lists")
                self.assertEqual(patch['addon_id'], 'plugin.video.pov')
                patch = dict(patch, enabled=True)
                done, changed, status = engine.PatchEngine._apply_single_patch(
                    engine.PatchEngine.__new__(engine.PatchEngine), host, patch, '\n')
                self.assertEqual((changed, status), (True, 'applied'), pid)
                calls = []
                fake = types.SimpleNamespace(stamp=lambda *args: calls.append(args[1:]))
                vfs = types.SimpleNamespace(translatePath=lambda path: path)
                listitem = types.SimpleNamespace(setLabel=lambda label: None, done=False)
                scope = {}
                with mock.patch.dict(sys.modules, {'pov_rating': fake, 'xbmcvfs': vfs}), mock.patch.object(sys, 'path', list(sys.path)):
                    exec(compile(done, pid, 'exec'), scope)
                    scope['build'](listitem=listitem, **arguments)
                self.assertEqual(calls, [expected], pid)
                self.assertTrue(listitem.done, pid + ': the list goes on after the hook')
                # a stamp that fails never costs the title its place in the list
                broken = types.SimpleNamespace(stamp=mock.Mock(side_effect=RuntimeError('boom')))
                listitem = types.SimpleNamespace(setLabel=lambda label: None, done=False)
                with mock.patch.dict(sys.modules, {'pov_rating': broken, 'xbmcvfs': vfs}), mock.patch.object(sys, 'path', list(sys.path)):
                    scope['build'](listitem=listitem, **arguments)
                self.assertTrue(listitem.done, pid)


class SkinTests(unittest.TestCase):
    def variable(self):
        root = ET.parse(XML / 'Includes_POVIL_Home.xml').getroot()
        return next(v for v in root.iter('variable') if v.get('name') == 'POVIL_ItemAverage')

    def test_a_picture_shows_its_lists_average_else_the_lists_own_rating(self):
        values = [(v.get('condition'), v.text) for v in self.variable().findall('value')]
        self.assertEqual(values, [
            ('!String.IsEmpty(ListItem.Property(povil_avg))', '$INFO[ListItem.Property(povil_avg)]'),
            # a build without the Wizard, a title its patches did not reach
            (None, '$INFO[ListItem.Rating]')])
        self.assertEqual(rating.PROPERTY, 'povil_avg')

    def test_a_title_with_no_rating_of_its_own_still_gets_its_corner(self):
        """The new film: nothing in ListItem.Rating, an average from Trakt's figure."""
        root = ET.parse(XML / 'Includes_POVIL_Home.xml').getroot()
        badges = [c for c in root.iter('control') if c.get('description') == 'rating on the picture']
        self.assertTrue(badges)
        for badge in badges:
            self.assertTrue(badge.findtext('visible').startswith(
                '[Integer.IsGreater(ListItem.Rating,0) | !String.IsEmpty(ListItem.Property(povil_avg))] + '))

    def test_the_row_of_sites_ends_with_their_average(self):
        for name, prefix, key in (('Home.xml', 'povil.rt.', 9807), ('View_POVIL.xml', 'povil.rt.', 9807),
                                  ('DialogVideoInfo.xml', 'povil.rt.', 9807), ('VideoOSD.xml', 'povil.rtp.', 7920)):
            root = ET.parse(XML / name).getroot()
            for row in (c for c in root.iter('control') if c.get('type') == 'grouplist' and c.get('description') == 'ratings'):
                unit = row.findall('control')[0]
                self.assertEqual(unit.get('description'), 'average', name)
                labels = [c.findtext('label') for c in unit.findall('control') if c.get('type') == 'label']
                self.assertEqual(labels, ['ממוצע', '$INFO[Window(home).Property(%savg)]' % prefix], name)
                self.assertEqual(unit.findtext('visible'),
                                 'String.IsEqual(Control.GetLabel(%d),Window(home).Property(%sfor)) + '
                                 '!String.IsEmpty(Window(home).Property(%savg))' % (key, prefix, prefix), name)
                # it fits beside the sites: the row is wide enough for all of them and the average
                widths = [int(c.findtext('width')) for c in row.findall('control')]
                gap = int(row.findtext('itemgap'))
                self.assertLessEqual(sum(widths) + gap * (len(widths) - 1), int(row.findtext('width')), name)


if __name__ == '__main__':
    unittest.main()
