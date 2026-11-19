"""Device-to-device sync of POV's and Umbrella's own local lists (Wizard, resources/libs/cloud_sync).

The owner, Nov 2026: "sync between devices from anywhere, of series and films -- lists and continue watching --
without Trakt or MDBList". These tests hold the merge's promises (every device ends with the same lists, a removal
travels, an add-on that is not installed loses nothing) and the lists' round trip through POV's and Umbrella's own
files (schemas as POV 6.11.03 and Umbrella 6.8 make them).
"""
import importlib
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBS = str(ROOT / 'plugin.program.kodipovilwizard/resources/libs')
sys.path.insert(0, LIBS)
records = importlib.import_module('cloud_sync.records')
stores = importlib.import_module('cloud_sync.stores')
sys.path.remove(LIBS)

POV_SCHEMA = (
    'CREATE TABLE watched_status (db_type text, media_id text, season integer, episode integer, last_played text, title text, '
    'unique(db_type, media_id, season, episode))',
    'CREATE TABLE progress (db_type text, media_id text, season integer, episode integer, resume_point text, curr_time text, '
    'last_played text, resume_id integer, title text, unique(db_type, media_id, season, episode))',
    'CREATE TABLE favorites (db_type TEXT, tmdb_id TEXT, title TEXT, UNIQUE (db_type, tmdb_id))',
    'CREATE TABLE dropped (db_type TEXT, tmdb_id TEXT, title TEXT, UNIQUE (db_type, tmdb_id))',
)
UMB_WATCHED_SCHEMA = (
    'CREATE TABLE IF NOT EXISTS watched (media_type TEXT, imdb_id TEXT, tmdb_id TEXT, season INTEGER, episode INTEGER, title TEXT, '
    'last_played TEXT, overlay INTEGER, UNIQUE (imdb_id, tmdb_id, season, episode));',
    'CREATE TABLE IF NOT EXISTS progress (media_type TEXT, imdb_id TEXT, tmdb_id TEXT, season INTEGER, episode INTEGER, title TEXT, '
    'resume_point TEXT, curr_time TEXT, last_played TEXT, resume_id INTEGER, UNIQUE (imdb_id, tmdb_id, season, episode));',
)


def db(path, statements, rows=()):
    con = sqlite3.connect(path)
    for s in statements:
        con.execute(s)
    for sql, values in rows:
        con.execute(sql, values)
    con.commit()
    con.close()


class Device(object):
    """One Kodi: its own POV / Umbrella folders and the map it last saw."""

    def __init__(self, root, name, pov=True, umbrella=True):
        self.pov = os.path.join(root, name, 'pov') if pov else None
        self.umb = os.path.join(root, name, 'umbrella') if umbrella else None
        for folder in (self.pov, self.umb):
            if folder:
                os.makedirs(folder)
        if pov:
            db(os.path.join(self.pov, 'watched.db'), POV_SCHEMA)
        if umbrella:
            db(os.path.join(self.umb, 'watched.db'), UMB_WATCHED_SCHEMA)
        self.stores = stores.Stores(self.pov, self.umb)
        self.base = {}

    def sql(self, name, sql, values=()):
        con = sqlite3.connect(os.path.join(self.pov if name == 'pov' else self.umb, 'watched.db' if name != 'umbfav' else 'favourites.db'))
        con.execute(sql, values)
        con.commit()
        con.close()

    def sync(self, cloud, now):
        """What the engine does in one round, with a cloud that is a plain dict."""
        values, _skipped = self.stores.read()
        local = records.changes(self.base, values, now, self.stores.mine)
        merged = records.merge(cloud.get('records', {}), local)
        put, remove = records.to_apply(merged, values, self.stores.mine)
        self.stores.write(put, remove, values)
        cloud['records'] = records.loads(records.dumps(merged))
        after, _ = self.stores.read()
        self.base = {k: r for k, r in merged.items() if r.get('d') or k in after or not self.stores.mine(k)}
        return put, remove


