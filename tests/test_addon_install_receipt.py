"""An interrupted OTA must not become 'up to date' by writing addon.xml."""

import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard'
          / 'resources' / 'libs' / 'addon_install_receipt.py')
spec = importlib.util.spec_from_file_location('addon_install_receipt', SOURCE)
receipt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receipt)


class InterruptedAddonInstallTests(unittest.TestCase):
    def test_partial_same_version_retries_until_every_file_is_present(self):
        addon_id = 'plugin.program.orderfavourites-hebrew'
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            data = root / 'data'
            addons = root / 'addons'
            target = addons / addon_id
            target.mkdir(parents=True)
            package = root / 'package.zip'
            members = {
                addon_id + '/addon.xml':
                    '<addon id="{}" version="1.4.5"/>'.format(addon_id).encode(),
                addon_id + '/service.py': b'new service',
                addon_id + '/resources/icon.png': b'icon bytes',
            }
            with zipfile.ZipFile(package, 'w') as archive:
                for name, payload in members.items():
                    archive.writestr(name, payload)
            receipt.begin(str(data), addon_id, '1.4.5', 'a' * 64)
            (target / 'addon.xml').write_bytes(members[addon_id + '/addon.xml'])
            self.assertTrue(receipt.needs_retry(str(data), addon_id))
            with self.assertRaisesRegex(IOError, 'absent'):
                receipt.verify(str(package), str(addons), addon_id, '1.4.5')
            self.assertTrue(receipt.needs_retry(str(data), addon_id))
            (target / 'service.py').write_bytes(b'old service')
            (target / 'resources').mkdir()
            (target / 'resources' / 'icon.png').write_bytes(members[addon_id + '/resources/icon.png'])
            with self.assertRaisesRegex(IOError, 'differs'):
                receipt.verify(str(package), str(addons), addon_id, '1.4.5')
            (target / 'service.py').write_bytes(members[addon_id + '/service.py'])
            self.assertEqual(receipt.verify(str(package), str(addons), addon_id, '1.4.5'), 3)
            receipt.complete(str(data), addon_id)
            self.assertFalse(receipt.needs_retry(str(data), addon_id))

    def test_rejects_unsafe_addon_id(self):
        with tempfile.TemporaryDirectory() as root:
            for valid in ('repository.Fishenzon', 'repository.709',
                          'plugin.program.orderfavourites-hebrew'):
                self.assertFalse(receipt.needs_retry(root, valid))
            with self.assertRaises(ValueError):
                receipt.begin(root, '../outside', '1', 'a' * 64)


if __name__ == '__main__':
    unittest.main()
