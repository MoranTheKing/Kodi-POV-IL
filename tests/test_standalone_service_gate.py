"""MoranSubs' service.py serves both editions (Oct 2026).

The repo-channel ("standalone") add-on had its own slim service, frozen with
the old 0.2.x tree. It now ships the same service.py as the build, so every
step that touches POV, Umbrella, a skin's buttons and settings or the build's
own state must run on a Kodi POV IL build only, and a clean Kodi gets the
subtitle service alone (plus the two one-shots the old slim service had).
"""
import ast
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / 'service.subtitles.kodipovilai' / 'service.py'

BUILD_ONLY = {
    '_start_he_warm_drainer', '_ensure_pov_enabled', 'wait_for_home_rows',
    '_ensure_build_marker', '_maybe_force_pool_share', '_maybe_patch_hub_search',
    '_maybe_default_fentastic_player', '_point_subtitle_button',
    '_maybe_patch_af3_dialog_subtitles', '_maybe_patch_nox_change_source',
    '_maybe_patch_nox_osd_collision', '_maybe_patch_nox_next_episode',
    '_maybe_default_nox_poster_rating', '_maybe_patch_estuary_change_source',
    '_maybe_patch_fentastic_simpleplayer_source', '_maybe_patch_choose_subs_buttons',
    '_maybe_patch_change_source_pause', '_run_build_startup_repairs',
    '_maybe_unpatch_fentastic_notification', '_maybe_default_pool_on',
    '_maybe_enable_osd_autoclose', '_maybe_default_pov_autoplay',
    '_maybe_revert_pov_autoplay', '_maybe_revert_pov_always_resume',
    '_start_service_mirror_keeper',
    # The build switched Ktuvit off during its outage; the standalone never did.
    '_maybe_reenable_ktuvit',
}
STANDALONE_ONLY = {'_maybe_purge_temp_once', '_maybe_seed_hebrew_subtitle_prefs',
                   # the build runs _maybe_refresh_shared_sdh in its startup repairs
                   '_start_shared_sdh_refresh'}
# DarkSubs integration, both editions (the old slim service ran it too), only
# while DarkSubs is active.
DARKSUBS = {
    '_maybe_patch_darksubs', '_maybe_patch_darksubs_download_sub',
    '_maybe_patch_darksubs_opensubtitles', '_maybe_patch_darksubs_embedded_demote',
    '_maybe_patch_darksubs_embedded_insert', '_maybe_patch_darksubs_subwindow_demote',
    '_maybe_surface_darksubs_status', '_maybe_patch_darksubs_filename',
    '_maybe_patch_darksubs_picker_label', '_maybe_patch_darksubs_picker_height',
    '_maybe_patch_all_subs_samefile',
}
SUBTITLE_SERVICE = {
    '_start_subsync_drainer', '_start_subsync_delay_watch', '_prune_once',
    '_prune_source_memory_once', '_maybe_default_builtin_engine',
    '_ensure_darksubs_enabled', '_maybe_set_default_subtitle_service', '_maybe_prewarm_engine',
    '_maybe_patch_skin_dialog_subtitles', '_maybe_patch_skin_dialog_subtitles_rows',
    '_maybe_repair_rtl_cache', '_maybe_default_fast_first_chunk',
    '_maybe_migrate_embedded_translation_mode', '_maybe_force_gender_ref_arabic',
    '_maybe_tune_gemini3_defaults', '_maybe_bump_gemini_model',
    '_maybe_bump_gemini_model_38', '_maybe_lower_chunk_lines',
    '_maybe_start_autosub_player', '_start_pool_queue_drainer',
}


def load_service():
    spec = importlib.util.spec_from_file_location('ms_service_gate', SERVICE)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'xbmc': None}):   # import xbmc fails: main() returns at once
        spec.loader.exec_module(module)
    return module