class MergeTests(unittest.TestCase):
    def test_the_later_change_wins_and_a_removal_is_a_change(self):
        a = {'pov.fav.movie.1': {'v': {'title': 'A'}, 't': 10}}
        b = {'pov.fav.movie.1': {'t': 20, 'd': 1}}
        self.assertEqual(records.merge(a, b), b)
        self.assertEqual(records.merge(b, a), b, 'the same whatever the order')
        c = {'pov.fav.movie.1': {'v': {'title': 'A again'}, 't': 30}}
        self.assertEqual(records.merge(a, b, c)['pov.fav.movie.1']['v'], {'title': 'A again'})

    def test_what_changed_on_the_device_is_found_against_the_map_it_last_saw(self):
        base = {'pov.fav.movie.1': {'v': {'title': 'A'}, 't': 10}, 'pov.fav.movie.2': {'v': {'title': 'B'}, 't': 10},
                'umb.fav.movies.tt9': {'v': {'id': 'tt9'}, 't': 10}}
        values = {'pov.fav.movie.1': {'title': 'A'}, 'pov.fav.movie.3': {'title': 'C'}}
        out = records.changes(base, values, 99, mine=lambda key: key.startswith('pov.'))
        self.assertEqual(out['pov.fav.movie.1'], base['pov.fav.movie.1'], 'unchanged: keeps its time')
        self.assertEqual(out['pov.fav.movie.2'], {'t': 99, 'd': 1}, 'gone from the device: removed now')
        self.assertEqual(out['pov.fav.movie.3'], {'v': {'title': 'C'}, 't': 99})
        self.assertEqual(out['umb.fav.movies.tt9'], base['umb.fav.movies.tt9'], 'Umbrella is not here: nothing of it is removed')

    def test_whatever_arrives_from_the_cloud_is_checked_first(self):
        bad = {
            'pov.fav.movie.1': {'v': {'title': 'ok', 'x': [1, 2], 'nested': {'deep': {'deeper': {'deepest': 1}}}}, 't': 5},
            'pov.fav.movie.1; DROP TABLE favorites': {'v': {'title': 'x'}, 't': 5},
            'evil.fav.movie.1': {'v': {}, 't': 5},
            'pov.fav.movie.2': {'v': {'title': '__import__("os").system("x")'}, 't': 5},
            'pov.fav.movie.3': {'v': {'title': 'x'}, 't': 'soon'},
            'pov.fav.movie.4': {'v': {'title': 'x' * 1000}, 't': 5},
        }
        got = records.clean(bad)
        self.assertEqual(sorted(got), ['pov.fav.movie.1', 'pov.fav.movie.2', 'pov.fav.movie.4'])
        self.assertEqual(got['pov.fav.movie.1']['v'], {'title': 'ok', 'nested': {'deep': {}}}, 'no lists, two levels at most')
        self.assertEqual(got['pov.fav.movie.2']['v']['title'], '__import__("os").system("x")', 'kept as text: never run')
        self.assertEqual(len(got['pov.fav.movie.4']['v']['title']), records.MAX_TEXT)
        self.assertEqual(records.loads('not json'), {})
        self.assertEqual(records.loads('{"format": 2, "records": {}}'), {})

    def test_old_removals_are_forgotten_new_ones_kept(self):
        day = 86400 * 1000
        now = 200 * day
        recs = {'a.fav.movie.1': {'t': now - 121 * day, 'd': 1}, 'pov.fav.movie.2': {'t': now - 5 * day, 'd': 1},
                'pov.fav.movie.3': {'v': {}, 't': 1}}
        self.assertEqual(sorted(records.forget_old(recs, now)), ['pov.fav.movie.2', 'pov.fav.movie.3'])


class DevicesTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='povil-sync-')

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_favourites_places_and_watched_marks_travel_both_ways_and_removals_too(self):
        tv, phone, cloud = Device(self.root, 'tv'), Device(self.root, 'phone'), {}
        tv.sql('pov', 'INSERT INTO favorites VALUES (?, ?, ?)', ('movie', '27205', 'Inception'))
        tv.sql('pov', 'INSERT INTO progress VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
               ('episode', '1399', 1, 2, '35.5', '1200.0', '2026-11-19 21:00:00', 7, 'Game of Thrones'))
        phone.sql('pov', 'INSERT INTO watched_status VALUES (?, ?, ?, ?, ?, ?)', ('episode', '1399', 1, 1, '2026-11-18 20:00:00', 'GoT'))
        tv.sync(cloud, 100)
        phone.sync(cloud, 200)
        tv.sync(cloud, 300)
        for device in (tv, phone):
            values, skipped = device.stores.read()
            self.assertEqual(skipped, 0)
            self.assertEqual(values['pov.fav.movie.27205'], {'db_type': 'movie', 'tmdb_id': '27205', 'title': 'Inception'})
            self.assertEqual(values['pov.progress.episode.1399.1.2']['curr_time'], '1200.0')
            self.assertEqual(values['pov.progress.episode.1399.1.2']['season'], 1, 'written back as the number it was')
            self.assertIn('pov.watched.episode.1399.1.1', values)
        # removed on the phone: gone from the TV too, and a second sync changes nothing
        phone.sql('pov', 'DELETE FROM favorites WHERE tmdb_id = ?', ('27205',))
        phone.sync(cloud, 400)
        put, remove = tv.sync(cloud, 500)
        self.assertEqual((put, remove), ({}, ['pov.fav.movie.27205']))
        self.assertNotIn('pov.fav.movie.27205', tv.stores.read()[0])
        self.assertEqual(tv.sync(cloud, 600), ({}, []), 'settled')
        self.assertEqual(phone.sync(cloud, 700), ({}, []))

    def test_a_device_without_umbrella_keeps_umbrella_s_lists_for_the_others(self):
        tv, box, cloud = Device(self.root, 'tv'), Device(self.root, 'box', umbrella=False), {}
        tv.sql('umb', 'INSERT INTO watched VALUES (?, ?, ?, ?, ?, ?, ?, ?)', ('movie', 'tt1375666', '27205', '', '', 'Inception', '2026-11-19', 5))
        tv.sync(cloud, 100)
        box.sync(cloud, 200)
        box.sync(cloud, 300)
        self.assertIn('umb.watched.movie.tt1375666.27205._._', cloud['records'])
        self.assertFalse(cloud['records']['umb.watched.movie.tt1375666.27205._._'].get('d'))
        self.assertEqual(tv.sync(cloud, 400), ({}, []))

    def test_umbrella_favourites_round_trip_as_plain_literals_never_code(self):
        tv, phone, cloud = Device(self.root, 'tv'), Device(self.root, 'phone'), {}
        details = {'title': 'Inception', 'year': '2010', 'imdb': 'tt1375666', 'tmdb': '27205', 'poster': 'https://image.tmdb.org/t/p/w500/x.jpg'}
        tv.sql('umbfav', 'CREATE TABLE IF NOT EXISTS movies (id TEXT, items TEXT, UNIQUE(id));')
        tv.sql('umbfav', 'INSERT INTO movies VALUES (?, ?)', ('tt1375666', repr(details)))
        episode = {'title': 'Pilot', 'tvshowtitle': 'Show', 'season': '1', 'episode': '1', 'imdb': 'tt0944947',
                   'episodeIDS': {'trakt': 73640, 'tvdb': 3254641}}
        tv.sql('umbfav', 'CREATE TABLE IF NOT EXISTS episode (id TEXT, season TEXT, episode TEXT, items TEXT, imdb TEXT, UNIQUE(id));')
        tv.sql('umbfav', 'INSERT INTO episode VALUES (?, ?, ?, ?, ?)', ('tt094494711', '1', '1', repr(episode), 'tt0944947'))
        # a row whose details are code, not a literal: never read, never sent
        tv.sql('umbfav', 'INSERT INTO movies VALUES (?, ?)', ('tt0000001', '__import__("os").getcwd()'))
        tv.sync(cloud, 100)
        phone.sync(cloud, 200)
        con = sqlite3.connect(os.path.join(phone.umb, 'favourites.db'))
        rows = dict(con.execute('SELECT id, items FROM movies'))
        ep = con.execute('SELECT id, season, episode, items, imdb FROM episode').fetchall()
        con.close()
        self.assertEqual(sorted(rows), ['tt1375666'])
        import ast
        self.assertEqual(ast.literal_eval(rows['tt1375666']), details)
        self.assertEqual(ep[0][:3] + (ep[0][4],), ('tt094494711', '1', '1', 'tt0944947'))
        self.assertEqual(ast.literal_eval(ep[0][3]), episode)

    def test_a_row_written_from_the_cloud_with_hostile_values_stays_data(self):
        phone, cloud = Device(self.root, 'phone'), {}
        cloud['records'] = records.clean({
            'pov.fav.movie.1': {'v': {'db_type': 'movie', 'tmdb_id': "1'); DROP TABLE favorites; --", 'title': 'x'}, 't': 5},
            'umb.fav.movies.tt1': {'v': {'id': 'tt1', 'items': {'title': '__import__("os").remove("x")'}}, 't': 5},
        })
        phone.sync(cloud, 10)
        con = sqlite3.connect(os.path.join(phone.pov, 'watched.db'))
        self.assertEqual(con.execute('SELECT tmdb_id FROM favorites').fetchall(), [], 'its values do not name the row its key names')
        self.assertEqual(con.execute("SELECT name FROM sqlite_master WHERE name='favorites'").fetchall(), [('favorites',)])
        con.close()
        cloud['records']['pov.fav.movie.2'] = {'v': {'db_type': 'movie', 'tmdb_id': '2', 'title': "x'); DROP TABLE favorites; --"}, 't': 6}
        phone.sync(cloud, 20)
        con = sqlite3.connect(os.path.join(phone.pov, 'watched.db'))
        self.assertEqual(con.execute('SELECT title FROM favorites').fetchall(), [("x'); DROP TABLE favorites; --",)], 'a value is data')
        con.close()
        con = sqlite3.connect(os.path.join(phone.umb, 'favourites.db'))
        text = con.execute('SELECT items FROM movies').fetchone()[0]
        con.close()
        import ast
        self.assertEqual(ast.literal_eval(text), {'title': '__import__("os").remove("x")'}, 'a string literal: eval() gives the text back')
        self.assertTrue(text.startswith("{'title': '"))


