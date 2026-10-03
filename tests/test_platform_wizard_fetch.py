"""Every installer must consume the same published Wizard, without app prompts."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('platform_fetch', ROOT / '.github/scripts/fetch_platform_wizard.py')
fetcher = importlib.util.module_from_spec(spec); spec.loader.exec_module(fetcher)


class PlatformWizardFetchTests(unittest.TestCase):
    def fixture(self, directory, *, version='0.4.15', extra=None):
        directory = Path(directory); buffer = io.BytesIO()
        with ZipFile(buffer, 'w') as z:
            base = fetcher.ADDON + '/'
            z.writestr(base + 'addon.xml', '<addon id="' + fetcher.ADDON + '" version="' + version + '"/>')
            for name in ('fresh_install.py', 'modular_updater.py'):
                z.writestr(base + 'resources/libs/' + name, '# verified code')
            if extra: z.writestr(extra, '# invalid')
        data = buffer.getvalue()
        entry = dict(version='0.4.15', size=len(data), sha256=hashlib.sha256(data).hexdigest(), zip='https://example.test/wizard.zip')
        manifest = directory / 'manifest.json'
        manifest.write_text(json.dumps({'addons': {fetcher.ADDON: entry}}))
        source = directory / 'addon.xml'; source.write_text('<addon id="' + fetcher.ADDON + '" version="0.4.15"/>')
        return manifest, source, directory / 'dist', directory / 'env', data

    def test_verified_payload_is_preserved_and_version_derived(self):
        with tempfile.TemporaryDirectory() as raw:
            args = self.fixture(raw)
            with patch.object(fetcher, 'urlopen', return_value=io.BytesIO(args[-1])):
                target = fetcher.fetch(*args[:-1])
            self.assertEqual(target.read_bytes(), args[-1])
            self.assertEqual(args[3].read_text(), 'WIZARD_VERSION=0.4.15\n')

    def test_unpublished_source_is_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as raw:
            args = self.fixture(raw); args[1].write_text('<addon id="' + fetcher.ADDON + '" version="0.4.16"/>')
            with patch.object(fetcher, 'urlopen') as download, self.assertRaises(ValueError):
                fetcher.fetch(*args[:-1])
            download.assert_not_called()
            self.assertFalse(args[3].exists())

    def test_bad_hash_cannot_publish_an_installer_input(self):
        with tempfile.TemporaryDirectory() as raw:
            args = self.fixture(raw)
            with patch.object(fetcher, 'urlopen', return_value=io.BytesIO(args[-1] + b'bad')), self.assertRaises(ValueError):
                fetcher.fetch(*args[:-1])
            self.assertFalse(args[2].exists()); self.assertFalse(args[3].exists())

    def test_identity_and_archive_paths_are_verified_even_with_matching_hash(self):
        for options in ({'version': '0.4.14'}, {'extra': 'plugin.program.kodipovilwizard/../escape.py'}, {'extra': 'other/addon.xml'}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as raw:
                args = self.fixture(raw, **options)
                with patch.object(fetcher, 'urlopen', return_value=io.BytesIO(args[-1])), self.assertRaises(ValueError):
                    fetcher.fetch(*args[:-1])
                self.assertFalse(args[3].exists())

    def test_workflow_has_no_stale_wizard_or_new_notification_baseline(self):
        text = (ROOT / '.github/workflows/build-apk.yml').read_text('utf8')
        self.assertIn('fetch_platform_wizard.py', text)
        self.assertNotIn("WIZARD_VERSION: '", text)
        self.assertEqual(text.count('plugin.program.kodipovilwizard-${WIZARD_VERSION}.zip'), 4)
        self.assertNotIn('gh release delete', text)
        self.assertNotIn('latest_apk_version.txt', text)
        self.assertNotIn('latest_windows_version.txt', text)
        for platform in ('apk', 'windows'):
            pointer = ROOT / ('wizard/assets/kodi_version_auto_update/' + platform + '/latest_' + platform + '_version.txt')
            self.assertEqual(pointer.read_text().strip(), '21.3-povil.49')


if __name__ == '__main__': unittest.main()
