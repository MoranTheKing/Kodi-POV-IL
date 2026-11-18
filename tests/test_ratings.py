"""Ratings from several sites for the title Onyx shows (Wizard 0.5.5: resources/libs/ratings.py).

The data is Trakt's ratings call (no account, the application key POV carries); the skin asks by a home-window
property and an announcement, and one thread of the Wizard's service answers.
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'plugin.program.kodipovilwizard'
spec = importlib.util.spec_from_file_location('ratings_under_test', WIZARD / 'resources/libs/ratings.py')
ratings = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ratings)

# what Trakt answered for a film on 17 Nov 2026 (shortened)
FILM = {'trakt': {'rating': 8.75865, 'votes': 71298}, 'tmdb': {'rating': 8.4, 'votes': 40754},
        'imdb': {'rating': 8.8, 'votes': 2764656}, 'metascore': {'rating': 74},
        'rotten_tomatoes': {'rating': 87, 'state': 'fresh', 'user_rating': 91, 'user_state': 'upright'},
        'mal': {'rating': None, 'votes': 0}, 'letterboxd': {'rating': 4.22, 'votes': 3483312}}
EPISODE = {'trakt': {'rating': 8.49348, 'votes': 5163}, 'tmdb': {'rating': 9, 'votes': 269},
           'imdb': {'rating': 9.6, 'votes': 75773}, 'metascore': {'rating': None},
           'rotten_tomatoes': {'rating': None, 'state': None, 'user_rating': None, 'user_state': None}}


class Home(object):
    def __init__(self, **properties):
        self.properties = dict(properties)
        self.writes = []

    def getProperty(self, key):
        return self.properties.get(key, '')

    def setProperty(self, key, value):
        self.properties[key] = value
        self.writes.append(key)


class KeyTests(unittest.TestCase):
    def test_a_key_names_the_call_and_the_file_it_is_kept_in(self):
        self.assertEqual(ratings.parse('tt1375666|movie||'), ('movie-tt1375666', '/movies/tt1375666/ratings'))
        self.assertEqual(ratings.parse('tt0944947|tvshow|-1|'), ('show-tt0944947', '/shows/tt0944947/ratings'))
        self.assertEqual(ratings.parse('tt0944947|season|1|'), ('show-tt0944947', '/shows/tt0944947/ratings'),
                         'a season is shown its show\'s ratings')
        self.assertEqual(ratings.parse('tt0944947|episode|1|9'),
                         ('episode-tt0944947-1-9', '/shows/tt0944947/seasons/1/episodes/9/ratings'))

    def test_anything_else_is_not_asked(self):
        for key in ('', '|movie||', 'abc|movie||', 'tt12x|movie||', 'tt1375666|set||', 'tt1375666|episode||9',
                    'tt1375666|episode|1|x', 'tt1375666/../x|movie||', 'tt' + '9' * 20 + '|movie||', None):
            self.assertIsNone(ratings.parse(key), key)


class ShapeTests(unittest.TestCase):
    def test_a_film_gets_every_site(self):
        self.assertEqual(ratings.shape(FILM), {
            'tmdb': '8.4', 'imdb': '8.8', 'imdb_votes': '2.8M', 'trakt': '88%', 'tomato': '87%', 'tomato_state': 'fresh',
            'popcorn': '91%', 'popcorn_state': 'upright', 'meta': '74', 'meta_tone': 'good', 'letterboxd': '4.2'})

    def test_an_episode_gets_the_three_sites_that_rate_episodes(self):
        self.assertEqual(ratings.shape(EPISODE), {'tmdb': '9.0', 'imdb': '9.6', 'imdb_votes': '76K', 'trakt': '85%'})

    def test_verdicts(self):
        def one(**tomato):
            return ratings.shape({'rotten_tomatoes': tomato})
        self.assertEqual(one(rating=98, state='certified_fresh')['tomato_state'], 'certified')
        self.assertEqual(one(rating=31, state='rotten')['tomato_state'], 'rotten')
        self.assertEqual(one(rating=31)['tomato_state'], 'rotten', 'no verdict named: under 60 is rotten')
        self.assertEqual(one(rating=75)['tomato_state'], 'fresh')
        self.assertEqual(one(user_rating=40, user_state='spilled')['popcorn_state'], 'spilled')
        self.assertEqual(one(user_rating=40)['popcorn_state'], 'spilled')
        for score, tone in ((61, 'good'), (60, 'mixed'), (40, 'mixed'), (39, 'bad')):
            self.assertEqual(ratings.shape({'metascore': {'rating': score}})['meta_tone'], tone)

    def test_nothing_is_invented(self):
        self.assertEqual(ratings.shape({}), {})
        self.assertEqual(ratings.shape(None), {})
        self.assertEqual(ratings.shape({'imdb': {'rating': 0, 'votes': 0}, 'tmdb': {'rating': None}, 'trakt': {'rating': 7.0, 'votes': 0},
                                        'metascore': 'x', 'letterboxd': {'rating': 'n/a'}}), {})
        self.assertEqual([ratings.votes(n) for n in (812, 75773, 999499, 1000000, 2764656, None, 0)],
                         ['812', '76K', '999K', '1M', '2.8M', '', ''])


class StoreTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name) / 'ratings'
        self.now = [1000000.0]
        self.calls = []
        self.reply = (200, FILM)
        self.store = self.new()

    def new(self):
        def fetch(path):
            self.calls.append(path)
            return self.reply
        return ratings.Store(str(self.folder), fetch, clock=lambda: self.now[0])

    def test_a_title_is_asked_once_and_kept_for_three_days(self):
        self.assertEqual(self.store.lookup('tt1375666|movie||')['imdb'], '8.8')
        self.assertEqual(self.store.lookup('tt1375666|movie||')['imdb'], '8.8')
        self.assertEqual(self.calls, ['/movies/tt1375666/ratings'])
        self.assertEqual(self.new().lookup('tt1375666|movie||')['imdb'], '8.8', 'the next Kodi session reads the file')
        self.assertEqual(len(self.calls), 1)
        self.now[0] += ratings.KEEP + 1
        self.reply = (200, dict(FILM, imdb={'rating': 8.7, 'votes': 2800000}))
        self.assertEqual(self.store.lookup('tt1375666|movie||')['imdb'], '8.7')
        self.assertEqual(len(self.calls), 2)

    def test_a_season_and_its_show_share_one_answer(self):
        self.store.lookup('tt0944947|tvshow||')
        self.store.lookup('tt0944947|season|3|')
        self.assertEqual(self.calls, ['/shows/tt0944947/ratings'])

    def test_a_title_with_no_answer_is_asked_again_after_an_hour_not_before(self):
        self.reply = (404, None)
        self.assertEqual(self.store.lookup('tt0000001|movie||'), {})
        self.assertEqual(self.store.lookup('tt0000001|movie||'), {})
        self.assertEqual(len(self.calls), 1)
        self.now[0] += ratings.RETRY + 1
        self.reply = (200, FILM)
        self.assertEqual(self.store.lookup('tt0000001|movie||')['imdb'], '8.8')

    def test_a_failed_request_does_not_wipe_what_was_known(self):
        self.store.lookup('tt1375666|movie||')
        self.now[0] += ratings.KEEP + 1
        self.reply = (0, None)
        self.assertEqual(self.store.lookup('tt1375666|movie||')['imdb'], '8.8')
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.store.lookup('tt1375666|movie||')['imdb'], '8.8')
        self.assertEqual(len(self.calls), 2, 'not asked again at once')
        self.now[0] += ratings.RETRY + 1
        self.store.lookup('tt1375666|movie||')
        self.assertEqual(len(self.calls), 3)

    def test_too_many_requests_stops_the_asking_for_five_minutes(self):
        self.reply = (429, None)
        self.assertEqual(self.store.lookup('tt1375666|movie||'), {})
        self.assertEqual(self.store.lookup('tt0944947|tvshow||'), {})
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(list(self.folder.glob('*.json')) if self.folder.exists() else [], [], 'nothing was learned')
        self.now[0] += ratings.BACK_OFF + 1
        self.reply = (200, FILM)
        self.assertEqual(self.store.lookup('tt1375666|movie||')['imdb'], '8.8')

    def test_a_refused_key_stops_the_asking_for_an_hour(self):
        for status, film in ((401, 'tt0000401|movie||'), (403, 'tt0000403|movie||')):
            self.calls, self.store = [], self.new()
            self.reply = (status, None)
            self.assertEqual(self.store.lookup(film), {})
            self.now[0] += ratings.BACK_OFF + 1
            self.assertEqual(self.store.lookup('tt0944947|tvshow||'), {})
            self.assertEqual(len(self.calls), 1, status)
            self.now[0] += ratings.REFUSED
            self.reply = (200, FILM)
            self.assertEqual(self.store.lookup(film)['imdb'], '8.8')

    def test_a_key_that_names_nothing_reaches_neither_the_network_nor_the_disk(self):
        self.assertEqual(self.store.lookup('../../x|movie||'), {})
        self.assertEqual(self.calls, [])
        self.assertFalse(self.folder.exists())

    def test_old_files_go(self):
        self.store.lookup('tt1375666|movie||')
        self.now[0] += ratings.PRUNE + 2 * 24 * 3600
        import os
        old = self.now[0] - ratings.PRUNE - 10
        os.utime(self.folder / 'movie-tt1375666.json', (old, old))
        self.store.lookup('tt0944947|tvshow||')
        self.assertEqual(sorted(p.name for p in self.folder.glob('*.json')), ['show-tt0944947.json'])
        kept = json.loads((self.folder / 'show-tt0944947.json').read_text('utf-8'))
        self.assertEqual(sorted(kept), ['at', 'ok', 'ratings'])


class AnswerTests(unittest.TestCase):
    def store(self, moved=None):
        test = self

        class Fake(object):
            def lookup(self, key):
                if moved:
                    moved()
                return ratings.shape(FILM)
        return Fake()

    def test_the_fields_are_written_and_the_title_they_belong_to_last(self):
        home = Home(**{'povil.rt.ask': 'tt1375666|movie||'})
        self.assertTrue(ratings.answer(home, self.store(), 'home'))
        self.assertEqual(home.properties['povil.rt.imdb'], '8.8')
        self.assertEqual(home.properties['povil.rt.for'], 'tt1375666|movie||')
        self.assertEqual(home.writes[-1], 'povil.rt.for', 'the skin pairs a field with a title only by this')
        self.assertEqual(sorted(home.writes[:-1]), sorted('povil.rt.' + f for f in ratings.FIELDS))

    def test_a_field_the_title_lacks_is_emptied(self):
        home = Home(**{'povil.rt.ask': 'tt1|episode|1|1', 'povil.rt.tomato': '87%', 'povil.rt.for': 'tt1375666|movie||'})

        class Episode(object):
            def lookup(self, key):
                return ratings.shape(EPISODE)
        ratings.answer(home, Episode(), 'home')
        self.assertEqual(home.properties['povil.rt.tomato'], '')
        self.assertEqual(home.properties['povil.rt.imdb'], '9.6')

    def test_nothing_is_written_when_the_skin_moved_on_or_was_answered(self):
        home = Home(**{'povil.rt.ask': 'tt1375666|movie||'})
        self.assertFalse(ratings.answer(home, self.store(moved=lambda: home.properties.update({'povil.rt.ask': 'tt2|movie||'})), 'home'))
        self.assertEqual(home.writes, [])
        home = Home(**{'povil.rt.ask': 'tt1375666|movie||', 'povil.rt.for': 'tt1375666|movie||'})
        self.assertFalse(ratings.answer(home, self.store(), 'home'))
        self.assertFalse(ratings.answer(Home(), self.store(), 'home'), 'nothing asked')

    def test_the_player_has_its_own_question_and_answer(self):
        home = Home(**{'povil.rtp.ask': 'tt1375666|movie||', 'povil.rt.ask': 'tt9|movie||'})
        ratings.answer(home, self.store(), 'player')
        self.assertEqual(home.properties['povil.rtp.for'], 'tt1375666|movie||')
        self.assertNotIn('povil.rt.for', home.properties)


class DeskTests(unittest.TestCase):
    """The owner, Nov 2026: TMDb's number was there at once and the others two seconds later --
    "all of them at once, instantly"."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.asked = []
        self.now = [1_700_000_000.0]

        def fetch(path):
            self.asked.append(path)
            return 200, FILM
        self.store = ratings.Store(folder.name, fetch, clock=lambda: self.now[0])

    def test_a_known_title_is_answered_where_the_question_arrives_with_no_request(self):
        self.store.lookup('tt1375666|movie||')
        self.asked.clear()
        home = Home(**{'povil.rt.ask': 'tt1375666|movie||'})
        desk = ratings.Desk(home, self.store)
        self.assertTrue(desk.asked('home'))
        self.assertEqual(home.properties['povil.rt.imdb'], '8.8')
        self.assertEqual(home.properties['povil.rt.for'], 'tt1375666|movie||')
        self.assertEqual((self.asked, desk.jobs), ([], []), 'no request and no job')
        # a new store (Kodi started again) finds it in the title's file
        again = ratings.Store(self.store.folder, lambda path: self.fail('asked again'), clock=lambda: self.now[0])
        home = Home(**{'povil.rt.ask': 'tt1375666|movie||'})
        self.assertTrue(ratings.Desk(home, again).asked('home'))

    def test_a_title_not_known_is_asked_by_a_worker_and_answered_if_still_on_screen(self):
        home = Home(**{'povil.rt.ask': 'tt1375666|movie||'})
        desk = ratings.Desk(home, self.store)
        self.assertFalse(desk.asked('home'))
        self.assertEqual(home.writes, [])
        self.assertTrue(desk.step())
        self.assertEqual(self.asked, ['/movies/tt1375666/ratings'])
        self.assertEqual(home.properties['povil.rt.for'], 'tt1375666|movie||')
        self.assertFalse(desk.step(), 'nothing left')
        # the skin moved on while Trakt was asked: kept for later, not written
        home = Home(**{'povil.rt.ask': 'tt2|movie||'})
        desk = ratings.Desk(home, self.store)
        desk.asked('home')
        home.properties['povil.rt.ask'] = 'tt3|movie||'
        desk.step()
        self.assertEqual(home.writes, [])
        self.assertEqual(self.store.known('tt2|movie||')[1], True)

    def test_the_newest_question_is_asked_first(self):
        home = Home()
        desk = ratings.Desk(home, self.store)
        for imdb in ('tt1', 'tt2', 'tt3'):
            home.properties['povil.rt.ask'] = imdb + '|movie||'
            desk.asked('home')
        desk.step()
        self.assertEqual(self.asked, ['/movies/tt3/ratings'], 'where the viewer stopped, not where the scroll began')
        self.assertEqual(home.properties['povil.rt.for'], 'tt3|movie||')

    def test_what_is_known_but_old_is_shown_at_once_and_asked_again_behind_it(self):
        self.store.lookup('tt1375666|movie||')
        self.asked.clear()
        self.now[0] += ratings.KEEP + 60
        home = Home(**{'povil.rt.ask': 'tt1375666|movie||'})
        desk = ratings.Desk(home, self.store)
        self.assertTrue(desk.asked('home'), 'shown from the file')
        self.assertEqual(len(desk.jobs), 1)
        desk.step()
        self.assertEqual(self.asked, ['/movies/tt1375666/ratings'])

    def test_the_titles_beside_the_focused_one_are_asked_ahead_nearest_first(self):
        row = {0: 'tt100', 1: 'tt101', 2: 'tt102', 3: 'tt103', -1: 'tt099', 4: '', 5: 'tt105'}

        def read(label):
            if label == 'System.CurrentControlID':
                return '5010'
            item, _dot, field = label.rpartition('.')
            offset = int(item[item.index('ListItemNoWrap(') + 15:-1])
            self.assertTrue(item.startswith('Container(5010).'))
            if field == 'UniqueID(imdb)':
                return row.get(offset, '')
            return 'movie' if field == 'DBType' else ''
        self.assertEqual(ratings.neighbours(read)[:4], ['tt101|movie||', 'tt099|movie||', 'tt102|movie||', 'tt103|movie||'])
        self.assertEqual(ratings.neighbours(lambda label: ''), [], 'the focus is not on a list')
        self.store.lookup('tt101|movie||')          # one of them is known already
        self.asked.clear()
        home = Home(**{'povil.rt.ask': 'tt100|movie||'})
        desk = ratings.Desk(home, self.store, read)
        desk.asked('home')
        while desk.step():
            pass
        self.assertEqual(self.asked[0], '/movies/tt100/ratings', 'the title on screen before any asked ahead')
        self.assertEqual(self.asked[1], '/movies/tt099/ratings', 'then the nearest one not known')
        self.assertEqual(sorted(self.asked[1:]), sorted('/movies/%s/ratings' % i for i in ('tt099', 'tt102', 'tt103', 'tt105')))
        # the focus moves on to one of them: answered at once
        home.properties['povil.rt.ask'] = 'tt102|movie||'
        self.asked.clear()
        self.assertTrue(desk.asked('home'))
        self.assertEqual(home.properties['povil.rt.for'], 'tt102|movie||')
        # the player's slot asks nothing ahead
        player = ratings.Desk(Home(**{'povil.rtp.ask': 'tt100|movie||'}), self.store, read)
        player.asked('player')
        self.assertEqual(player.jobs, [])

    def test_the_other_rows_on_the_screen_are_asked_ahead_too(self):
        # the owner: "on a phone one can go to a title that is not a neighbour"
        rows = {5021: ['tt200', 'tt201', 'tt202'], 5022: ['tt300', 'tt301'], 5023: [], 5031: ['tt900']}
        focus = {'control': '5021', 'at': 0}
        reads = []

        def read(label):
            reads.append(label)
            if label == 'System.CurrentControlID':
                return focus['control']
            container = int(label[label.index('(') + 1:label.index(')')])
            if label.endswith('.NumItems'):
                return str(len(rows.get(container, [])))
            offset = int(label[label.index('ListItemNoWrap(') + 15:label.index(').', label.index('ListItemNoWrap('))])
            field = label.rpartition('.')[2]
            index = offset + (focus['at'] if container == int(focus['control']) else 0)
            titles = rows.get(container, [])
            if field == 'UniqueID(imdb)':
                return titles[index] if 0 <= index < len(titles) else ''
            return 'movie' if field == 'DBType' else ''
        keys = ratings.neighbours(read, rows=True)
        self.assertEqual(keys, ['tt201|movie||', 'tt202|movie||', 'tt300|movie||', 'tt301|movie||'],
                         'its own row first, then the other rows of the same tab -- not another tab\'s')
        self.assertEqual(ratings.neighbours(read), ['tt201|movie||', 'tt202|movie||'], 'only when asked to')
        home = Home(**{'povil.rt.ask': 'tt200|movie||'})
        desk = ratings.Desk(home, self.store, read)
        desk.asked('home')
        while desk.step():
            pass
        self.assertEqual(sorted(self.asked), sorted('/movies/%s/ratings' % t for t in ('tt200', 'tt201', 'tt202', 'tt300', 'tt301')))
        # the focus stays in the row: the other rows are not read again at every press
        del reads[:]
        focus['at'] = 1
        home.properties['povil.rt.ask'] = 'tt201|movie||'
        self.assertTrue(desk.asked('home'), 'known: answered at once')
        while desk.step():
            pass
        self.assertFalse([r for r in reads if r.startswith('Container(5022)')])
        # ... but they are after a while, and when the focus comes to another row
        self.now[0] += ratings.ROWS_EVERY + 1
        desk.asked('home')
        while desk.step():
            pass
        self.assertTrue([r for r in reads if r.startswith('Container(5022)')])
        # a tap on a title of another row: it was asked ahead
        focus['control'], focus['at'] = '5022', 1
        home.properties['povil.rt.ask'] = 'tt301|movie||'
        self.assertTrue(desk.asked('home'))
        self.assertEqual(home.properties['povil.rt.for'], 'tt301|movie||')

    def test_titles_asked_ahead_go_one_at_a_time_and_one_look_at_the_screen_is_enough(self):
        # review, Nov 2026: a tab seen for the first time is some ninety titles; Trakt answers a burst with
        # "too many requests", and then even the focused title waits five minutes
        home = Home()
        desk = ratings.Desk(home, self.store, lambda label: '')
        for n in range(5):
            desk._put(desk.AHEAD, 'tt%d|movie||' % (n + 1), None)
        self.assertFalse(desk.step(urgent_only=True), 'a worker for the title on screen leaves them alone')
        self.assertEqual(len(desk.jobs), 5)
        home.properties['povil.rt.ask'] = 'tt9|movie||'
        desk.asked('home')
        self.assertTrue(desk.step(urgent_only=True))        # the look at the screen
        self.assertTrue(desk.step(urgent_only=True))        # the title on screen
        self.assertEqual(self.asked, ['/movies/tt9/ratings'])
        self.assertFalse(desk.step(urgent_only=True))
        # every question asks for a look at the screen; an older look still waiting is dropped
        for imdb in ('tt11', 'tt12', 'tt13'):
            home.properties['povil.rt.ask'] = imdb + '|movie||'
            desk.asked('home')
        self.assertEqual(len([job for job in desk.jobs if job[2] is None]), 1)

    def test_a_long_scroll_does_not_pile_up_and_a_title_is_never_asked_twice_at_once(self):
        home = Home()
        desk = ratings.Desk(home, self.store)
        for n in range(ratings.QUEUE * 2):
            desk._put(desk.AHEAD, 'tt%d|movie||' % (n + 1), None)
        self.assertEqual(len(desk.jobs), ratings.QUEUE)
        self.assertEqual(desk.jobs[0][2], 'tt%d|movie||' % (ratings.QUEUE * 2), 'the newest stay')
        desk.jobs[:] = []
        desk.busy.add('tt7|movie||')
        desk._put(desk.URGENT, 'tt7|movie||', 'home')
        self.assertTrue(desk.step())
        self.assertEqual(self.asked, [], 'the worker already asking it answers when it is done')
        desk.close()
        self.assertFalse(desk.step(wait=5), 'a closing desk hands out nothing and does not wait')

    def test_two_answers_never_mix_and_the_line_to_trakt_is_kept_open(self):
        home = Home(**{'povil.rt.ask': 'tt2|movie||'})
        self.assertFalse(ratings.publish(home, 'povil.rt.', 'tt1|movie||', ratings.shape(FILM)))
        self.assertEqual(home.writes, [])
        self.assertTrue(ratings.publish(home, 'povil.rt.', 'tt2|movie||', {}))
        self.assertEqual(home.writes[-1], 'povil.rt.for')
        source = (WIZARD / 'resources/libs/ratings.py').read_text('utf-8')
        fetch = source[source.index('def trakt_fetch(path):'):source.index('_WRITING = ')]
        self.assertIn('http.client.HTTPSConnection(HOST, timeout=TIMEOUT)', fetch)
        self.assertIn('_LINES.line = None', fetch, 'a line closed at the far end is opened again, once')
        self.assertNotIn('urlopen', source)


class WiringTests(unittest.TestCase):
    def test_the_wizards_service_runs_the_watch_as_a_thread_and_nothing_polls(self):
        startup = (WIZARD / 'startup.py').read_text('utf-8')
        self.assertIn("_start_watch('POVILRatings', _ratings_watch)", startup)
        source = (WIZARD / 'resources/libs/ratings.py').read_text('utf-8')
        watch = source[source.index('def watch():'):]
        self.assertIn('def onNotification(self, sender, method, data):', watch)
        self.assertIn('desk.asked(slot)', watch, 'answered where the question arrives')
        self.assertIn('desk.step(wait=60, urgent_only=urgent_only)', watch, 'the workers sleep until there is a job: nothing polls')
        self.assertNotIn('sleep(', source)
        # the screen is read only when the skin asked: for the titles beside the focused one
        self.assertEqual(source.count('getInfoLabel'), 1)
        self.assertIn("xbmcaddon.Addon('plugin.video.pov').getSetting('trakt.client_id')", source)
        self.assertNotRegex(source, r"['\"][0-9a-f]{40,}['\"]", 'no key is written here: POV carries its own')


if __name__ == '__main__':
    unittest.main()
