"""A device without Umbrella: nothing looks for it (field report, 14 Nov 2026: "it keeps looking for
Umbrella at every start"). Kodi writes a red "Unknown addon id" line for every Addon() of an add-on that is
not installed, and the Umbrella steps of the startup pass and the per-minute keeper are work for nothing."""
import ast
import importlib.util
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ADDON = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai'
SERVICE = ADDON / 'service.py'
PROMPT = ADDON / 'resources/lib/umbrella_watch_prompt.py'


def _service(names, library):
    """The named top-level defs/assignments of service.py, run against a fake resources.lib."""
    tree = ast.parse(SERVICE.read_text('utf8'))
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name in names)
            or (isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in names for t in n.targets))]
    ns = {'threading': threading, '_skip_pov_patchers': lambda: False}
    exec(compile(ast.fix_missing_locations(ast.Module(body=keep, type_ignores=[])), str(SERVICE), 'exec'), ns)
    mods = {'resources': types.ModuleType('resources'), 'resources.lib': library}
    for k, v in vars(library).items():
        if not k.startswith('_'):
            mods['resources.lib.' + k] = v
    return ns, mods


def _library(installed):
    lib = types.ModuleType('resources.lib')
    lib.addon_presence = types.SimpleNamespace(installed=Mock(side_effect=lambda i: installed))
    lib.kodi_utils = types.SimpleNamespace(log=lambda *a, **k: None)
    for name in ('umbrella_language_patcher', 'umbrella_hebrew_ui_patcher', 'umbrella_setup_patcher',
                 'umbrella_subtitle_match_patcher', 'mdblist_umbrella_mirror', 'trakt_umbrella_mirror',
                 'umbrella_tmdb_apikey_patcher', 'umbrella_source_ux_patcher', 'umbrella_mdblist_token_patcher',
                 'umbrella_mdblist_sync_patcher', 'umbrella_watch_prompt', 'pov_seasons_view_seed',
                 'legacy_lang_mirror', 'kodi_playlist_timeout_patcher'):
        setattr(lib, name, Mock(name=name))
    return lib


def _umbrella_calls(lib):
    return [n for n in vars(lib) if n.startswith(('umbrella_', 'mdblist_umbrella', 'trakt_umbrella'))
            and getattr(lib, n).method_calls]


class StartupPass(unittest.TestCase):
    NAMES = ('UMBRELLA_ADDON_ID', '_umbrella_installed', '_maybe_patch_umbrella_language',
             '_maybe_patch_mdblist_reauth')

    def run_pass(self, installed):
        lib = _library(installed)
        ns, mods = _service(self.NAMES, lib)
        with patch.dict('sys.modules', mods):
            ns['_maybe_patch_umbrella_language']()
            ns['_maybe_patch_mdblist_reauth']()
        return lib

    def test_no_umbrella_step_runs_without_umbrella(self):
        lib = self.run_pass(False)
        self.assertEqual(_umbrella_calls(lib), [])
        lib.addon_presence.installed.assert_called_with('plugin.video.umbrella')

    def test_the_steps_that_are_not_umbrella_s_still_run_without_it(self):
        # review of 0.3.82: Kodi's own playlist timeout (the "playback failed" after backing out of a source
        # list) and Account Manager Lite's labels live in the same function, above the Umbrella gate
        lib = self.run_pass(False)
        self.assertTrue(lib.kodi_playlist_timeout_patcher.ensure_patched.called)
        lib.legacy_lang_mirror.mirror.assert_called_with('script.module.acctmgr')

    def test_with_umbrella_the_steps_run(self):
        lib = self.run_pass(True)
        called = _umbrella_calls(lib)
        for name in ('umbrella_language_patcher', 'umbrella_setup_patcher', 'mdblist_umbrella_mirror',
                     'umbrella_mdblist_token_patcher', 'umbrella_mdblist_sync_patcher'):
            self.assertIn(name, called)


class Keeper(unittest.TestCase):
    NAMES = ('UMBRELLA_ADDON_ID', '_umbrella_installed', '_start_service_mirror_keeper')

    def tick(self, installed):
        lib = _library(installed)
        ns, mods = _service(self.NAMES, lib)
        waits = []
        monitor = types.SimpleNamespace(abortRequested=lambda: False,
                                        waitForAbort=lambda s: waits.append(s) or len(waits) > 1)

        class Inline(object):
            def __init__(self, target, daemon=None):
                self.target = target

            def start(self):
                self.target()
        with patch.dict('sys.modules', mods), patch.object(threading, 'Thread', Inline):
            ns['_start_service_mirror_keeper'](monitor)
        self.assertEqual(waits, [90, 60])                  # one tick ran
        return lib

    def test_a_tick_without_umbrella_looks_for_nothing(self):
        lib = self.tick(False)
        self.assertEqual(_umbrella_calls(lib), [])
        self.assertTrue(lib.pov_seasons_view_seed.ensure_seeded.called)   # POV's part goes on

    def test_a_tick_with_umbrella_mirrors_and_asks(self):
        lib = self.tick(True)
        self.assertTrue(lib.mdblist_umbrella_mirror.mirror.called)
        self.assertTrue(lib.trakt_umbrella_mirror.mirror.called)
        self.assertTrue(lib.umbrella_watch_prompt.maybe_ask_async.called)


class WatchPrompt(unittest.TestCase):
    def test_no_addon_lookup_without_umbrella(self):
        spec = importlib.util.spec_from_file_location('umbrella_watch_prompt_fixture', PROMPT)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        built = []
        m.xbmcaddon = types.SimpleNamespace(Addon=lambda i: built.append(i))
        m.kodi_utils = types.SimpleNamespace(get_setting=lambda *a: '', set_setting=lambda *a: None,
                                             log=lambda *a, **k: None)
        m.xbmc = types.SimpleNamespace(Player=lambda: types.SimpleNamespace(isPlayingVideo=lambda: False))
        m.ws = types.SimpleNamespace()
        m.addon_settings_safe = types.SimpleNamespace()
        m.xbmcgui = types.SimpleNamespace()
        m.addon_presence = types.SimpleNamespace(installed=lambda i: False)
        self.assertEqual(m.maybe_ask(), 'not_installed')
        self.assertEqual(built, [])


if __name__ == '__main__':
    unittest.main()
