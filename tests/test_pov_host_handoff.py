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

    def test_settings_copies_survive_refused_metadata_and_a_stale_temp(self):
        # Field log, 23 Oct 2026 (Android TV 12): shutil.copy2 raised
        # "[Errno 13] Permission denied" on the temp file -- it also copies
        # metadata (mode, times, xattrs) that Android's emulated storage can
        # refuse -- and the migration stopped there. Every metadata-copying
        # helper is made to fail here; the stale read-only temp is hardening.
        migration = _load('qa_modular_host_migration_android',
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
            controller = _load('qa_pov_host_handoff_android',
                               LIBS / 'pov_host_handoff.py')

        def denied(*_args, **_kwargs):
            raise PermissionError(13, 'Permission denied')
        with tempfile.TemporaryDirectory() as raw:
            userdata = Path(raw)
            target = userdata / 'addon_data/plugin.video.pov/settings.xml'
            target.parent.mkdir(parents=True)
            target.write_text('original-private-settings', encoding='utf-8')
            backup = userdata / controller.SETTINGS_BACKUP
            backup.parent.mkdir(parents=True)
            stale = backup.with_name(backup.name + '.tmp')
            stale.write_text('half-written', encoding='utf-8')
            stale.chmod(0o444)                  # left read-only by an interrupted run
            with mock.patch.object(controller.shutil, 'copy2', denied), \
                    mock.patch.object(controller.shutil, 'copy', denied), \
                    mock.patch.object(controller.shutil, 'copystat', denied), \
                    mock.patch.object(controller.shutil, 'copymode', denied):
                controller._preserve_settings(userdata)
                self.assertEqual(backup.read_text(encoding='utf-8'), 'original-private-settings')
                self.assertFalse(stale.exists())
                target.write_text('new-settings', encoding='utf-8')
                controller._restore_settings(userdata)
            self.assertEqual(target.read_text(encoding='utf-8'), 'original-private-settings')

    def _prepare_fixture(self, raw, name):
        migration = _load('qa_modular_host_migration_' + name,
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
            controller = _load('qa_pov_host_handoff_' + name,
                               LIBS / 'pov_host_handoff.py')
        root = Path(raw)
        host = root / 'addons/plugin.video.pov'
        host.mkdir(parents=True)
        userdata = root / 'userdata'
        (userdata / 'addon_data/plugin.video.pov').mkdir(parents=True)
        (userdata / 'addon_data/plugin.video.pov/settings.xml').write_text(
            'private', encoding='utf-8')
        service = root / 'modular_service_handoff.py'
        service.write_text('', encoding='utf-8')

        def stage_clean_host(_archive, _host, _sha, version, _check):
            stage = Path(tempfile.mkdtemp(prefix=migration.STAGE_PREFIX,
                                          dir=str(root))) / 'plugin.video.pov'
            stage.mkdir()
            (stage / 'addon.xml').write_text(
                '<addon id="plugin.video.pov" version="{}"/>'.format(version),
                encoding='utf-8')
            return stage

        def orphan(name):
            tree = root / (migration.STAGE_PREFIX + name) / 'plugin.video.pov'
            tree.mkdir(parents=True)
            (tree / 'addon.xml').write_text('old', encoding='utf-8')
            return tree.parent

        settings = {}
        xbmc = types.SimpleNamespace(executeJSONRPC=lambda _payload: json.dumps(
            {'jsonrpc': '2.0', 'id': 1, 'result': {'addon': {'enabled': True}}}))
        xbmcaddon = types.SimpleNamespace(Addon=lambda _id: types.SimpleNamespace(
            setSetting=settings.__setitem__,
            getSetting=lambda key: settings.get(key, '')))
        modules = mock.patch.dict(sys.modules, {'xbmc': xbmc, 'xbmcaddon': xbmcaddon})
        patches = [modules,
                   mock.patch.object(migration, 'stage_clean_host', stage_clean_host),
                   mock.patch.object(controller, '_patched_stage', lambda _stage: {})]
        return controller, migration, root, host, userdata, service, orphan, patches

    def _stages(self, root, migration):
        return sorted(path.name for path in root.glob(migration.STAGE_PREFIX + '*'))

    def test_failed_prepare_removes_its_stage_and_earlier_leftovers(self):
        # The field box staged a full POV tree on each attempt and then failed
        # at the settings backup, so the trees piled up beside addons/.
        with tempfile.TemporaryDirectory() as raw:
            (controller, migration, root, host, userdata, service, orphan,
             patches) = self._prepare_fixture(raw, 'prepare_fail')
            orphan('left1')
            orphan('left2')
            unrelated = root / (migration.BACKUP_PREFIX + 'a' * 32)
            unrelated.mkdir()
            # Named like a stage but not a folder: never ours to delete.
            stray = root / (migration.STAGE_PREFIX + 'file')
            stray.write_text('not a stage', encoding='utf-8')

            def denied(_userdata):
                raise PermissionError(13, 'Permission denied')
            with patches[0], patches[1], patches[2], \
                    mock.patch.object(controller, '_preserve_settings', denied):
                with self.assertRaises(PermissionError):
                    controller.prepare(root / 'pov.zip', host, userdata,
                                       '6.10.21', 'c' * 64, service)
            self.assertEqual(self._stages(root, migration), [stray.name])
            self.assertTrue(unrelated.is_dir())
            self.assertFalse((userdata / controller.PLAN_NAME).exists())

    def test_prepare_keeps_only_the_planned_stage(self):
        with tempfile.TemporaryDirectory() as raw:
            (controller, migration, root, host, userdata, service, orphan,
             patches) = self._prepare_fixture(raw, 'prepare_keep')
            with patches[0], patches[1], patches[2]:
                first = controller.prepare(root / 'pov.zip', host, userdata,
                                           '6.10.20', 'c' * 64, service)
                orphan('left1')
                self.assertEqual(len(self._stages(root, migration)), 2)
                # Same version, intact stage: the plan is reused, the
                # leftover is swept and the planned stage stays.
                again = controller.prepare(root / 'pov.zip', host, userdata,
                                           '6.10.20', 'c' * 64, service)
                self.assertEqual(again['stage'], first['stage'])
                self.assertEqual(self._stages(root, migration),
                                 [first['stage'].parent.name])
                # A newer pin replaces the plan; the old stage goes with it.
                newer = controller.prepare(root / 'pov.zip', host, userdata,
                                           '6.10.21', 'd' * 64, service)
            self.assertEqual(self._stages(root, migration),
                             [newer['stage'].parent.name])
            self.assertNotEqual(newer['stage'], first['stage'])
            plan = controller.read_plan(userdata, host)
            self.assertEqual(plan['stage'], newer['stage'])
            self.assertEqual(plan['version'], '6.10.21')
            self.assertTrue((userdata / controller.SETTINGS_BACKUP).is_file())

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
