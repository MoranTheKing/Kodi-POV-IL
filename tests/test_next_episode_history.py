"""Next-episode reads stay fresh, scoped, complete and equivalent to native SQL."""
from contextlib import closing
import importlib.util
from pathlib import Path
import random
import sqlite3
import tempfile
import threading
from types import MappingProxyType
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCHES = ROOT / 'plugin.program.kodipovilwizard/resources/libs/patches'


def load(name):
    spec = importlib.util.spec_from_file_location('next_tests_' + name, PATCHES / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


next_history = load('pov_next_history')
history = load('pov_watch_history')


class NextHistoryQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'watched.db'
        self.connections = []
        self.dropped = set()
        self.indicators = []
        self.make_schema()

    def make_schema(self, suffix='UNIQUE(db_type,media_id,season,episode)', extra=''):
        with closing(sqlite3.connect(self.path)) as c:
            c.execute('DROP TABLE IF EXISTS watched_status')
            c.execute('CREATE TABLE watched_status(db_type TEXT, media_id TEXT, season INTEGER, '
                      'episode INTEGER, last_played TEXT, title TEXT' + extra + ', ' + suffix + ')')

    def connect(self, indicator):
        self.indicators.append(indicator)
        c = sqlite3.connect(self.path)
        self.connections.append(c)
        return c

    def native(self):
        return dict(get_dropped_info_tv=lambda indicator: self.dropped.copy(),
                    _database_connect=self.connect, set_PRAGMAS=lambda c: c.cursor())

    def insert(self, rows):
        with closing(sqlite3.connect(self.path)) as c:
            c.executemany('INSERT OR REPLACE INTO watched_status VALUES (?,?,?,?,?,?)', rows)
            c.commit()

    def expected(self):
        with closing(sqlite3.connect(self.path)) as c:
            rows = c.execute(next_history.WINDOW_QUERY, ('episode',)).fetchall()
        return [{'media_ids': {'tmdb': r[0]}, 'last_played': r[2], 'season': r[3], 'episode': r[4]}
                for r in rows if int(r[0]) not in self.dropped]

    def test_random_history_matches_all_native_rows_and_order(self):
        rng = random.Random(702)
        rows = [('episode', str(show), season, episode, str(rng.random()), 'Title')
                for show in range(1, 80) for season in range(1, 5) for episode in range(1, 9)]
        rows += [('movie', '1', 99, 99, '2099', 'Movie')]
        rng.shuffle(rows)
        self.insert(rows)
        self.dropped = {2, 8, 40}
        expected = self.expected()
        for indicator in (0, 1, 2):
            self.assertEqual(next_history.next_episodes(self.native(), indicator), expected)
        self.assertEqual(self.indicators, [0, 1, 2])
        for c in self.connections:
            with self.assertRaises(sqlite3.ProgrammingError): c.execute('SELECT 1')

    def test_latest_play_time_does_not_replace_highest_native_episode(self):
        self.insert([('episode','9',2,3,'2000','Show'), ('episode','9',1,10,'2099','Show'),
                     ('episode','9',2,2,'2100','Show')])
        self.assertEqual(next_history.next_episodes(self.native(), 0), self.expected())
        self.assertEqual(self.expected()[0]['episode'], 3)

    def test_watch_unwatch_and_dropped_updates_are_immediate(self):
        self.insert([('episode','9',1,1,'a','Show')])
        self.assertEqual(next_history.next_episodes(self.native(), 0)[0]['episode'], 1)
        self.insert([('episode','9',1,2,'b','Show')])
        self.assertEqual(next_history.next_episodes(self.native(), 0)[0]['episode'], 2)
        with closing(sqlite3.connect(self.path)) as c:
            c.execute("DELETE FROM watched_status WHERE episode=2")
            c.commit()
        self.assertEqual(next_history.next_episodes(self.native(), 0)[0]['episode'], 1)
        self.dropped.add(9)
        self.assertEqual(next_history.next_episodes(self.native(), 0), [])
        self.dropped.clear()
        self.assertEqual(next_history.next_episodes(self.native(), 0)[0]['episode'], 1)

    def test_empty_history_is_not_persisted(self):
        self.assertEqual(next_history.next_episodes(self.native(), 0), [])
        self.insert([('episode','9',1,1,'a','Show')])
        self.assertEqual(next_history.next_episodes(self.native(), 0), self.expected())

    def test_legacy_schema_without_suitable_index_keeps_window_query(self):
        self.make_schema('UNIQUE(title, last_played)')
        self.insert([('episode','9',1,1,'a','Show'), ('episode','9',2,2,'b','Show')])
        with closing(sqlite3.connect(self.path)) as c:
            self.assertFalse(next_history._has_seek_index(c.cursor()))
        self.assertEqual(next_history.next_episodes(self.native(), 0), self.expected())

    def test_without_rowid_schema_falls_back_without_data_loss(self):
        with closing(sqlite3.connect(self.path)) as c:
            c.execute('DROP TABLE watched_status')
            c.execute('CREATE TABLE watched_status(db_type TEXT, media_id TEXT, season INTEGER, '
                      'episode INTEGER, last_played TEXT, title TEXT, '
                      'PRIMARY KEY(db_type,media_id,season,episode)) WITHOUT ROWID')
        self.insert([('episode','9',1,1,'a','Show'), ('episode','9',2,2,'b','Show')])
        self.assertEqual(next_history.next_episodes(self.native(), 0), self.expected())

    def test_null_episode_legacy_rows_retain_native_tie_choice(self):
        self.insert([('episode','9',None,None,'a','Show'), ('episode','9',None,None,'b','Show'),
                     ('episode','10',1,None,'c','Show'), ('episode','10',1,None,'d','Show'),
                     ('episode','11',None,7,'e','Show'), ('episode','11',2,1,'f','Show')])
        self.assertEqual(next_history.next_episodes(self.native(), 0), self.expected())

    def test_custom_descending_index_retains_native_query(self):
        self.make_schema('UNIQUE(db_type,media_id,season DESC,episode DESC)')
        self.insert([('episode','9',None,None,'a','Show'), ('episode','9',None,None,'b','Show')])
        with closing(sqlite3.connect(self.path)) as c:
            self.assertFalse(next_history._has_seek_index(c.cursor()))
        self.assertEqual(next_history.next_episodes(self.native(), 0), self.expected())

    def test_shadow_rowid_retains_native_query(self):
        self.make_schema(extra=', rowid INTEGER')
        with closing(sqlite3.connect(self.path)) as c:
            c.execute('INSERT INTO watched_status VALUES (?,?,?,?,?,?,?)',
                      ('episode','9',1,1,'a','Show',99))
            c.commit()
            self.assertFalse(next_history._has_seek_index(c.cursor()))
        self.assertEqual(next_history.next_episodes(self.native(), 0), self.expected())

    def test_read_does_not_change_history_or_schema(self):
        self.insert([('episode','9',1,1,'a','Show')])
        with closing(sqlite3.connect(self.path)) as c:
            schema = c.execute('SELECT type,name,sql FROM sqlite_master ORDER BY name').fetchall()
            rows = c.execute('SELECT * FROM watched_status').fetchall()
        next_history.next_episodes(self.native(), 0)
        with closing(sqlite3.connect(self.path)) as c:
            self.assertEqual(c.execute('SELECT type,name,sql FROM sqlite_master ORDER BY name').fetchall(), schema)
            self.assertEqual(c.execute('SELECT * FROM watched_status').fetchall(), rows)

    def test_native_error_is_propagated_and_connection_is_closed(self):
        self.insert([('episode','not-a-number',1,1,'a','Show')])
        with self.assertRaises(ValueError): next_history.next_episodes(self.native(), 0)
        with self.assertRaises(sqlite3.ProgrammingError): self.connections[-1].execute('SELECT 1')

    def test_existing_index_is_used_for_per_show_lookup(self):
        with closing(sqlite3.connect(self.path)) as c:
            self.assertTrue(next_history._has_seek_index(c.cursor()))
            plans = [r[3] for r in c.execute('EXPLAIN QUERY PLAN ' + next_history.SEEK_QUERY,
                                            ('episode','episode')).fetchall()]
        self.assertTrue(any('SEARCH history USING' in r for r in plans), plans)


class ConstructorHistoryScopeTests(unittest.TestCase):
    def setUp(self):
        self.calls = 0
        class Cursor:
            def execute(inner, *args): return inner
            def fetchall(inner): return [('9','Show','now',1,1)]
        class Connection:
            def close(inner): pass
        def connect(indicator):
            self.calls += 1
            return Connection()
        self.native = dict(MappingProxyType=MappingProxyType,
                           GET_MOVIE_SHOW='SELECT %s FROM watched_status',
                           _database_connect=connect, set_PRAGMAS=lambda c: Cursor())
        def reader(indicator): return history.tv_history(self.native, indicator)
        self.reader = reader

    def construct(self, mode='build_next_episode', reader=None):
        reader = reader or self.reader
        class Native:
            def __init__(self, params): self.watched_info = reader(0)
        instance = Native.__new__(Native)
        history.next_constructor(instance, Native.__init__.__get__(instance), {'mode':mode}, reader)
        return instance.watched_info

    def test_only_explicit_next_constructor_skips_unused_read(self):
        result = self.construct()
        self.assertIsInstance(result, MappingProxyType)
        self.assertEqual(dict(result), {})
        self.assertEqual(self.calls, 0)
        result = self.reader(0)
        self.assertEqual(result['9'], (('9','Show','now',1,1),))
        self.assertEqual(self.calls, 1)

    def test_other_episode_and_calendar_routes_keep_complete_history(self):
        for mode in ('build_in_progress_episode', 'build_episode_list', 'build_my_calendar_trakt'):
            self.assertIn('9', self.construct(mode))
        self.assertEqual(self.calls, 3)

    def test_scope_does_not_escape_to_another_thread_or_reader(self):
        results = []
        def reader(indicator):
            thread = threading.Thread(target=lambda: results.append(self.reader(0)))
            thread.start(); thread.join()
            return self.reader(0)
        self.construct(reader=reader)
        self.assertIn('9', results[0])
        self.assertEqual(self.calls, 2)
        self.assertIsNone(history._next_history.get())

    def test_a_ticket_can_only_skip_one_read(self):
        reader = self.reader
        class Native:
            def __init__(self, params): self.rows = (reader(0), reader(0))
        instance = Native.__new__(Native)
        history.next_constructor(instance, Native.__init__.__get__(instance),
                                 {'mode':'build_next_episode'}, reader)
        self.assertEqual(dict(instance.rows[0]), {})
        self.assertIn('9', instance.rows[1])
        self.assertEqual(self.calls, 1)

    def test_overridden_reader_and_failed_constructor_do_not_leak_scope(self):
        def broken(indicator): raise RuntimeError('overridden reader')
        with self.assertRaises(RuntimeError): self.construct(reader=broken)
        self.assertIsNone(history._next_history.get())
        self.assertIn('9', self.reader(0))


if __name__ == '__main__': unittest.main()
