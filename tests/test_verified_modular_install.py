"""Fresh and fallback OTA repairs must clear receipts only after a full swap."""
import hashlib
import importlib.util
import os
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock
from test_provisioning_gate import _load_function

LIBS = Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard/resources/libs'
ADDON = 'service.subtitles.kodipovilai'


def load(name):
    spec = importlib.util.spec_from_file_location(name, LIBS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VerifiedModuleTests(unittest.TestCase):
    def test_partial_disabled_service_repairs_and_clears_old_failure(self):
        stage, receipt = load('staged_addon_install'), load('addon_install_receipt')
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            addons = base / 'addons'
            target = addons / ADDON
            target.mkdir(parents=True)
            (target / 'addon.xml').write_text('<addon id="%s" version="0.3.23"/>' % ADDON)
            package = base / 'subs.zip'
            with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(ADDON + '/addon.xml', '<addon id="%s" version="0.3.24"/>' % ADDON)
                archive.writestr(ADDON + '/service.py', 'complete service')
            digest = hashlib.sha256(package.read_bytes()).hexdigest()
            config = types.SimpleNamespace(ADDON_DATA=str(base / 'userdata/addon_data'),
                                           ADDON_ID='plugin.program.kodipovilwizard', ADDONS=str(addons))
            fn = _load_function(LIBS / 'modular_updater.py', '_install_verified_module',
                                dict(os=os, CONFIG=config), class_name='ModularUpdater')
            updater = types.SimpleNamespace(_on_disk=lambda _id: target.exists(),
                                            _runtime_addon_enabled=lambda _id: False)
            data = os.path.join(config.ADDON_DATA, config.ADDON_ID)
            receipt.begin(data, ADDON, '0.3.23', digest)
            module = types.ModuleType('resources.libs')
            module.staged_addon_install, module.addon_install_receipt = stage, receipt
            with mock.patch.dict(sys.modules, {'resources.libs': module}), mock.patch.object(stage, '_extract_kodi', return_value=False):
                # A corrupt/truncated package keeps the retry record and old tree.
                with self.assertRaises(ValueError):
                    fn(updater, package, dict(id=ADDON, version='0.3.24'), '0' * 64)
                self.assertTrue(receipt.needs_retry(data, ADDON))
                self.assertFalse((target / 'service.py').exists())
                self.assertEqual(fn(updater, package, dict(id=ADDON, version='0.3.24'), digest), 2)
                self.assertFalse(receipt.needs_retry(data, ADDON))
                self.assertEqual((target / 'service.py').read_text(), 'complete service')
                updater._runtime_addon_enabled = lambda _id: True
                with self.assertRaisesRegex(RuntimeError, 'live'):
                    fn(updater, package, dict(id=ADDON, version='0.3.24'), digest)
                self.assertEqual((target / 'service.py').read_text(), 'complete service')


if __name__ == '__main__':
    unittest.main()
