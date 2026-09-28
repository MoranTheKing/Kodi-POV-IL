"""A failed or interrupted MoranSubs OTA must leave a working old add-on."""

import importlib.util
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


SOURCE = (Path(__file__).resolve().parents[1] /
          'plugin.program.kodipovilwizard/resources/libs/staged_addon_install.py')
spec = importlib.util.spec_from_file_location('staged_addon_install', SOURCE)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
ADDON = 'service.subtitles.kodipovilai'


class StagedInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addons = Path(self.tmp.name) / 'addons'
        self.addons.mkdir()
        self.old = self.addons / ADDON
        self.old.mkdir()
        (self.old / 'addon.xml').write_text(
            '<addon id="%s" version="0.2.566" />' % ADDON, encoding='utf-8')
        (self.old / 'old.py').write_text('old code', encoding='utf-8')
        packages = Path(self.tmp.name) / 'userdata/ota-packages'
        packages.mkdir(parents=True)
        self.bundle = packages / (ADDON + '_update.zip')

    def tearDown(self):
        self.tmp.cleanup()

    def bundle_with(self, payload=None, addon_id=ADDON):
        if payload is None:
            payload = {'addon.xml': '<addon id="%s" version="0.3.15" />' % addon_id,
                       'service.py': 'new code'}
        with zipfile.ZipFile(self.bundle, 'w', zipfile.ZIP_STORED) as archive:
            for rel, data in payload.items():
                archive.writestr(addon_id + '/' + rel, data)

    def install(self):
        digest = hashlib.sha256(self.bundle.read_bytes()).hexdigest()
        return installer.install(self.bundle, self.addons, ADDON, '0.3.15', digest)

    def test_full_swap_and_recovery_are_idempotent(self):
        self.bundle_with()
        self.assertEqual(self.install(), 2)
        self.assertEqual((self.old / 'service.py').read_text(), 'new code')
        self.assertFalse((self.old / 'old.py').exists())
        installer.recover(self.addons, self.bundle, ADDON)
        self.assertEqual((self.old / 'service.py').read_text(), 'new code')

    def test_bad_package_does_not_change_old_addon(self):
        self.bundle_with(addon_id='wrong.addon')
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual((self.old / 'old.py').read_text(), 'old code')

    def test_wrong_digest_or_unsupported_compression_keeps_old_addon(self):
        self.bundle_with()
        with self.assertRaises(ValueError):
            installer.install(self.bundle, self.addons, ADDON, '0.3.15', '0' * 64)
        with zipfile.ZipFile(self.bundle, 'w', zipfile.ZIP_BZIP2) as archive:
            archive.writestr(ADDON + '/addon.xml',
                             '<addon id="%s" version="0.3.15" />' % ADDON)
            archive.writestr(ADDON + '/service.py', 'new code')
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual((self.old / 'old.py').read_text(), 'old code')

    def test_deflated_package_swaps_atomically(self):
        with zipfile.ZipFile(self.bundle, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(ADDON + '/addon.xml',
                             '<addon id="%s" version="0.3.15" />' % ADDON)
            archive.writestr(ADDON + '/service.py', 'new code')
        self.assertEqual(self.install(), 2)
        self.assertEqual((self.old / 'service.py').read_text(), 'new code')

    def test_prepared_package_survives_reboot_without_touching_old_service(self):
        self.bundle_with()
        digest = hashlib.sha256(self.bundle.read_bytes()).hexdigest()
        self.assertEqual(installer.install(self.bundle, self.addons, ADDON,
                                           '0.3.15', digest, defer_swap=True), 2)
        self.assertEqual((self.old / 'old.py').read_text(), 'old code')
        installer.recover(self.addons, self.bundle, ADDON)
        self.assertEqual(installer.activate_prepared(self.addons, ADDON,
                                                     '0.3.15', digest), 2)
        self.assertEqual((self.old / 'service.py').read_text(), 'new code')

    def test_handoff_requires_matching_fresh_ack(self):
        userdata = Path(self.tmp.name) / 'userdata'
        plan = installer.request_handoff(userdata, '0.3.15', 'a' * 64)
        self.assertEqual(installer.read_handoff(userdata), (plan, None))
        ack_path = userdata / installer.ACK_NAME
        ack_path.write_text(json.dumps({'schema': 1, 'token': 'b' * 32,
                                        'acked': plan['created']}), encoding='utf-8')
        self.assertEqual(installer.read_handoff(userdata), (plan, None))
        ack_path.write_text(json.dumps({'schema': 1, 'token': plan['token'],
                                        'acked': plan['created']}), encoding='utf-8')
        self.assertIsNotNone(installer.read_handoff(userdata)[1])
        installer.clear_handoff(userdata)
        self.assertEqual(installer.read_handoff(userdata), (None, None))

    def test_python_fallback_when_kodi_extractor_is_unavailable(self):
        self.bundle_with()
        with mock.patch.object(installer, '_extract_kodi', return_value=False):
            self.assertEqual(self.install(), 2)
        self.assertEqual((self.old / 'service.py').read_text(), 'new code')

    def test_traversal_or_case_duplicate_never_reaches_live_addon(self):
        for bad_member in (ADDON + '/../escape.py', ADDON + '/SERVICE.py',
                           ADDON + '/NUL.py', ADDON + '/data:stream'):
            with self.subTest(bad_member=bad_member):
                with zipfile.ZipFile(self.bundle, 'w') as archive:
                    archive.writestr(ADDON + '/addon.xml',
                                     '<addon id="%s" version="0.3.15" />' % ADDON)
                    archive.writestr(ADDON + '/service.py', 'new code')
                    archive.writestr(bad_member, 'bad')
                with self.assertRaises(ValueError):
                    self.install()
                self.assertEqual((self.old / 'old.py').read_text(), 'old code')

    def test_failed_swap_restores_old_addon(self):
        self.bundle_with()
        real_replace = installer.os.replace

        def fail_new_stage(source, destination):
            if str(source).endswith('.kodipovil-ms-new'):
                raise PermissionError('simulated file lock')
            return real_replace(source, destination)

        with mock.patch.object(installer.os, 'replace', side_effect=fail_new_stage):
            with self.assertRaises(PermissionError):
                self.install()
        self.assertEqual((self.old / 'old.py').read_text(), 'old code')

    def test_next_boot_restores_backup_after_interrupted_swap(self):
        self.bundle_with()
        target, stage, backup = installer._paths(self.addons, self.bundle, ADDON)
        backup.parent.mkdir(parents=True, exist_ok=True)
        target.rename(backup)
        stage.mkdir()
        (stage / 'partial.py').write_text('partial', encoding='utf-8')
        installer.recover(self.addons, self.bundle, ADDON)
        self.assertEqual((target / 'old.py').read_text(), 'old code')
        self.assertFalse(backup.exists())
        self.assertFalse(stage.exists())


if __name__ == '__main__':
    unittest.main()
