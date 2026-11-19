"""The place in a POV film or episode is kept while it plays, not only at the stop (a viewer, Nov 2026: a
series left mid-episode was missing from "continue watching"); and the Wizard's saved data carries POV's
history and favourites (it read a "databases" folder POV never makes)."""
import ast
import importlib.util
import os
import runpy
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'plugin.program.kodipovilwizard'
PATCHES = WIZARD / 'resources/libs/patches'
spec = importlib.util.spec_from_file_location('qa_periodic_bookmark', PATCHES / 'pov_periodic_bookmark.py')
periodic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(periodic)
CONFIG = runpy.run_path(str(PATCHES / 'patches_config.py'))['PATCH_CONFIG']
ENTRY = next(e for e in CONFIG if e['id'] == 'pov_periodic_bookmark')

# POV 6.11.03's playback loop (modules/player.py), as far as the hook needs it
LOOP = (
    "class POVPlayer(object):\n"
    "\tdef check_playback_events(self):\n"
    "\t\ttry:\n"
    "\t\t\tself.monitor.waitForAbort(1)\n"
    "\t\t\tself.total_time, self.curr_time = self.getTotalTime(), self.getTime()\n"
    "\t\t\tself.current_point = round(float(self.curr_time/self.total_time * 100), 1)\n"
    "\t\t\tself.remaining_time = round(self.total_time - self.curr_time)\n"
    "\t\t\tif not self.subs_searched:\n"
    "\t\t\t\tself.exec_task('subtitles')\n"
    "\t\t\tif not self.media_marked:\n"
    "\t\t\t\tif self.current_point >= self.set_watched:\n"
    "\t\t\t\t\tself.media_watched_marker()\n"
    "\t\texcept: pass\n")


class Clock(object):
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def player(**kw):
    p = types.SimpleNamespace(media_marked=False, set_resume=5, set_watched=80, current_point=30.0, curr_time=900.0,
                              total_time=3000.0, mediatype='episode', tmdb_id='1399', title='Episode', season=1, episode=2)
    p.__dict__.update(kw)
    return p


class TickTests(unittest.TestCase):
    def run_ticks(self, indicators, steps, **kw):
        clock, ws = Clock(), Mock()
        settings = types.SimpleNamespace(watched_indicators=lambda: indicators)
        p = player(**kw)
        for seconds, curr in steps:
            clock.now += seconds
            p.curr_time = curr
            periodic.tick(p, ws, settings, clock)
        return ws

    def test_pov_s_own_resume_points_every_minute(self):
        ws = self.run_ticks(0, [(0, 900), (30, 930), (31, 961), (60, 1021), (59, 1080)])
        self.assertEqual(ws.set_bookmark.call_count, 2)
        self.assertEqual(ws.set_bookmark.call_args_list[0].args, ('episode', '1399', 961, 3000.0, 'Episode', 1, 2))
        self.assertEqual(ws.set_bookmark.call_args_list[0].kwargs, {'refresh': 'false'})
        ws.trakt_progress.assert_not_called()

    def test_trakt_and_mdblist_every_three_minutes_without_a_sync(self):
        ws = self.run_ticks(1, [(0, 900), (60, 960), (121, 1081)])
        ws.set_bookmark.assert_not_called()
        ws.trakt_progress.assert_called_once_with('set_progress', 'episode', '1399', 35.9, 1, 2, refresh=False)
        ws = self.run_ticks(2, [(0, 900), (181, 1081)])
        ws.mdbl_progress.assert_called_once()
        ws.trakt_progress.assert_not_called()

    def test_only_between_pov_s_own_limits_and_not_while_paused(self):
        self.assertFalse(self.run_ticks(0, [(0, 60), (61, 70)], current_point=2.0).set_bookmark.called)
        self.assertFalse(self.run_ticks(0, [(0, 2500), (61, 2560)], current_point=85.0).set_bookmark.called)
        self.assertFalse(self.run_ticks(0, [(0, 900), (61, 960)], media_marked=True).set_bookmark.called)
        ws = self.run_ticks(0, [(0, 900), (61, 960), (61, 960), (61, 960)])
        self.assertEqual(ws.set_bookmark.call_count, 1, 'paused: the place did not move')

    def test_it_never_raises(self):
        ws = Mock()
        ws.set_bookmark.side_effect = RuntimeError('database locked')
        clock = Clock()
        p = player()
        settings = types.SimpleNamespace(watched_indicators=lambda: 0)
        periodic.tick(p, ws, settings, clock)
        clock.now += 61
        periodic.tick(p, ws, settings, clock)        # no exception
        periodic.tick(object(), ws, settings, clock)  # nothing it can read: no exception either