def _engine():
    sys.path.insert(0, LIBS)
    try:
        return importlib.import_module('cloud_sync.engine'), importlib.import_module('cloud_sync.drive')
    finally:
        sys.path.remove(LIBS)


class FakeDrive(object):
    """The viewer's Drive as the engine sees it, with the quota units of each call (May 2026 table)."""

    def __init__(self, store):
        self.store, self.calls = store, []

    def find(self):
        self.calls.append(('find', 100))
        return dict(self.store['meta']) if self.store.get('meta') else None

    def look(self, file_id):
        self.calls.append(('look', 5))
        meta = self.store.get('meta')
        return dict(meta) if meta and meta['id'] == file_id else None

    def download(self, file_id):
        self.calls.append(('download', 200))
        return self.store['text']

    def upload(self, text, file_id=None):
        self.calls.append(('upload', 50))
        self.store['text'] = text
        self.store['version'] = self.store.get('version', 0) + 1
        self.store['meta'] = {'id': file_id or 'file-1', 'md5Checksum': 'md5-%d' % self.store['version']}
        return dict(self.store['meta'])


class RoundTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='povil-round-')
        self.engine, self.drive = _engine()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def device(self, name, **kw):
        d = Device(self.root, name, **kw)
        d.folder = self.engine.Folder(os.path.join(self.root, name, 'wizard'))
        return d

    def test_a_quiet_round_costs_one_look_and_a_change_one_upload(self):
        cloud = {}
        tv, phone = self.device('tv'), self.device('phone')
        tv.sql('pov', 'INSERT INTO favorites VALUES (?, ?, ?)', ('tv', '1399', 'Game of Thrones'))
        drive = FakeDrive(cloud)
        first = self.engine.sync_round(tv.folder, tv.stores, drive, 1000)
        self.assertEqual((first['uploaded'], first['records']), (True, 1))
        self.assertEqual([c[0] for c in drive.calls], ['find', 'upload'], 'no file yet: one search, one upload')
        drive = FakeDrive(cloud)
        self.engine.sync_round(phone.folder, phone.stores, drive, 2000)
        self.assertEqual([c[0] for c in drive.calls], ['find', 'download'], 'a new device: one search, one read, nothing to add')
        self.assertIn('pov.fav.tv.1399', phone.stores.read()[0])
        for device in (tv, phone):
            drive = FakeDrive(cloud)
            self.engine.sync_round(device.folder, device.stores, drive, 3000)
            self.assertEqual(drive.calls, [('look', 5)], 'nothing new anywhere: 5 units')
        phone.sql('pov', 'INSERT INTO favorites VALUES (?, ?, ?)', ('movie', '27205', 'Inception'))
        drive = FakeDrive(cloud)
        self.engine.sync_round(phone.folder, phone.stores, drive, 4000)
        self.assertEqual(sum(u for _c, u in drive.calls), 55, 'one look, one upload')
        drive = FakeDrive(cloud)
        self.engine.sync_round(tv.folder, tv.stores, drive, 5000)
        self.assertEqual(sum(u for _c, u in drive.calls), 205, 'one look, one read')
        self.assertIn('pov.fav.movie.27205', tv.stores.read()[0])

    def test_two_devices_that_upload_over_each_other_still_end_with_everything(self):
        cloud = {}
        tv, phone = self.device('tv'), self.device('phone')
        self.engine.sync_round(tv.folder, tv.stores, FakeDrive(cloud), 1000)
        self.engine.sync_round(phone.folder, phone.stores, FakeDrive(cloud), 1100)
        tv.sql('pov', 'INSERT INTO favorites VALUES (?, ?, ?)', ('movie', '1', 'One'))
        phone.sql('pov', 'INSERT INTO favorites VALUES (?, ?, ?)', ('movie', '2', 'Two'))
        # both read the same file, then each uploads: the second upload drops the first one's favourite from the file
        snapshot = dict(cloud)
        self.engine.sync_round(tv.folder, tv.stores, FakeDrive(cloud), 2000)
        version = cloud['version']
        cloud.clear()
        cloud.update(snapshot)
        self.engine.sync_round(phone.folder, phone.stores, FakeDrive(cloud), 2001)
        self.assertNotIn('pov.fav.movie.1', records.loads(cloud['text']))
        cloud['version'] = version + 1
        cloud['meta'] = {'id': 'file-1', 'md5Checksum': 'md5-race'}
        for when in (3000, 3100, 3200, 3300):
            for device in (tv, phone):
                self.engine.sync_round(device.folder, device.stores, FakeDrive(cloud), when)
        for device in (tv, phone):
            values = device.stores.read()[0]
            self.assertIn('pov.fav.movie.1', values)
            self.assertIn('pov.fav.movie.2', values)

    def test_drive_errors_leave_what_the_device_knew_untouched(self):
        cloud = {}
        tv = self.device('tv')
        tv.sql('pov', 'INSERT INTO favorites VALUES (?, ?, ?)', ('movie', '1', 'One'))
        self.engine.sync_round(tv.folder, tv.stores, FakeDrive(cloud), 1000)
        before = tv.folder.maps()
        error = self.drive.DriveError

        class Broken(FakeDrive):
            def look(self, file_id):
                raise error(503, 'busy')
        with self.assertRaises(self.drive.DriveError):
            self.engine.sync_round(tv.folder, tv.stores, Broken(cloud), 2000)
        self.assertEqual(tv.folder.maps(), before)

    def test_only_one_round_at_a_time(self):
        folder = self.engine.Folder(os.path.join(self.root, 'w'))
        self.assertTrue(folder.lock())
        self.assertFalse(folder.lock(), 'the service and the tile never run a round together')
        folder.unlock()
        self.assertTrue(folder.lock())
        folder.unlock()


