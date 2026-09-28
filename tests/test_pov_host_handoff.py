"""Restart recovery must never leave POV disabled after a confirmed swap."""

import importlib.util
import json
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / 'plugin.program.kodipovilwizard/resources/libs'


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class POVHostHandoffTests(unittest.TestCase):
    def test_settings_backup_is_local_and_restores_without_overwriting_original(self):
        migration = _load('qa_modular_host_migration_backup',
                          LIBS / 'modular_host_migration.py')
        resources = types.ModuleType('resources')
        libs = types.ModuleType('resources.libs')
        libs.modular_host_migration = migration
        patch_engine = types.ModuleType('resources.libs.patch_engine')
        patch_engine.PatchEngine = type('UnusedPatchEngine', (), {})
        with mock.patch.dict(sys.modules, {
                'resources': resources, 'resources.libs': libs,
                'resources.libs.modular_host_migration': migration,
                'resources.libs.patch_engine': patch_engine}):
            controller = _load('qa_pov_host_handoff_backup',
                               LIBS / 'pov_host_handoff.py')
        with tempfile.TemporaryDirectory() as raw:
            userdata = Path(raw)
            target = userdata / 'addon_data/plugin.video.pov/settings.xml'
            target.parent.mkdir(parents=True)
            target.write_text('original-private-settings', encoding='utf-8')
            controller._preserve_settings(userdata)
            backup = userdata / controller.SETTINGS_BACKUP
            self.assertEqual(backup.read_text(encoding='utf-8'),
                             'original-private-settings')
            target.write_text('new-settings', encoding='utf-8')
            controller._preserve_settings(userdata)
            self.assertEqual(backup.read_text(encoding='utf-8'),
                             'original-private-settings')
            controller._restore_settings(userdata)
            self.assertEqual(target.read_text(encoding='utf-8'),
                             'original-private-settings')

    def test_confirmed_swap_recovers_after_crash_before_reenable(self):
        migration = _load('qa_modular_host_migration',
                          LIBS / 'modular_host_migration.py')
        resources = types.ModuleType('resources')
        libs = types.ModuleType('resources.libs')
        libs.modular_host_migration = migration
        patch_engine = types.ModuleType('resources.libs.patch_engine')
        patch_engine.PatchEngine = type('UnusedPatchEngine', (), {})
        with mock.patch.dict(sys.modules, {
                'resources': resources, 'resources.libs': libs,
                'resources.libs.modular_host_migration': migration,
                'resources.libs.patch_engine': patch_engine}):
            controller = _load('qa_pov_host_handoff', LIBS / 'pov_host_handoff.py')

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            host = root / 'addons/plugin.video.pov'
            host.mkdir(parents=True)
            (host / 'addon.xml').write_text(
                '<addon id="plugin.video.pov" version="6.09.06"/>', encoding='utf-8')
            (host / 'new.py').write_text('working = True\n', encoding='utf-8')
            suffix = 'a' * 32
            migration._write_journal(root / migration.JOURNAL_NAME,
                                     'confirmed', suffix)
            userdata = root / 'userdata'
            userdata.mkdir()
            now = int(time.time())
            plan = {'schema': 1, 'addon_id': 'plugin.video.pov',
                    'version': '6.09.06', 'sha256': 'b' * 64,
                    'tree_digest': controller._digest_tree(host),
                    'stage_name': '.plugin.video.pov-stage-lost1234',
                    'creator_pid': -1, 'was_enabled': True,
                    'created': now, 'expires': now + 3600}
            (userdata / controller.PLAN_NAME).write_text(
                json.dumps(plan), encoding='utf-8')
            # A different addon can write an integration hook after the
            # immediately verified swap but before the next Kodi process.
            (host / 'new.py').write_text('working = True\nprivate_hook = True\n',
                                         encoding='utf-8')
            state = {'enabled': False, 'rescan': 0}

            def rpc(payload):
                request = json.loads(payload)
                if request['method'] == 'Addons.GetAddonDetails':
                    result = {'addon': {'enabled': state['enabled']}}
                else:
                    state['enabled'] = request['params']['enabled']
                    result = 'OK'
                return json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': result})

            xbmc = types.SimpleNamespace(
                executeJSONRPC=rpc,
                executebuiltin=lambda *_args: state.__setitem__(
                    'rescan', state['rescan'] + 1),
                getCondVisibility=lambda _query: False)
            xbmcaddon = types.SimpleNamespace(Addon=lambda _id: types.SimpleNamespace(
                getSetting=lambda _key: 'true'))
            with mock.patch.dict(sys.modules, {'xbmc': xbmc,
                                               'xbmcaddon': xbmcaddon}):
                self.assertTrue(controller.complete(host, userdata))
            self.assertTrue(state['enabled'])
            self.assertGreaterEqual(state['rescan'], 1)
            self.assertFalse((userdata / controller.PLAN_NAME).exists())


if __name__ == '__main__':
    unittest.main()