class HookTests(unittest.TestCase):
    def patched(self):
        xbmc = types.SimpleNamespace(LOGDEBUG=0, LOGINFO=1, LOGWARNING=2, LOGERROR=3)
        logger = types.SimpleNamespace(log=Mock())
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {
                'xbmc': xbmc, 'xbmcaddon': types.SimpleNamespace(), 'xbmcvfs': types.SimpleNamespace(),
                'resources.libs.common': types.SimpleNamespace(logging=logger)}):
            spec = importlib.util.spec_from_file_location('periodic_engine', WIZARD / 'resources/libs/patch_engine.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            root = Path(tmp)
            target = root / ENTRY['target_file']
            target.parent.mkdir(parents=True)
            target.write_text(LOOP, encoding='utf-8')

            class Engine(module.PatchEngine):
                @staticmethod
                def _resolve_paths(_aid, filename):
                    return str(root), str(root / filename)

                def _is_patch_enabled(self, entry):
                    return True
            Engine([dict(ENTRY)]).run()
            Engine([dict(ENTRY)]).run()
            return target.read_text(encoding='utf-8')

    def test_the_hook_sits_in_the_playback_loop_and_runs(self):
        text = self.patched()
        self.assertEqual(text.count(ENTRY['marker']), 1, 'applied once, the second run leaves it')
        ast.parse(text)
        self.assertLess(text.index('pov_periodic_bookmark'), text.index('if not self.subs_searched:'))
        self.assertGreater(text.index('pov_periodic_bookmark'), text.index('self.current_point = round'))
        # run the patched loop: the first look imports the module (by the patches folder), later looks reuse it
        fake_vfs = types.SimpleNamespace(translatePath=lambda path: str(PATCHES) + os.sep)
        ws = Mock()
        scope = {'ws': ws, 'settings': types.SimpleNamespace(watched_indicators=lambda: 0)}
        with patch.dict(sys.modules, {'xbmcvfs': fake_vfs}):
            sys.modules.pop('pov_periodic_bookmark', None)
            exec(compile(text, 'player.py', 'exec'), scope)
            p = scope['POVPlayer']()
            p.monitor = types.SimpleNamespace(waitForAbort=lambda s: False)
            p.getTotalTime, p.getTime = (lambda: 3000.0), (lambda: 900.0)
            p.subs_searched, p.media_marked, p.set_resume, p.set_watched = True, False, 5, 80
            p.mediatype, p.tmdb_id, p.title, p.season, p.episode = 'movie', '27205', 'Inception', '', ''
            p.check_playback_events()
            self.assertTrue(callable(getattr(p, '_povil_periodic', None)))
            p._povil_saved_at -= 61
            p.getTime = lambda: 960.0
            p.check_playback_events()
            sys.modules.pop('pov_periodic_bookmark', None)
        ws.set_bookmark.assert_called_once_with('movie', '27205', 960.0, 3000.0, 'Inception', '', '', refresh='false')


class SavedDataTests(unittest.TestCase):
    def test_pov_s_own_data_is_saved_and_its_caches_are_not(self):
        source = (WIZARD / 'resources/libs/save.py').read_text(encoding='utf-8')
        self.assertNotIn("'plugin.video.pov', 'databases'", source)
        tree = ast.parse(source)
        wanted = {'POV_DATA_FILES', 'POV_DATA_PREFIX', 'pov_data_files', '_add_pov_data_to_zip', '_consistent_copy'}
        nodes = [n for n in tree.body if (isinstance(n, ast.Assign) and n.targets[0].id in wanted) or
                 (isinstance(n, ast.FunctionDef) and n.name in wanted)]
        scope = {'os': os, 'zipfile': zipfile}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'save.py', 'exec'), scope)
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('navigator.db', 'views.db', 'metacache.db', 'maincache.db', 'traktcache.db',
                         'settings.xml', 'povil_favorites_order', 'povil_dropped_trakt.json', 'povil_dropped_trakt.json.lock.db'):
                Path(tmp, name).write_text('x')
            # watched.db a real database, open for writing while it is saved (POV writing during playback)
            import sqlite3
            live = sqlite3.connect(os.path.join(tmp, 'watched.db'))
            live.execute('CREATE TABLE favorites (db_type TEXT, tmdb_id TEXT, title TEXT)')
            live.execute("INSERT INTO favorites VALUES ('movie', '27205', 'Inception')")
            live.commit()
            live.execute("INSERT INTO favorites VALUES ('movie', '1', 'not committed')")
            os.mkdir(os.path.join(tmp, 'povil_snapshots'))
            self.assertEqual(scope['pov_data_files'](tmp), ['navigator.db', 'povil_dropped_trakt.json', 'povil_favorites_order',
                                                           'views.db', 'watched.db'])
            target = os.path.join(tmp, 'out.zip')
            with zipfile.ZipFile(target, 'w') as zipf:
                scope['_add_pov_data_to_zip'](zipf, tmp, 'pov')
            live.rollback()
            live.close()
            with zipfile.ZipFile(target) as zipf:
                names = [n.replace(os.sep, '/') for n in zipf.namelist()]
                self.assertIn('pov/watched.db', names)
                saved = os.path.join(tmp, 'saved.db')
                with open(saved, 'wb') as handle:
                    handle.write(zipf.read([n for n in zipf.namelist() if n.replace(os.sep, '/') == 'pov/watched.db'][0]))
            con = sqlite3.connect(saved)
            self.assertEqual(con.execute('SELECT title FROM favorites').fetchall(), [('Inception',)],
                             'SQLite\'s own copy: committed rows, nothing half written')
            con.close()


if __name__ == '__main__':
    unittest.main()
