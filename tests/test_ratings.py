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


class WiringTests(unittest.TestCase):
    def test_the_wizards_service_runs_the_watch_as_a_thread_and_nothing_polls(self):
        startup = (WIZARD / 'startup.py').read_text('utf-8')
        self.assertIn("_start_watch('POVILRatings', _ratings_watch)", startup)
        source = (WIZARD / 'resources/libs/ratings.py').read_text('utf-8')
        watch = source[source.index('def watch():'):]
        self.assertIn('def onNotification(self, sender, method, data):', watch)
        self.assertIn('wake.wait()', watch)
        self.assertNotIn('getInfoLabel', source, 'the skin names the title; nothing here reads the screen in a loop')
        self.assertIn("xbmcaddon.Addon('plugin.video.pov').getSetting('trakt.client_id')", source)
        self.assertNotRegex(source, r"['\"][0-9a-f]{40,}['\"]", 'no key is written here: POV carries its own')


if __name__ == '__main__':
    unittest.main()
