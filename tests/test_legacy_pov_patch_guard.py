"""Guard old POV trees and keep the clean-host AIOStreams hook compatible."""

import ast
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ENGINE = (Path(__file__).resolve().parents[1]
          / 'plugin.program.kodipovilwizard/resources/libs/patch_engine.py')
CONFIG = ENGINE.parent / 'patches/patches_config.py'


class LegacyPovPatchGuardTests(unittest.TestCase):
    def _engine(self, addon_root):
        xbmc = types.ModuleType('xbmc')
        xbmc.LOGDEBUG, xbmc.LOGINFO, xbmc.LOGWARNING, xbmc.LOGERROR = range(4)
        xbmcaddon = types.ModuleType('xbmcaddon')
        xbmcaddon.Addon = lambda: types.SimpleNamespace(getSetting=lambda _key: '')
        xbmcvfs = types.ModuleType('xbmcvfs')
        prefix = 'special://home/addons/plugin.video.pov'
        xbmcvfs.translatePath = lambda value: (
            str(addon_root) + value[len(prefix):]
            if value.startswith(prefix) else value)
        resources = types.ModuleType('resources')
        libs = types.ModuleType('resources.libs')
        common = types.ModuleType('resources.libs.common')
        logging = types.ModuleType('resources.libs.common.logging')
        logging.log = lambda *_args, **_kwargs: None
        common.logging = logging
        modules = {'xbmc': xbmc, 'xbmcaddon': xbmcaddon, 'xbmcvfs': xbmcvfs,
                   'resources': resources, 'resources.libs': libs,
                   'resources.libs.common': common,
                   'resources.libs.common.logging': logging}
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location('legacy_guard_engine', ENGINE)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        return module

    def test_old_marker_prevents_partial_writes_across_files(self):
        with tempfile.TemporaryDirectory() as raw:
            addon = Path(raw) / 'plugin.video.pov'
            addon.mkdir()
            legacy = addon / 'legacy.py'
            clean = addon / 'clean.py'
            legacy.write_text('ANCHOR\n# AI_SUBS_AUTOPICK_v7\n', encoding='utf-8')
            clean.write_text('ANCHOR\n', encoding='utf-8')
            original = (legacy.read_bytes(), clean.read_bytes())
            module = self._engine(addon)
            config = [dict(id=name, name=name, addon_id='plugin.video.pov',
                           target_file=target, marker='NEW_V1', anchor='ANCHOR',
                           action='append_after', hook='pass', enabled=True)
                      for name, target in (('one', 'clean.py'), ('two', 'legacy.py'))]
            # The clean file is first, so this proves the guard runs before
            # processing *any* target, rather than skipping one bad patch.
            with patch.dict(sys.modules, {
                    'xbmc': module.xbmc, 'xbmcaddon': module.xbmcaddon,
                    'xbmcvfs': module.xbmcvfs,
                    'resources.libs.common.logging': module.logging}):
                stats = module.PatchEngine(config).run()
            self.assertEqual(stats['legacy_host_deferred'], 1)
            self.assertEqual((legacy.read_bytes(), clean.read_bytes()), original)

    def test_clean_host_still_accepts_patch(self):
        with tempfile.TemporaryDirectory() as raw:
            addon = Path(raw) / 'plugin.video.pov'
            addon.mkdir()
            target = addon / 'clean.py'
            target.write_text('ANCHOR\n', encoding='utf-8')
            module = self._engine(addon)
            config = [dict(id='one', name='one', addon_id='plugin.video.pov',
                           target_file='clean.py', marker='NEW_V1', anchor='ANCHOR',
                           action='append_after', hook='pass', enabled=True)]
            with patch.dict(sys.modules, {
                    'xbmc': module.xbmc, 'xbmcaddon': module.xbmcaddon,
                    'xbmcvfs': module.xbmcvfs,
                    'resources.libs.common.logging': module.logging}):
                stats = module.PatchEngine(config).run()
            self.assertEqual(stats['applied'], 1)
            self.assertIn('NEW_V1', target.read_text(encoding='utf-8'))

    def test_new_host_alternative_upgrades_and_then_is_idempotent(self):
        with tempfile.TemporaryDirectory() as raw:
            module = self._engine(Path(raw))
            entry=dict(id='sample',name='sample',target_file='sample.py',
                       marker='HOOK_V2',anchor='OLD_ANCHOR',action='append_after',
                       enabled=True,hook='old_call()',alternatives=[
                           {'anchor':'NEW_ANCHOR','hook':'new_call()'}])
            engine=module.PatchEngine([])
            source='# NEW_ANCHOR\n'
            changed,_,status=engine._apply_single_patch(source,entry,'\n')
            self.assertEqual(status,'applied')
            self.assertIn('new_call()',changed)
            self.assertNotIn('old_call()',changed)
            self.assertEqual(engine._apply_single_patch(changed,entry,'\n'),
                             (changed,False,'skipped_current'))

    def test_superseded_shape_removes_obsolete_hook_without_faking_application(self):
        with tempfile.TemporaryDirectory() as raw:
            module = self._engine(Path(raw))
            engine=module.PatchEngine([])
            entry=dict(id='sample',name='sample',target_file='sample.py',
                       marker='HOOK_V1',anchor='# OLD',action='append_after',
                       enabled=True,hook='legacy_call()')
            source=engine._apply_single_patch('# OLD\n',entry,'\n')[0]
            source=source.replace('# OLD','# NEW')
            entry.update(marker='HOOK_V2',alternatives=[{'anchor':'# NEW','superseded':True}])
            changed,_,status=engine._apply_single_patch(source,entry,'\n')
            self.assertEqual((changed,status),('# NEW\n','superseded'))

    def test_hook_cannot_supply_its_own_upgraded_anchor(self):
        with tempfile.TemporaryDirectory() as raw:
            module=self._engine(Path(raw)); engine=module.PatchEngine([])
            entry=dict(id='sample',name='sample',target_file='sample.py',marker='HOOK_V1',
                       anchor='# OLD',action='append_after',enabled=True,hook='# NEW\npass')
            source=engine._apply_single_patch('# OLD\n',entry,'\n')[0]
            entry.update(marker='HOOK_V2',anchor='# NEW')
            self.assertEqual(engine._apply_single_patch(source,entry,'\n'),
                             (source,False,'anchor_missing'))

    def test_invalid_python_is_not_written(self):
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);target=root/'host.py';target.write_text('anchor = 1\n')
            module=self._engine(root)
            class Engine(module.PatchEngine):
                @staticmethod
                def _resolve_paths(addon_id,relative):return str(root),str(root/relative)
            entry=dict(id='sample',name='sample',target_file='host.py',marker='HOOK_V1',
                       anchor='anchor = 1',action='append_after',enabled=True,hook='if :',addon_id='plugin.video.pov')
            stats=Engine([entry]).run()
            self.assertGreater(stats['failed'],0)
            self.assertEqual(target.read_text(),'anchor = 1\n')

    def test_aiostreams_hook_survives_directsync_settings_variant(self):
        config_tree = ast.parse(CONFIG.read_text(encoding='utf-8'))
        assignment = next(node for node in config_tree.body
                          if isinstance(node, ast.Assign) and any(
                              isinstance(target, ast.Name) and target.id == 'PATCH_CONFIG'
                              for target in node.targets))
        item = next(item for item in ast.literal_eval(assignment.value)
                    if item['id'] == 'pov_aiostreams_credentials_fix')
        source = (
            "def active_internal_scrapers():\n"
            "\tif get_setting('provider.aiostreams') == 'true': "
            "settings = ['provider.aiostreams']\n"
            "\telse: settings = ['provider.external', 'provider.easynews']\n"
            "\tsettings.extend(item[1] for item in (('pm', 'provider.pm_cloud'),))\n"
            "\treturn settings\n")
        directsync = source.replace(
            "else: settings = ['provider.external', 'provider.easynews']",
            "else: settings = ['provider.external', 'provider.easynews', 'provider.directsync']")
        with tempfile.TemporaryDirectory() as raw:
            module = self._engine(Path(raw) / 'plugin.video.pov')
            for variant in (source, directsync):
                changed, did_change, status = module.PatchEngine([])._apply_single_patch(
                    variant, item, '\n')
                self.assertTrue(did_change)
                self.assertEqual(status, 'applied')
                ast.parse(changed)
                self.assertIn(item['marker'], changed)
                self.assertIn('settings = pov_aiostreams_fix.enforce_credentials(settings)',
                              changed)
                if variant is directsync:
                    self.assertIn('provider.directsync', changed)


if __name__ == '__main__':
    unittest.main()