def main_calls():
    tree = ast.parse(SERVICE.read_text(encoding='utf-8'))
    main = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main'][0]
    return {n.func.id for n in ast.walk(main) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


class ServiceGate(unittest.TestCase):
    def run_main(self, build):
        service = load_service()
        called = []
        names = main_calls() - {'_is_kodi_pov_il_build', '_check_first_run_marker'}
        for name in names:
            if hasattr(service, name) and callable(getattr(service, name)):
                setattr(service, name, (lambda n: lambda *a, **k: called.append(n))(name))
        service._is_kodi_pov_il_build = lambda: build
        service._check_first_run_marker = lambda: False
        monitor = types.SimpleNamespace(abortRequested=lambda: False, waitForAbort=lambda s=0: True)
        service.xbmc = types.SimpleNamespace(Monitor=lambda: monitor, LOGINFO=1, LOGWARNING=2)
        reloads = []
        fake = lambda name: types.SimpleNamespace(reload_if_patched=lambda: reloads.append(name),
                                                  reload_if_repaired=lambda: reloads.append(name))
        lib = types.ModuleType('resources.lib')
        for mod in ('pov_reload', 'source_settings_reload', 'darksubs_reload', 'kodi_utils'):
            setattr(lib, mod, fake(mod))
        lib.kodi_utils = types.SimpleNamespace(get_bool=lambda k, d=False: False, log=lambda *a, **k: None)
        mods = {'resources': types.ModuleType('resources'), 'resources.lib': lib}
        for mod in ('pov_reload', 'source_settings_reload', 'darksubs_reload', 'kodi_utils'):
            mods['resources.lib.' + mod] = getattr(lib, mod)
        with patch.dict(sys.modules, mods):
            service.main()
        return set(called), reloads

    def test_without_the_build_only_the_subtitle_service_runs(self):
        called, reloads = self.run_main(build=False)
        self.assertEqual(called & BUILD_ONLY, set())
        self.assertEqual(SUBTITLE_SERVICE - called, set())
        self.assertEqual(STANDALONE_ONLY - called, set())
        self.assertEqual(DARKSUBS - called, set())          # DarkSubs active in this run
        self.assertNotIn('pov_reload', reloads)
        self.assertNotIn('source_settings_reload', reloads)

    def test_the_build_still_runs_everything(self):
        called, reloads = self.run_main(build=True)
        self.assertEqual(BUILD_ONLY - called, set())
        self.assertEqual(SUBTITLE_SERVICE - called, set())
        self.assertEqual(called & STANDALONE_ONLY, set())
        self.assertEqual(reloads.count('pov_reload'), 2)
        self.assertIn('source_settings_reload', reloads)

    def test_every_step_is_classified(self):
        # A new step in main() must be put in one of the three sets.
        steps = {n for n in main_calls() if n.startswith('_') or n == 'wait_for_home_rows'}
        unclassified = steps - BUILD_ONLY - STANDALONE_ONLY - SUBTITLE_SERVICE - DARKSUBS - {
            '_is_kodi_pov_il_build', '_check_first_run_marker'}
        self.assertEqual(unclassified, set())

    def test_shared_sdh_refresh_reaches_both_editions(self):
        # main() can't see the steps inside _run_build_startup_repairs (build
        # only); the subtitle one among them needs its own standalone path.
        tree = ast.parse(SERVICE.read_text(encoding='utf-8'))
        fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        refs = lambda fn: {n.id for n in ast.walk(fns[fn]) if isinstance(n, ast.Name)}
        self.assertIn('_maybe_refresh_shared_sdh', refs('_run_build_startup_repairs'))
        self.assertIn('_maybe_refresh_shared_sdh', refs('_start_shared_sdh_refresh'))

        service = load_service()
        ran = []
        service._maybe_refresh_shared_sdh = lambda: ran.append(True)
        service._background_settle_seconds = lambda: 0
        threads = []
        with patch.object(service.threading, 'Thread',
                          lambda target, daemon: types.SimpleNamespace(start=lambda: threads.append(target))):
            service._start_shared_sdh_refresh(types.SimpleNamespace(waitForAbort=lambda s: False))
        self.assertEqual(len(threads), 1)      # off the main thread
        threads[0]()
        self.assertEqual(ran, [True])
        aborted = []
        with patch.object(service.threading, 'Thread',
                          lambda target, daemon: types.SimpleNamespace(start=lambda: aborted.append(target))):
            service._start_shared_sdh_refresh(types.SimpleNamespace(waitForAbort=lambda s: True))
        aborted[0]()
        self.assertEqual(ran, [True])          # Kodi stopping during the settle: no fetch

    def test_the_markers_are_declared(self):
        settings = (SERVICE.parent / 'resources' / 'settings.xml').read_text(encoding='utf-8')
        for marker in ('_he_subs_prefs_v1', '_temp_purge_done'):
            self.assertIn('<setting id="%s"' % marker, settings)


if __name__ == '__main__':
    unittest.main()
