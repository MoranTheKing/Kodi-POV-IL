"""The release generator must retain and validate the clean POV migration pin."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '.github/scripts/gen_manifest.py'
spec = importlib.util.spec_from_file_location('qa_gen_manifest', SOURCE)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class ManifestHostPinTests(unittest.TestCase):
    def test_mirror_requires_owned_release_and_official_provenance(self):
        pin = generator._pov_host_migration()
        pin['zip'] = ('https://github.com/MoranTheKing/Kodi-POV-IL/releases/download/'
                      'addons-latest/official-' + pin['filename'])
        pin['upstream_zip'] = 'https://kodifitzwell.github.io/repo/plugin.video.pov/' + pin['filename']
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'pin.json'
            with mock.patch.object(generator, 'POV_HOST_MIGRATION', str(path)):
                path.write_text(json.dumps(pin))
                self.assertEqual(generator._pov_host_migration()['sha256'], pin['sha256'])
                for invalid in (dict(pin, zip=pin['zip'].replace('MoranTheKing', 'other')),
                                dict(pin, upstream_zip='https://example.org/host.zip')):
                    path.write_text(json.dumps(invalid))
                    with self.assertRaises(ValueError):
                        generator._pov_host_migration()

    def test_official_pin_is_emitted_and_bad_hash_is_rejected(self):
        official = generator._pov_host_migration()
        self.assertEqual(official['id'], 'plugin.video.pov')
        self.assertEqual(official['version'], '6.10.04')
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'manifest.json'
            # This unit test checks pin propagation, independent of whether
            # CI has already packaged every addon in dist/.
            with mock.patch.object(generator, 'MANIFEST_OUT', str(path)), \
                    mock.patch.object(generator, 'discover_addons', return_value=[]), \
                    mock.patch.object(generator, '_config_entry', return_value={
                        'config_version': 'test', 'filename': 'config-test.zip',
                        'size': 1, 'sha256': 'a' * 64}):
                self.assertEqual(generator.main(), 0)
            emitted = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(emitted['pov_host_migration'], official)
            pin_path = Path(raw) / 'bad-pin.json'
            pin_path.write_text(json.dumps(dict(official, sha256='0')),
                                encoding='utf-8')
            with mock.patch.object(generator, 'POV_HOST_MIGRATION', str(pin_path)):
                with self.assertRaises(ValueError):
                    generator._pov_host_migration()


if __name__ == '__main__':
    unittest.main()
