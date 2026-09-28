#!/usr/bin/env python3
"""Exercise the dormant host transaction against fake Kodi trees only."""

import hashlib
import importlib.util
import json
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE = (ROOT / 'wizard/source/plugin.program.kodipovilwizard/resources'
          / 'libs/modular_host_migration.py')
spec = importlib.util.spec_from_file_location('modular_host_migration', MODULE)
assert spec and spec.loader
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class HostMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addons = self.root / 'addons'
        self.addons.mkdir()
        self.host = self.addons / migration.ADDON_ID
        self.host.mkdir()
        (self.host / 'addon.xml').write_text(
            '<addon id="plugin.video.pov" version="6.09.03"/>',
            encoding='utf-8')
        (self.host / 'old-marker.txt').write_text('old patched host', encoding='utf-8')
        self.userdata = self.root / 'userdata/addon_data/plugin.video.pov'
        self.userdata.mkdir(parents=True)
        (self.userdata / 'settings.xml').write_text(
            '<settings><setting id="token">private-test-value</setting></settings>',
            encoding='utf-8')
        self.user_bytes = (self.userdata / 'settings.xml').read_bytes()
        self.archive = self.root / 'clean-pov.zip'
        self.members = {
            'plugin.video.pov/addon.xml':
                b'<addon id="plugin.video.pov" version="6.09.05"/>',
            'plugin.video.pov/resources/lib/clean.py': b'VALUE = 1\n',
        }
        self._make_zip()

    def _make_zip(self, members=None):
        with zipfile.ZipFile(self.archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for name, data in (members or self.members).items():
                bundle.writestr(name, data)
        return hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def _stage(self, digest=None, check=None):
        return migration.stage_clean_host(
            self.archive, self.host,
            digest or hashlib.sha256(self.archive.read_bytes()).hexdigest(),
            '6.09.05', check or (lambda p: (p / 'resources/lib/clean.py').is_file()))

    def _assert_user_data(self):
        self.assertEqual((self.userdata / 'settings.xml').read_bytes(), self.user_bytes)

    def test_stage_activate_confirm_keeps_backup_and_user_data(self):
        staged = self._stage()
        self.assertTrue((self.host / 'old-marker.txt').is_file())
        backup = migration.activate_staged_host(staged, self.host)
        self.assertTrue((self.host / 'resources/lib/clean.py').is_file())
        self.assertTrue((backup / 'old-marker.txt').is_file())
        journal = json.loads((self.addons / migration.JOURNAL_NAME).read_text())
        self.assertEqual(journal['state'], 'pending_validation')
        self._assert_user_data()
        migration.confirm_host(self.host, lambda p: (p / 'resources/lib/clean.py').is_file())
        self.assertTrue(backup.is_dir())
        with self.assertRaises(migration.MigrationError):
            migration.rollback_host(self.host)
        migration.rollback_host(self.host, allow_confirmed=True)
        self.assertTrue((self.host / 'old-marker.txt').is_file())
        self._assert_user_data()

    def test_failed_post_switch_check_restores_old_tree(self):
        staged = self._stage()
        migration.activate_staged_host(staged, self.host)
        with self.assertRaisesRegex(migration.MigrationError, 'old host restored'):
            migration.confirm_host(self.host, lambda _p: False)
        self.assertTrue((self.host / 'old-marker.txt').is_file())
        self.assertEqual(json.loads((self.addons / migration.JOURNAL_NAME).read_text())['state'],
                         'rolled_back')
        self._assert_user_data()

    def test_raised_health_check_also_rolls_back(self):
        staged = self._stage()
        migration.activate_staged_host(staged, self.host)

        def broken(_path):
            raise RuntimeError('synthetic Kodi health failure')

        with self.assertRaises(migration.MigrationError):
            migration.confirm_host(self.host, broken)
        self.assertTrue((self.host / 'old-marker.txt').is_file())

    def test_mid_swap_failure_restores_old_tree(self):
        staged = self._stage()
        real_replace = os.replace

        def fail_staged_move(src, dst):
            if Path(src) == staged and Path(dst) == self.host:
                raise OSError('synthetic second rename failure')
            return real_replace(src, dst)

        with patch.object(migration.os, 'replace', side_effect=fail_staged_move):
            with self.assertRaises(OSError):
                migration.activate_staged_host(staged, self.host)
        self.assertTrue((self.host / 'old-marker.txt').is_file())
        self._assert_user_data()

    def test_crash_after_old_move_can_be_recovered(self):
        suffix = '0' * 32
        migration._write_journal(self.addons / migration.JOURNAL_NAME,
                                 'prepared', suffix)
        backup = self.addons / (migration.BACKUP_PREFIX + suffix)
        os.replace(self.host, backup)
        self.assertFalse(self.host.exists())
        self.assertEqual(migration.recover_unconfirmed(self.host), 'restored')
        self.assertTrue((self.host / 'old-marker.txt').is_file())
        self._assert_user_data()

    def test_crash_after_new_host_move_quarantines_it(self):
        staged = self._stage()
        backup = migration.activate_staged_host(staged, self.host)
        self.assertEqual(migration.recover_unconfirmed(self.host), 'restored')
        self.assertTrue((self.host / 'old-marker.txt').is_file())
        self.assertFalse(backup.exists())
        self.assertEqual(migration.recover_unconfirmed(self.host), 'rolled_back')
        self._assert_user_data()

    def test_recovery_interrupted_after_backup_restoration_is_idempotent(self):
        staged = self._stage()
        backup = migration.activate_staged_host(staged, self.host)
        journal = self.addons / migration.JOURNAL_NAME
        suffix = json.loads(journal.read_text())['suffix']
        failed = self.addons / (migration.FAILED_PREFIX + suffix)
        migration._write_journal(journal, 'rollback_in_progress', suffix)
        os.replace(self.host, failed)
        os.replace(backup, self.host)
        self.assertEqual(migration.recover_unconfirmed(self.host), 'restored')
        self.assertTrue((self.host / 'old-marker.txt').is_file())
        self.assertEqual(json.loads(journal.read_text())['state'], 'rolled_back')

    def test_recovery_interrupted_when_old_host_was_absent(self):
        suffix = '2' * 32
        journal = self.addons / migration.JOURNAL_NAME
        backup = self.addons / (migration.BACKUP_PREFIX + suffix)
        migration._write_journal(journal, 'rollback_in_progress', suffix)
        os.replace(self.host, backup)
        os.replace(backup, self.host)
        self.assertEqual(migration.recover_unconfirmed(self.host), 'restored')
        self.assertTrue((self.host / 'old-marker.txt').is_file())

    def test_prepared_no_swap_then_retry(self):
        suffix = '1' * 32
        journal = self.addons / migration.JOURNAL_NAME
        migration._write_journal(journal, 'prepared', suffix)
        self.assertEqual(migration.recover_unconfirmed(self.host), 'not_swapped')
        staged = self._stage()
        migration.activate_staged_host(staged, self.host)
        self.assertTrue((self.host / 'resources/lib/clean.py').is_file())
        self.assertTrue((self.addons / (migration.JOURNAL_NAME + '.history-' + suffix)).is_file())

    def test_confirmed_host_is_not_automatically_reverted(self):
        staged = self._stage()
        backup = migration.activate_staged_host(staged, self.host)
        migration.confirm_host(self.host, lambda _p: True)
        self.assertEqual(migration.recover_unconfirmed(self.host), 'confirmed')
        self.assertTrue((self.host / 'resources/lib/clean.py').is_file())
        self.assertTrue((backup / 'old-marker.txt').is_file())

    def test_wrong_digest_or_health_failure_cannot_touch_host(self):
        with self.assertRaisesRegex(migration.MigrationError, 'SHA-256 mismatch'):
            self._stage('0' * 64)
        with self.assertRaisesRegex(migration.MigrationError, 'health check failed'):
            self._stage(check=lambda _p: False)
        self.assertTrue((self.host / 'old-marker.txt').is_file())
        self.assertFalse((self.addons / migration.JOURNAL_NAME).exists())
        self._assert_user_data()

    def test_rejects_wrong_identity_and_traversal(self):
        bad_sets = [
            {'plugin.video.pov/addon.xml':
             b'<addon id="plugin.video.umbrella" version="6.09.05"/>'},
            dict(self.members, **{'plugin.video.pov/../escape.txt': b'escape'}),
            dict(self.members, **{'other.addon/evil.py': b'evil'}),
        ]
        for members in bad_sets:
            digest = self._make_zip(members)
            with self.assertRaises(migration.MigrationError):
                self._stage(digest)
            self.assertTrue((self.host / 'old-marker.txt').is_file())
            self.assertFalse((self.root / 'escape.txt').exists())

    def test_rejects_symlink_and_case_duplicate(self):
        with zipfile.ZipFile(self.archive, 'w') as bundle:
            for name, data in self.members.items():
                bundle.writestr(name, data)
            link = zipfile.ZipInfo('plugin.video.pov/resources/lib/link.py')
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(link, '../../outside')
        with self.assertRaisesRegex(migration.MigrationError, 'special file'):
            self._stage()

        with zipfile.ZipFile(self.archive, 'w') as bundle:
            for name, data in self.members.items():
                bundle.writestr(name, data)
            bundle.writestr('plugin.video.pov/RESOURCES/lib/clean.py', b'other')
        with self.assertRaisesRegex(migration.MigrationError, 'duplicate'):
            self._stage()

    def test_rejects_windows_path_aliases_and_special_devices(self):
        for alias in ('plugin.video.pov/resources/CON.txt',
                      'plugin.video.pov/resources/dir./file.py',
                      'plugin.video.pov/resources/dir /file.py',
                      'plugin.video.pov\\resources\\lib\\clean.py'):
            digest = self._make_zip(dict(self.members, **{alias: b'bad'}))
            with self.assertRaises(migration.MigrationError):
                self._stage(digest)
            self.assertTrue((self.host / 'old-marker.txt').is_file())


if __name__ == '__main__':
    unittest.main()
