"""Execute modern Umbrella sync against failures, pagination and racing activity.

UMBRELLA_STOCK points at an unmodified current host. Without it, execute the
verbatim 6.7.87 function fixtures; print which coverage was used.
"""
import ast
from contextlib import closing
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PATCHER = ROOT / 'addons/service.subtitles.kodipovilai/resources/lib/umbrella_mdblist_sync_patcher.py'
FIXTURE = HERE / 'fixtures/umbrella_sync_6_7_87.py'
STOCK = Path(os.environ.get('UMBRELLA_STOCK', '/nonexistent')) / 'resources/lib/modules/mdblist.py'
SOURCE = STOCK.read_text(encoding='utf-8') if STOCK.is_file() else FIXTURE.read_text(encoding='utf-8')
print('modern sync fixture:', str(STOCK) if STOCK.is_file() else 'verbatim 6.7.87 functions (no stock tree)')
sys.path.insert(0, str(HERE))
import test_patcher_upgrade_path as harness

NAMES = {'sync_watchedProgress', 'get_request', '_activities_dict',
         'getWatchedActivity', 'getServerTime'}
CURSOR = 'last_watched_sync_at_v2'
PAGE = {'movies': [], 'episodes': [], 'pagination': {'has_more': False}}


def drive(source, responses, supplied=True, transport=False, snapshots=None):
    pending = iter(responses)
    snapshots = iter(snapshots or [dict(watched_at=150, server_time=200)])
    calls, writes, ingested, activity_reads = [], [], [], []
    def request(url):
        calls.append(url)
        return next(pending)
    def activities():
        value = next(snapshots)
        activity_reads.append(value)
        return value
    db = types.SimpleNamespace(
        last_sync=lambda key: 100,
        update_last_watched_at=lambda key, stamp=None: writes.append((key, stamp)),
        upsert_watched_movie=lambda **kw: ingested.append(('movie', kw)),
        upsert_watched_episode=lambda **kw: ingested.append(('episode', kw)),
        cache_delete=lambda *a: None, _hash_function=lambda *a: 'cache')
    ns = dict(mdbsync=db, getActivities=activities, _activity_timestamp=lambda x: int(x or 0),
              syncMovies=lambda: None, syncTVShows=lambda: None,
              _clr_episode_progress_cache=lambda: None,
              log_utils=types.SimpleNamespace(log=lambda *a, **k: None,
                                             error=lambda: None, LOGDEBUG=0))
    tree = ast.parse(source)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in NAMES]
    assert {n.name for n in nodes} == NAMES
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'upstream-sync', 'exec'), ns)
    if transport:
        class Response:
            status_code = 200
            def json(self):
                raise ValueError('malformed synthetic JSON')
        ns.update(session=types.SimpleNamespace(get=lambda *a, **k: Response()),
                  mdblist_baseurl='https://invalid.example', headers={})
    else:
        ns['get_request'] = request
    result = ns['sync_watchedProgress'](
        activities=dict(watched_at=150, server_time=200) if supplied else None,
        forced=not supplied)
    return dict(result=result, writes=writes, calls=calls, ingested=ingested,
                activity_reads=activity_reads)


class ServerCursorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='umb-server-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.path = self.home / 'addons/plugin.video.umbrella/resources/lib/modules/mdblist.py'
        self.path.parent.mkdir(parents=True)
        self.path.write_text(SOURCE, encoding='utf-8', newline='\n')
        harness._install_stubs(str(self.home))
        self.mod = types.ModuleType('server_patcher')
        self.mod.__file__ = str(PATCHER)
        exec(compile(PATCHER.read_text(encoding='utf-8'), str(PATCHER), 'exec'), self.mod.__dict__)

    def patched(self):
        self.assertEqual(self.mod.ensure_patched(), 'patched')
        return self.path.read_text(encoding='utf-8')

    def test_failure_pages_and_mid_page_failure(self):
        patched = self.patched()
        for bad in (None, {}, {'error': 'temporary failure'}, [], 'invalid'):
            for responses in ([bad], [dict(PAGE, pagination={'has_more': True}), bad]):
                with self.subTest(responses=responses):
                    got = drive(patched, responses)
                    self.assertFalse(got['writes'])
                    self.assertNotEqual(got['result'], True)
        # This must demonstrate the defect, not merely assert desired behavior.
        self.assertTrue(drive(SOURCE, [{}])['writes'])
        self.assertTrue(drive(SOURCE, [{'error': 'temporary failure'}])['writes'])

    def test_real_request_json_decode_fallback(self):
        patched = self.patched()
        self.assertTrue(drive(SOURCE, [], transport=True)['writes'])
        self.assertFalse(drive(patched, [], transport=True)['writes'])

    def test_success_empty_and_paginated(self):
        patched = self.patched()
        movie = {'movie': {'ids': {'imdb': 'tt0000001'}, 'title': 'Test'}, 'last_watched_at': 'test'}
        episode = {'episode': {'show': {'ids': {'imdb': 'tt0000002'}}, 'season': 1, 'number': 2}}
        rows = [dict(PAGE, movies=[movie], pagination={'has_more': True}),
                dict(PAGE, episodes=[episode])]
        for responses, expected_rows in (([PAGE], 0), (rows, 2)):
            with self.subTest(expected_rows=expected_rows):
                result = drive(patched, responses)
                self.assertIs(result['result'], True)
                self.assertEqual(result['writes'], [(CURSOR, 200), ('last_watched_at', 200)])
                self.assertEqual(len(result['ingested']), expected_rows)
                self.assertIn('since=1970-01-01T00:01:40Z', result['calls'][0])
                if expected_rows:
                    self.assertIn('offset=1000', result['calls'][1])

    def test_forced_refresh_freezes_activity_before_pages(self):
        patched = self.patched()
        snapshots = [dict(watched_at=150, server_time=200), dict(watched_at=250, server_time=300)]
        stock = drive(SOURCE, [PAGE], supplied=False, snapshots=snapshots)
        self.assertEqual(stock['writes'][0], (CURSOR, 300))
        fixed = drive(patched, [PAGE], supplied=False, snapshots=snapshots)
        self.assertEqual(fixed['writes'], [(CURSOR, 200), ('last_watched_at', 200)])
        self.assertEqual(len(fixed['activity_reads']), 1)
        # Failed activity lookup must not end in the helper's wall-clock default.
        missing = drive(patched, [PAGE], supplied=False, snapshots=[{}])
        self.assertFalse(missing['writes'])
        self.assertFalse(missing['calls'])

    def test_reset_reaches_generation_two_devices_and_is_one_shot(self):
        db = self.home / 'userdata/addon_data/plugin.video.umbrella/mdbSync.db'
        db.parent.mkdir(parents=True, exist_ok=True)
        retained = {'last_watched_movies_at': 'movies', 'last_watched_episodes_at': 'episodes',
                    'last_activities_at': 'activity'}
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute('CREATE TABLE service (setting TEXT PRIMARY KEY, value TEXT)')
            conn.executemany('INSERT INTO service VALUES (?, ?)',
                             list(retained.items()) + [(CURSOR, '200'), ('last_watched_at', '200')])
        self.mod.kodi_utils.set_setting(self.mod._RESET_FLAG, '2')
        self.patched()
        with closing(sqlite3.connect(db)) as conn, conn:
            self.assertEqual(dict(conn.execute('SELECT * FROM service')), retained)
            conn.execute('INSERT INTO service VALUES (?, ?)', (CURSOR, '300'))
        self.assertEqual(self.mod.kodi_utils.get_setting(self.mod._RESET_FLAG), '3')
        self.assertEqual(self.mod.ensure_patched(), 'unchanged')
        with closing(sqlite3.connect(db)) as conn, conn:
            self.assertEqual(dict(conn.execute('SELECT * FROM service'))[CURSOR], '300')

    def test_both_line_endings_revert_and_upgrade_exactly(self):
        for eol in ('\n', '\r\n'):
            with self.subTest(eol=eol):
                original = SOURCE.replace('\r\n', '\n').replace('\n', eol)
                self.path.write_bytes(original.encode('utf-8'))
                self.assertEqual(self.mod.ensure_patched(), 'patched')
                after = self.path.read_bytes()
                self.assertEqual(self.mod.ensure_patched(), 'unchanged')
                self.assertEqual(self.path.read_bytes(), after)
                self.assertEqual(self.mod._revert(after.decode('utf-8'), eol), original)
                self.path.write_bytes(after.replace(self.mod.MARKER.encode(),
                                                  b'# AI_SUBS_UMB_MDBL_SINCE_v0'))
                self.assertEqual(self.mod.ensure_patched(), 'repatched')
                self.assertEqual(self.path.read_bytes(), after)

    def test_guard_is_scoped_and_partial_refactor_is_refused(self):
        extra = '\ndef unrelated():\n\t\t\tdata = get_request(url)\n'
        self.path.write_text(SOURCE + extra, encoding='utf-8', newline='\n')
        self.assertTrue(self.patched().endswith(extra))
        changed = SOURCE.replace('if data is None: return', 'if not data: return')
        self.path.write_bytes(changed.encode('utf-8'))
        self.assertEqual(self.mod.ensure_patched(), 'unmatched')
        self.assertEqual(self.path.read_bytes(), changed.encode('utf-8'))


if __name__ == '__main__':
    unittest.main()
