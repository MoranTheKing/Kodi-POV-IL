"""POV 6.10.16 restructure: the build's hooks follow the moved files.

6.10.16 moved resources/lib/entry.py to resources/lib/modules/entry.py,
session.py to modules/session.py (imported as modules.session), re-sorted
watched_cache.py's imports and moved its UI strings into
modules/strings_po.py. Devices update POV from its developer's repository on
their own; with the old config ten hooks lost their anchors and the half-
applied watched_cache pair left dummy modules in sys.modules, so every
next-episode / in-progress list failed (field reports, 21 Oct 2026).
"""
import importlib.util
import os
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'plugin.program.kodipovilwizard'
PATCHES = WIZARD / 'resources/libs/patches'
FIXTURE = ROOT / 'tests/fixtures/http_session/session.py'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EngineFollowsMovedFile(unittest.TestCase):
    def run_engine(self, rel_existing):
        xbmc = types.SimpleNamespace(LOGDEBUG=0, LOGINFO=1, LOGWARNING=2, LOGERROR=3)
        logger = types.SimpleNamespace(log=Mock())
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {
                'xbmc': xbmc, 'xbmcaddon': types.SimpleNamespace(),
                'xbmcvfs': types.SimpleNamespace(),
                'resources.libs.common': types.SimpleNamespace(logging=logger)}):
            engine = load('engine_6_10_16', WIZARD / 'resources/libs/patch_engine.py')
            root = Path(tmp)
            target = root / rel_existing
            target.parent.mkdir(parents=True)
            target.write_text('from threading import Thread\nx = 1\n', encoding='utf-8')
            config = [dict(id='moved', name='moved', addon_id='plugin.video.pov',
                           target_file='resources/lib/entry.py',
                           target_alternatives=['resources/lib/modules/entry.py'],
                           marker='# MOVED_v1', anchor='from threading import Thread',
                           action='prepend_before', hook='y = 2\n')]

            class Engine(engine.PatchEngine):
                @staticmethod
                def _resolve_paths(_aid, filename):
                    return str(root), str(root / filename)

                def _is_patch_enabled(self, entry):
                    return True
            first, second = Engine(config).run(), Engine(config).run()
            return first, second, target.read_text(encoding='utf-8')

    def test_old_and_new_layout(self):
        for rel in ('resources/lib/entry.py', 'resources/lib/modules/entry.py'):
            with self.subTest(rel=rel):
                first, second, text = self.run_engine(rel)
                self.assertEqual((first['applied'], first['missing']), (1, 0))
                self.assertEqual(second['skipped_current'], 1)
                self.assertIn('# MOVED_v1', text)

    def test_config_points_every_entry_hook_at_both_layouts(self):
        config = runpy.run_path(str(PATCHES / 'patches_config.py'))['PATCH_CONFIG']
        entry = [e for e in config if e['target_file'] == 'resources/lib/entry.py']
        self.assertEqual(len(entry), 6)
        for e in entry:
            self.assertEqual(e.get('target_alternatives'), ['resources/lib/modules/entry.py'], e['id'])


class SharedSessionUnderModulesPackage(unittest.TestCase):
    def test_6_10_16_defers_modules_session(self):
        lazy = load('lazy_6_10_16', PATCHES / 'pov_http_session.py')
        saved = {k: sys.modules.pop(k, None) for k in ('modules', 'modules.session', '_povil_native_session')}
        try:
            with tempfile.TemporaryDirectory() as tmp:
                pkg = Path(tmp) / 'modules'
                pkg.mkdir()
                (pkg / '__init__.py').write_text('', encoding='utf-8')
                sys.path.insert(0, tmp)
                try:
                    self.assertTrue(lazy.install(str(FIXTURE), '6.10.16', 'modules.session'))
                    proxy = sys.modules['modules.session']
                    from modules.session import session, HTTPAdapter, Retry  # noqa: F401
                    self.assertIs(proxy._native, None)        # nothing loaded yet
                    self.assertFalse(lazy.install(str(FIXTURE), '6.10.16', 'modules.session'))
                finally:
                    sys.path.remove(tmp)
        finally:
            for key, value in saved.items():
                sys.modules.pop(key, None)
                if value is not None:
                    sys.modules[key] = value


