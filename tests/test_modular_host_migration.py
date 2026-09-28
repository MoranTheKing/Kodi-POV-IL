"""The clean POV host moves atomically and can be rolled back without userdata."""

import hashlib
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] /
          'plugin.program.kodipovilwizard/resources/libs/modular_host_migration.py')
spec = importlib.util.spec_from_file_location('candidate_modular_host_migration', SOURCE)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class HostMigrationTests(unittest.TestCase):
    def test_staged_swap_and_rollback_keep_original_and_userdata(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            addons = root / 'addons'
            host = addons / 'plugin.video.pov'
            host.mkdir(parents=True)
            (host / 'addon.xml').write_text(
                '<addon id="plugin.video.pov" version="6.09.04"/>', encoding='utf-8')
            (host / 'old.py').write_text('legacy = True\n', encoding='utf-8')
            userdata = root / 'userdata/addon_data/plugin.video.pov/settings.xml'
            userdata.parent.mkdir(parents=True)
            userdata.write_text('<settings>keep-account</settings>', encoding='utf-8')
            archive = root / 'official.zip'
            with zipfile.ZipFile(archive, 'w') as zf:
                zf.writestr('plugin.video.pov/addon.xml',
                            '<addon id="plugin.video.pov" version="6.09.06"/>')
                zf.writestr('plugin.video.pov/new.py', 'clean = True\n')
            sha = hashlib.sha256(archive.read_bytes()).hexdigest()
            staged = migration.stage_clean_host(
                archive, host, sha, '6.09.06',
                lambda path: (path / 'new.py').is_file())
            self.assertEqual(staged.parent.parent, root,
                             'stage must not be visible to Kodi addon scanner')
            self.assertTrue((host / 'old.py').exists())
            backup = migration.activate_staged_host(staged, host)
            self.assertEqual(backup.parent, root)
            migration.confirm_host(host, lambda path: (path / 'new.py').is_file())
            migration.rollback_host(host, allow_confirmed=True)
            self.assertTrue((host / 'old.py').is_file())
            self.assertEqual(userdata.read_text(encoding='utf-8'),
                             '<settings>keep-account</settings>')

    def test_wrong_hash_never_touches_installed_host(self):
        with tempfile.TemporaryDirectory() as raw:
            host = Path(raw) / 'addons/plugin.video.pov'
            host.mkdir(parents=True)
            (host / 'addon.xml').write_text('old', encoding='utf-8')
            archive = Path(raw) / 'official.zip'
            with zipfile.ZipFile(archive, 'w') as zf:
                zf.writestr('plugin.video.pov/addon.xml',
                            '<addon id="plugin.video.pov" version="6.09.06"/>')
            with self.assertRaises(migration.MigrationError):
                migration.stage_clean_host(archive, host, '0' * 64, '6.09.06',
                                           lambda _path: True)
            self.assertEqual((host / 'addon.xml').read_text(encoding='utf-8'), 'old')


if __name__ == '__main__':
    unittest.main()
