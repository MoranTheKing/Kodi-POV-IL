"""Large modular add-ons are verified before replacing the installed tree."""

import hashlib
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


SOURCE = (Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard'
          / 'resources' / 'libs' / 'staged_addon_install.py')
spec = importlib.util.spec_from_file_location('staged_addon_install_generic', SOURCE)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class GenericStagedInstallTests(unittest.TestCase):
    def test_generic_update_keeps_prepared_service_handoff(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            addons = root / 'addons'
            addons.mkdir()
            for addon_id, version, defer in (
                    ('service.subtitles.kodipovilai', '0.3.15', True),
                    ('skin.fentastic', '1.0.29', False)):
                package = root / (addon_id + '.zip')
                with zipfile.ZipFile(package, 'w') as archive:
                    archive.writestr(addon_id + '/addon.xml',
                                     '<addon id="{}" version="{}"/>'.format(addon_id, version))
                digest = hashlib.sha256(package.read_bytes()).hexdigest()
                installer.install(package, addons, addon_id, version, digest,
                                  defer_swap=defer)
                if defer:
                    service_digest = digest
            self.assertTrue(installer.prepared_matches(
                addons, 'service.subtitles.kodipovilai', '0.3.15', service_digest))
            self.assertEqual(installer.activate_prepared(
                addons, 'service.subtitles.kodipovilai', '0.3.15', service_digest), 1)

    def test_skin_package_is_complete_before_atomic_swap(self):
        addon_id = 'skin.fentastic'
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            addons = root / 'addons'
            target = addons / addon_id
            target.mkdir(parents=True)
            (target / 'addon.xml').write_text(
                '<addon id="skin.fentastic" version="1.0.25"/>', encoding='utf-8')
            (target / 'old.xml').write_text('keep until complete', encoding='utf-8')
            package = root / 'skin.zip'
            with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(addon_id + '/addon.xml',
                                 '<addon id="skin.fentastic" version="1.0.29"/>')
                for index in range(1200):
                    archive.writestr(addon_id + '/xml/part-%04d.xml' % index,
                                     '<window>%d</window>' % index)
            digest = hashlib.sha256(package.read_bytes()).hexdigest()
            count = installer.install(package, addons, addon_id, '1.0.29', digest)
            self.assertEqual(count, 1201)
            self.assertFalse((target / 'old.xml').exists())
            self.assertEqual(len(list((target / 'xml').glob('*.xml'))), 1200)
            self.assertFalse(installer._paths(addons, package, addon_id)[2].exists())

    def test_interrupted_swap_restores_old_addon(self):
        addon_id = 'repository.Fishenzon'
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            addons = root / 'addons'
            target = addons / addon_id
            target.mkdir(parents=True)
            (target / 'addon.xml').write_text(
                '<addon id="repository.Fishenzon" version="1.0.2"/>',
                encoding='utf-8')
            package = root / 'repo.zip'
            with zipfile.ZipFile(package, 'w') as archive:
                archive.writestr(addon_id + '/addon.xml',
                                 '<addon id="repository.Fishenzon" version="1.0.3"/>')
            digest = hashlib.sha256(package.read_bytes()).hexdigest()
            real_replace = installer.os.replace
            target_path, stage, backup = installer._paths(addons, package, addon_id)

            def fail_stage(source, destination):
                if str(source) == str(stage) and str(destination) == str(target_path):
                    raise PermissionError('simulated interrupted swap')
                return real_replace(source, destination)

            with mock.patch.object(installer.os, 'replace', side_effect=fail_stage):
                with self.assertRaises(PermissionError):
                    installer.install(package, addons, addon_id, '1.0.3', digest)
            self.assertEqual((target / 'addon.xml').read_text(encoding='utf-8'),
                             '<addon id="repository.Fishenzon" version="1.0.2"/>')
            installer.recover(addons, package, addon_id)
            self.assertFalse(backup.exists())


if __name__ == '__main__':
    unittest.main()