class WatchedMockNeedsItsCleanup(unittest.TestCase):
    def test_mock_only_with_proxy_in_the_same_file(self):
        fake_xbmc = types.SimpleNamespace(log=Mock(), LOGWARNING=2, LOGERROR=3)
        with patch.dict(sys.modules, {'xbmc': fake_xbmc}):
            lazy = load('watched_lazy_6_10_16', PATCHES / 'pov_watched_lazy_imports.py')
            with tempfile.TemporaryDirectory() as tmp:
                for proxy, expected in ((False, False), (True, True)):
                    path = Path(tmp) / ('watched_%s.py' % proxy)
                    body = '# --- BEGIN PATCH ID: x ---\n# WIZARD_POV_WATCHED_LAZY_MOCK_v2\n'
                    if proxy:
                        body += '# WIZARD_POV_WATCHED_LAZY_PROXY_v2\n'
                    path.write_text(body, encoding='utf-8')
                    for mod in lazy.DUMMY_MODULES:
                        sys.modules.pop(mod, None)
                    try:
                        lazy.mock_modules({'__file__': str(path)})
                        dummied = isinstance(sys.modules.get('indexers.local_api'), lazy.DummyModule)
                        self.assertEqual(dummied, expected)
                    finally:
                        for mod in lazy.DUMMY_MODULES:
                            if isinstance(sys.modules.get(mod), lazy.DummyModule):
                                del sys.modules[mod]

    def test_hook_without_arguments_reads_the_callers_file(self):
        fake_xbmc = types.SimpleNamespace(log=Mock(), LOGWARNING=2, LOGERROR=3)
        with patch.dict(sys.modules, {'xbmc': fake_xbmc}):
            lazy = load('watched_lazy_6_10_16b', PATCHES / 'pov_watched_lazy_imports.py')
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'watched_cache.py'
                path.write_text('import lazy_mod\nlazy_mod.mock_modules()\n', encoding='utf-8')
                for mod in lazy.DUMMY_MODULES:
                    sys.modules.pop(mod, None)
                with patch.dict(sys.modules, {'lazy_mod': lazy}):
                    runpy.run_path(str(path))       # no proxy marker in this file
                self.assertNotIn('indexers.local_api', sys.modules)
                # the same call from a file that carries the proxy marker mocks
                path.write_text('# WIZARD_POV_WATCHED_LAZY_PROXY_v2\n'
                                'import lazy_mod\nlazy_mod.mock_modules()\n', encoding='utf-8')
                try:
                    with patch.dict(sys.modules, {'lazy_mod': lazy}):
                        runpy.run_path(str(path))
                        self.assertIsInstance(sys.modules.get('indexers.local_api'), lazy.DummyModule)
                finally:
                    for mod in lazy.DUMMY_MODULES:
                        if isinstance(sys.modules.get(mod), lazy.DummyModule):
                            del sys.modules[mod]


class AgeGuardFindsMovedEntry(unittest.TestCase):
    def test_host_integrity_accepts_modules_entry(self):
        guard = load('age_guard_6_10_16', PATCHES / 'profile_age_guard.py')
        with tempfile.TemporaryDirectory() as tmp:
            pov = Path(tmp) / 'plugin.video.pov'
            files = {
                'resources/lib/modules/entry.py': '# WIZARD_POV_PROFILE_DIRECTORY_v1\n# WIZARD_POV_PROFILE_ROUTE_v1\n',
                'resources/lib/modules/player.py': '# WIZARD_POV_PROFILE_PLAY_v1\n',
                'resources/lib/menus/movies.py': '# WIZARD_POV_PROFILE_MOVIE_META_v1\n',
                'resources/lib/menus/tvshows.py': '# WIZARD_POV_PROFILE_TV_META_v1\n',
                'resources/lib/indexers/metadata.py': '# WIZARD_POV_PROFILE_EPISODE_META_v1\n'}
            for rel, text in files.items():
                (pov / rel).parent.mkdir(parents=True, exist_ok=True)
                (pov / rel).write_text(text, encoding='utf-8')
            self.assertTrue(guard.host_integrity(tmp))
            (pov / 'resources/lib/modules/entry.py').write_text('# nothing\n', encoding='utf-8')
            self.assertFalse(guard.host_integrity(tmp))


