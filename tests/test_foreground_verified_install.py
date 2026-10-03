"""Foreground jobs cannot advertise addon.xml from an incomplete install."""
import hashlib
import os
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from test_provisioning_gate import ROOT, _load_function
from test_personal_list_order import load

LIBS = ROOT / 'plugin.program.kodipovilwizard/resources/libs'
receipt = load('qa_foreground_receipt', LIBS / 'addon_install_receipt.py')
staged = load('qa_foreground_staged', LIBS / 'staged_addon_install.py')


class ForegroundVerifiedInstallTests(unittest.TestCase):
    def test_upstream_hashless_job_is_verified_and_failed_swap_keeps_retry_receipt(self):
        for pinned in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                home = Path(directory); addons = home / 'addons'; addons.mkdir()
                data = home / 'userdata'; data.mkdir()
                target = addons / 'script.test'; target.mkdir()
                (target / 'addon.xml').write_text('<addon id="script.test" version="1.0"/>')
                (target / 'old.py').write_text('old')
                package = home / 'addon.zip'
                with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as z:
                    z.writestr('script.test/addon.xml', '<addon id="script.test" version="2.0"/>')
                    z.writestr('script.test/default.py', 'complete')
                job = {'id': 'script.test', 'version': '2.0'}
                digest = hashlib.sha256(package.read_bytes()).hexdigest()
                if pinned: job['sha256'] = digest
                progress = []
                fn = _load_function(LIBS / 'gui/install_manager.py', '_install_job', {
                    'os': os, 'CONFIG': types.SimpleNamespace(ADDONS=str(addons),
                        ADDON_DATA=str(data), ADDON_ID='wizard.test'),
                    'config_apply': types.SimpleNamespace(sha256_file=lambda _p: digest),
                    'logging': types.SimpleNamespace(log=lambda *a, **k: None),
                    'xbmc': types.SimpleNamespace(LOGERROR=4)})
                lib = types.ModuleType('resources.libs')
                lib.addon_install_receipt = receipt; lib.staged_addon_install = staged
                with patch.dict(sys.modules, {'resources.libs': lib}):
                    with patch.object(staged, 'install', side_effect=OSError('disk unavailable')):
                        self.assertFalse(fn(job, str(package), lambda *a: progress.append(a)))
                    self.assertEqual(receipt.needs_retry(str(data / 'wizard.test'), 'script.test'), pinned)
                    self.assertIn('1.0', (target / 'addon.xml').read_text())
                    self.assertEqual((target / 'old.py').read_text(), 'old')
                    self.assertTrue(fn(job, str(package), lambda *a: progress.append(a)))
                self.assertFalse(receipt.needs_retry(str(data / 'wizard.test'), 'script.test'))
                self.assertEqual((target / 'default.py').read_text(), 'complete')
                self.assertFalse((target / 'old.py').exists())
                self.assertEqual(progress[-1], (2, 2))


if __name__ == '__main__': unittest.main()
