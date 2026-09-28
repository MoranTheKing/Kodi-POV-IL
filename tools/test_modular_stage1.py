"""Filesystem rehearsal for the old-service Wizard bootstrap and bridge ZIP."""

import ast
import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from build_modular_stage1 import build, REQUEST_MEMBER, STAGED_MEMBER


ROOT = Path(__file__).resolve().parents[1]
HELPER = (ROOT / 'addons/service.subtitles.kodipovilai/resources/lib'
          / 'modular_legacy_bootstrap.py')
spec = importlib.util.spec_from_file_location('modular_bootstrap_test', HELPER)
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def candidate_zip(path, version='0.4.3', extra=None):
    entries = {
        'addon.xml': '<addon id="plugin.program.kodipovilwizard" version="{}"/>'.format(version),
        'startup.py': 'print("modular startup")\n',
        'resources/libs/wizard.py': 'class Wizard: pass\n',
        'resources/libs/modular_updater.py': 'class ModularUpdater: pass\n',
    }
    if extra:
        entries.update(extra)
    with zipfile.ZipFile(path, 'w') as bundle:
        for name, data in entries.items():
            bundle.writestr('plugin.program.kodipovilwizard/' + name, data)
    return bootstrap._sha256(path)


class ModularStage1Tests(unittest.TestCase):
    def test_pov_addon_window_respects_clean_host_switch(self):
        source = (ROOT / 'addons/service.subtitles.kodipovilai/service.py').read_text(
            encoding='utf-8')
        tree = ast.parse(source)
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef)
                        and node.name == '_maybe_patch_pov_addon_window')
        namespace = {'_skip_pov_patchers': lambda: True}
        exec(compile(ast.Module(body=[function], type_ignores=[]),
                     '<pov-addon-window-guard>', 'exec'), namespace)
        with mock.patch.dict(sys.modules, {'resources': None}):
            self.assertIsNone(namespace['_maybe_patch_pov_addon_window']())

    def test_path_scope_rejects_parent_escape(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / 'addons'
            root.mkdir()
            self.assertTrue(bootstrap._inside(root / 'wizard/addon.xml', root))
            self.assertFalse(bootstrap._inside(root / '../outside', root))

    def test_install_keeps_old_wizard_and_second_run_is_idempotent(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            addons = root / 'addons'
            addons.mkdir()
            live = addons / bootstrap.WIZARD_ID
            live.mkdir()
            (live / 'old-only.txt').write_text('user old Wizard', encoding='utf-8')
            archive = root / 'candidate.zip'
            digest = candidate_zip(archive)
            result, backup = bootstrap.install_staged_wizard(
                archive, digest, '0.4.3', addons)
            self.assertEqual(result, 'installed')
            self.assertTrue(Path(backup, 'old-only.txt').is_file())
            self.assertIn('modular startup', (live / 'startup.py').read_text())
            result, second_backup = bootstrap.install_staged_wizard(
                archive, digest, '0.4.3', addons)
            self.assertEqual((result, second_backup), ('already_installed', backup))
            self.assertTrue(Path(backup, 'old-only.txt').is_file())

    def test_interrupted_swap_restores_old_wizard_before_retry(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            addons = root / 'addons'
            addons.mkdir()
            rollback = addons / bootstrap.ROLLBACK
            rollback.mkdir()
            (rollback / 'addon.xml').write_text(
                '<addon id="plugin.program.kodipovilwizard" version="0.1.48"/>',
                encoding='utf-8')
            (rollback / 'old-only.txt').write_text('keep', encoding='utf-8')
            self.assertTrue(bootstrap._restore_interrupted_swap(addons))
            live = addons / bootstrap.WIZARD_ID
            self.assertEqual((live / 'old-only.txt').read_text(), 'keep')
            self.assertFalse(rollback.exists())

    def test_unrecognised_rollback_tree_is_never_promoted(self):
        with tempfile.TemporaryDirectory() as raw:
            addons = Path(raw) / 'addons'
            addons.mkdir()
            rollback = addons / bootstrap.ROLLBACK
            rollback.mkdir()
            (rollback / 'addon.xml').write_text(
                '<addon id="other.addon" version="1"/>', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                bootstrap._restore_interrupted_swap(addons)
            self.assertFalse((addons / bootstrap.WIZARD_ID).exists())

    def test_invalid_archive_never_changes_existing_wizard(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            addons = root / 'addons'
            live = addons / bootstrap.WIZARD_ID
            live.mkdir(parents=True)
            old = live / 'startup.py'
            old.write_bytes(b'old')
            archive = root / 'candidate.zip'
            digest = candidate_zip(archive)
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                bootstrap.install_staged_wizard(archive, '0' * 64,
                                                '0.4.3', addons)
            self.assertEqual(old.read_bytes(), b'old')
            with zipfile.ZipFile(archive, 'a') as bundle:
                bundle.writestr('plugin.program.kodipovilwizard/../escape', 'bad')
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                bootstrap.install_staged_wizard(
                    archive, bootstrap._sha256(archive), '0.4.3', addons)
            self.assertEqual(old.read_bytes(), b'old')

    def test_failed_second_rename_restores_old_wizard(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            addons = root / 'addons'
            live = addons / bootstrap.WIZARD_ID
            live.mkdir(parents=True)
            (live / 'old-only.txt').write_text('keep', encoding='utf-8')
            archive = root / 'candidate.zip'
            digest = candidate_zip(archive)
            original = bootstrap.os.replace
            calls = []

            def fail_second(source, target):
                calls.append((source, target))
                if len(calls) == 2:
                    raise OSError('simulated rename failure')
                return original(source, target)

            with mock.patch.object(bootstrap.os, 'replace', side_effect=fail_second):
                with self.assertRaisesRegex(OSError, 'simulated'):
                    bootstrap.install_staged_wizard(archive, digest,
                                                    '0.4.3', addons)
            self.assertEqual((live / 'old-only.txt').read_text(), 'keep')

    def test_bridge_contains_only_public_service_and_private_transition_marker(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            service = root / 'service.subtitles.kodipovilai'
            helper = service / 'resources/lib'
            helper.mkdir(parents=True)
            (service / 'addon.xml').write_text(
                '<addon id="service.subtitles.kodipovilai" version="0.2.566"/>',
                encoding='utf-8')
            (helper / 'modular_legacy_bootstrap.py').write_text('pass\n')
            (helper / 'wizard_self_healer.py').write_text(
                'from . import modular_legacy_bootstrap\n')
            archive = root / 'wizard.zip'
            digest = candidate_zip(archive)
            output = root / 'stage1.zip'
            result = build(service, archive, output)
            self.assertEqual(result['wizard_sha256'], digest)
            with zipfile.ZipFile(output) as bundle:
                plan = json.loads(bundle.read(REQUEST_MEMBER))
                self.assertEqual(plan, {'sha256': digest, 'version': '0.4.3'})
                self.assertEqual(bundle.read(STAGED_MEMBER), archive.read_bytes())
                self.assertFalse(any(name.startswith('addons/plugin.program.')
                                     for name in bundle.namelist()))

    def test_requested_bootstrap_commits_ready_marker_and_blocks_old_healer(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            userdata = root / 'userdata'
            addons = root / 'addons'
            userdata.mkdir()
            service = addons / bootstrap.SERVICE_ID / 'resources'
            service.mkdir(parents=True)
            wizard = addons / bootstrap.WIZARD_ID
            wizard.mkdir()
            (wizard / 'old.py').write_text('old', encoding='utf-8')
            archive = service / 'modular_wizard_stage1.zip'
            digest = candidate_zip(archive)
            (userdata / bootstrap.REQUEST).write_text(json.dumps({
                'sha256': digest, 'version': '0.4.3'}), encoding='utf-8')

            class Vfs:
                @staticmethod
                def translatePath(value):
                    return str(root / value.removeprefix('special://home/'))

            class AddonApi:
                @staticmethod
                def Addon(_id):
                    return object()

            class Kodi:
                @staticmethod
                def getCondVisibility(_value):
                    return False

            class Dialog:
                def notification(self, *_args, **_kwargs):
                    return None

            Gui = type('Gui', (), {'Dialog': Dialog})

            pid = [100]
            with (mock.patch.object(bootstrap, 'xbmcvfs', Vfs),
                  mock.patch.object(bootstrap, 'xbmcaddon', AddonApi),
                  mock.patch.object(bootstrap, 'xbmc', Kodi),
                  mock.patch.object(bootstrap, 'xbmcgui', Gui),
                  mock.patch.object(bootstrap.os, 'getpid', side_effect=lambda: pid[0])):
                self.assertEqual(bootstrap.ensure_bootstrapped(),
                                 'deferred_restart')
                self.assertTrue((wizard / 'old.py').is_file())
                self.assertEqual(bootstrap.ensure_bootstrapped(),
                                 'deferred_restart')
                pid[0] = 200
                self.assertEqual(bootstrap.ensure_bootstrapped(), 'installed')
                self.assertFalse((userdata / bootstrap.REQUEST).exists())
                self.assertTrue((userdata / bootstrap.READY).is_file())
                self.assertTrue((addons / bootstrap.ROLLBACK).is_dir())
                self.assertEqual(bootstrap.ensure_bootstrapped(), 'ready')
                # A local edit after installation cannot cause the old
                # service to overwrite the user's modular Wizard.
                (wizard / 'startup.py').write_text('local edit', encoding='utf-8')
                self.assertEqual(bootstrap.ensure_bootstrapped(), 'ready')
                self.assertEqual((wizard / 'startup.py').read_text(), 'local edit')
            self.assertTrue((wizard / 'startup.py').is_file())

            sys.path.insert(0, str(ROOT / 'addons/service.subtitles.kodipovilai'))
            try:
                from resources.lib import wizard_self_healer, modular_legacy_bootstrap
                with mock.patch.object(
                        modular_legacy_bootstrap,
                        'ensure_bootstrapped', return_value='ready'):
                    self.assertEqual(wizard_self_healer.ensure_healed(),
                                     'modular_ready')
                with mock.patch.object(
                        modular_legacy_bootstrap,
                        'ensure_bootstrapped', return_value='not_requested'):
                    self.assertEqual(wizard_self_healer.ensure_healed(),
                                     'no_kodi')
            finally:
                sys.path.remove(str(ROOT / 'addons/service.subtitles.kodipovilai'))


if __name__ == '__main__':
    unittest.main()