class DebridStatusFindsModulesEntry(unittest.TestCase):
    def test_neutralizes_modules_entry(self):
        fake_xbmc = types.SimpleNamespace(log=Mock(), LOGINFO=1, LOGWARNING=2, LOGERROR=3)
        with patch.dict(sys.modules, {'xbmc': fake_xbmc}):
            status = load('debrid_status_6_10_16', PATCHES / 'pov_debrid_status.py')
        fake_entry = types.ModuleType('modules.entry')
        fake_entry.premAccntNotification = lambda: 'upstream toast'
        package = types.ModuleType('modules')
        package.__path__ = []
        package.entry = fake_entry
        with patch.dict(sys.modules, {'modules': package, 'modules.entry': fake_entry,
                                      'xbmc': types.SimpleNamespace(log=Mock(), LOGINFO=1,
                                                                    LOGWARNING=2, LOGERROR=3)}):
            status.xbmc = sys.modules['xbmc']
            status.run({})
            self.assertIsNone(fake_entry.premAccntNotification())


class HebrewStringsTable(unittest.TestCase):
    def test_strings_po_py_entries_are_set_and_compile(self):
        with patch.dict(sys.modules, {'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p)}):
            heb = load('heb_6_10_16', ROOT / 'service.subtitles.kodipovilai/resources/lib/pov_hebrew_ui_patcher.py')
        src = ("from types import MappingProxyType\nstrings_po = MappingProxyType({\n"
               "32028: 'Movies',\n32450: 'Search',\n32537: 'Season',\n32832: 'It\\'s Resume',\n})\n")
        out, applied = heb._apply_py(src)
        self.assertEqual(applied, 4)
        ns = {}
        exec(compile(out, 'strings_po.py', 'exec'), ns)
        self.assertEqual(ns['strings_po'][32450], heb.HE['32450'])
        self.assertEqual(ns['strings_po'][32832], heb.HE['32832'])
        self.assertEqual(heb._apply_py(out), (out, 4))   # idempotent text


class ContinueWatchingRemoteRead(unittest.TestCase):
    def test_dropped_list_reader_imports_modules_session(self):
        # Reviewer find: `from session import ...` cannot resolve on 6.10.16,
        # so Trakt/MDBList users' next-episode lists came back empty.
        with patch.dict(sys.modules, {'xbmc': types.SimpleNamespace(log=Mock(), LOGWARNING=2)}):
            cw = load('cw_6_10_16', PATCHES / 'pov_continue_watching.py')
        calls = []

        class Boom(Exception):
            pass

        class Client:
            def mount(self, *a):
                pass

            def request(self, *a, **k):
                calls.append(a)
                raise Boom()

            def close(self):
                pass
        fake_session = types.ModuleType('modules.session')
        fake_session.TimeoutSession = Client
        fake_session.HTTPAdapter = lambda **k: None
        modules_pkg = types.ModuleType('modules')
        modules_pkg.__path__ = []
        modules_pkg.kodi_utils = types.SimpleNamespace(get_setting=lambda key: '')
        modules_pkg.session = fake_session
        api = types.SimpleNamespace(base_url='https://api.example', READ_TOKEN='x')
        indexers = types.ModuleType('indexers')
        indexers.__path__ = []
        indexers.trakt_api = api
        indexers.mdblist_api = api
        stubs = {'modules': modules_pkg, 'modules.kodi_utils': modules_pkg.kodi_utils,
                 'modules.session': fake_session, 'indexers': indexers,
                 'indexers.trakt_api': api, 'indexers.mdblist_api': api}
        saved = sys.modules.pop('session', None)
        try:
            with patch.dict(sys.modules, stubs):
                with self.assertRaises(cw.HiddenUnavailable):
                    cw._read_remote('trakt', 'identity')
        finally:
            if saved is not None:
                sys.modules['session'] = saved
        self.assertEqual(len(calls), 1)     # the reader got as far as the request


if __name__ == '__main__':
    unittest.main()
