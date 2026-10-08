"""Guard critical startup paths while POV patch ownership moves to Wizard."""

import ast
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / 'service.subtitles.kodipovilai/service.py'
WIZARD = ROOT / 'plugin.program.kodipovilwizard'
CONFIG = WIZARD / 'resources/libs/patches/patches_config.py'


def _main_calls():
    tree = ast.parse(SERVICE.read_text('utf-8-sig'))
    main = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == 'main')
    return {node.func.id for node in ast.walk(main)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}


class StartupParityTests(unittest.TestCase):
    def test_direct_external_addon_repairs_are_wired_and_packaged(self):
        required = {
            '_maybe_patch_darksubs', '_maybe_patch_darksubs_download_sub',
            '_maybe_patch_darksubs_opensubtitles',
            '_maybe_patch_darksubs_embedded_demote',
            '_maybe_patch_darksubs_embedded_insert',
            '_maybe_patch_darksubs_subwindow_demote',
            '_maybe_patch_darksubs_filename',
            '_maybe_patch_darksubs_picker_height',
            '_maybe_patch_darksubs_picker_label',
            '_maybe_surface_darksubs_status',
            '_maybe_patch_all_subs_samefile',
            '_maybe_patch_estuary_change_source',
            '_maybe_patch_fentastic_simpleplayer_source',
            '_maybe_unpatch_fentastic_notification',
        }
        self.assertFalse(required - _main_calls())
        for module in (
                'darksubs_embedded_demote_patcher',
                'darksubs_subwindow_demote_patcher',
                'darksubs_filename_fallback_patcher',
                'darksubs_picker_height_patcher',
                'darksubs_picker_label_patcher',
                'all_subs_samefile_patcher',
                'estuary_change_source_patcher',
                'fentastic_simpleplayer_source_patcher'):
            self.assertTrue((ROOT / 'service.subtitles.kodipovilai'
                             / 'resources/lib' / (module + '.py')).is_file(), module)

    def test_wizard_owns_three_removed_pov_service_patchers(self):
        # The Wizard startup actually invokes the patch engine on each boot.
        startup = (WIZARD / 'startup.py').read_text('utf-8')
        self.assertIn('PatchEngine().run_if_changed()', startup)
        spec = importlib.util.spec_from_file_location('candidate_patches', CONFIG)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        by_id = {item['id']: item for item in module.PATCH_CONFIG}
        expected = {
            'pov_debrid_unbound_guard': ('resources/lib/modules/debrid.py',
                                        'files =', 'torrent_id ='),
            'pov_playback_capture': ('resources/lib/modules/sources.py',
                                     'pov_source_remember.run_capture',),
            'pov_reorder_sources': ('resources/lib/modules/sources.py',
                                    'pov_source_remember.run_reorder',),
            'pov_subtitle_match_percent': ('resources/lib/windows/sources.py',
                                           'pov_sub_match_v2.run',),
        }
        for patch_id, (target, *needles) in expected.items():
            item = by_id[patch_id]
            self.assertTrue(item['enabled'], patch_id)
            self.assertEqual(item['target_file'], target)
            self.assertTrue(item['anchor'])
            self.assertTrue(item['marker'])
            for needle in needles:
                self.assertIn(needle, item['hook'], patch_id)


if __name__ == '__main__':
    unittest.main()