class DeviceFlowTests(unittest.TestCase):
    def setUp(self):
        _e, self.drive = _engine()

    def opener(self, answers):
        import io as _io
        import json as _json
        import urllib.error
        sent = []

        class Opener(object):
            def open(self, request, timeout=None):
                sent.append((request.get_method(), request.full_url, request.data))
                status, body = answers.pop(0)
                if status >= 400:
                    raise urllib.error.HTTPError(request.full_url, status, 'x', {}, _io.BytesIO(_json.dumps(body).encode()))

                class Answer(object):
                    def __init__(self):
                        self.status, self.headers = status, {}

                    def read(self):
                        return _json.dumps(body).encode()

                    def __enter__(self):
                        return self

                    def __exit__(self, *a):
                        return False
                return Answer()
        return Opener(), sent

    def test_the_code_is_asked_until_the_viewer_approves(self):
        opener, sent = self.opener([
            (200, {'device_code': 'dc', 'user_code': 'ABCD-EFGH', 'verification_url': 'https://www.google.com/device', 'expires_in': 1800,
                   'interval': 5}),
            (428, {'error': 'authorization_pending'}),
            (403, {'error': 'slow_down'}),
            (200, {'access_token': 'at', 'refresh_token': 'rt', 'expires_in': 3599}),
        ])
        flow = self.drive.start_device_flow('client', opener=opener)
        self.assertIn(b'scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive.appdata', sent[0][2], 'only the app folder')
        waited = []
        tokens = self.drive.poll_device_flow('client', 'secret', flow, wait=waited.append, clock=lambda: 1000.0, opener=opener)
        self.assertEqual(tokens['refresh_token'], 'rt')
        self.assertEqual(waited, [5, 5, 10], 'slow_down: asks less often')

    def test_a_refused_or_expired_code_ends_without_tokens(self):
        for error in ('access_denied', 'expired_token'):
            opener, _sent = self.opener([(403, {'error': error})])
            self.assertIsNone(self.drive.poll_device_flow('c', 's', {'device_code': 'd', 'interval': 1, 'expires_in': 60},
                                                          wait=lambda s: None, clock=lambda: 0.0, opener=opener))

    def test_a_revoked_access_says_so(self):
        opener, _sent = self.opener([(400, {'error': 'invalid_grant'})])
        drive = self.drive.Drive('c', 's', {'refresh_token': 'rt'}, opener=opener)
        with self.assertRaises(self.drive.Disconnected):
            drive.look('file-1')


if __name__ == '__main__':
    unittest.main()
